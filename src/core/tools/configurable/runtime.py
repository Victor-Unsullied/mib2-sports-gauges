"""Hash-gated Sports transactions with durable, repeatable recovery."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
import zipfile
import uuid
import durable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
import selection
import compatibility
import device
import transport

REMOTE = '/persistence/golf-sports-configurator'
OPTIONS = REMOTE + '/options.properties'
UI = REMOTE + '/sport-ui.jar'
UI_STAGE = REMOTE + '/.sport-ui.stage.jar'
RECEIPT = REMOTE + '/recovery.json'
CONFIG_STATUS = '/tmp/golf-sportconfig.status'
TEMP_STATUS = '/tmp/golf-temperaturefix.status'
SPORT_STATUS = '/tmp/golf-power-torque-v7.status'
STAGE = '/extbin/apps/hmi/HMI/jar/.TestInterface.sports-config-v2.stage.jar'
STATE_ROOT = ROOT.parents[1] / 'state'
STATE = STATE_ROOT / 'native/current.json'
FACTORY = 'de/vw/mib/debuginterface/target/TestInterfaceTargetFactoryImpl.class'


def manifest():
    return json.loads((HERE / 'BUILD.json').read_text(encoding='utf-8'))


def recognized_ui(data):
    build = manifest()
    return data is None or device.sha(data) in [*build['ui_sha256'].values(), *build.get('previous_ui_sha256', [])]


def profile_id(profile):
    return hashlib.sha256(json.dumps(profile['options'], sort_keys=True).encode()).hexdigest()[:16]


def properties(profile, mode):
    options = selection.validate_profile(profile)['options']
    device.require(mode in ('disabled', 'preflight', 'self-write', 'enabled'), 'Unknown native phase')
    rows = [('version', '4'), ('oil', str(options['oil_temperature_fix']).lower()),
            ('coolant', str(options['coolant_temperature_fix']).lower()),
            ('torque', str(options['enable_torque_gauge']).lower()),
            *[(native, str(options[key]).lower()) for native,key in zip(
                ('gauge_boost','gauge_gmeter','gauge_coolant','gauge_power','gauge_oil'), selection.GAUGE_KEYS[:-1])],
            ('power_source', options['power_source']), ('smoothing', options['needle_smoothing']),
            ('power_unit', options['power_unit']),
            *[(key, 'auto' if options[key] is None else str(options[key])) for key in selection.RANGE_KEYS],
            ('mode', mode), ('profile_id', profile_id(profile))]
    return ''.join(key + '=' + value + '\n' for key, value in rows).encode('ascii')


def identify(data):
    digest = device.sha(data)
    for row in manifest()['profiles']:
        if digest in (row['incoming_sha256'], row['configured_sha256']):
            return row, digest == row['configured_sha256']
    raise ValueError('Unknown carrier; no existing correction will be overwritten')


def compose(incoming):
    row, configured = identify(incoming)
    if configured:
        return incoming, row
    build = manifest()
    component_data = (HERE / 'components.jar').read_bytes()
    device.require(device.sha(component_data) == build['components_sha256'], 'Component payload changed')
    with zipfile.ZipFile(io.BytesIO(component_data)) as archive:
        components = {name: archive.read(name) for name in archive.namelist()}
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(incoming)) as source, zipfile.ZipFile(output, 'w') as target:
        original = {name: source.read(name) for name in source.namelist()}
        for info in source.infolist():
            content = bytes.fromhex(row['factory_hex']) if info.filename == FACTORY else components.get(info.filename, original[info.filename])
            target.writestr(info, content)
        for name, data in sorted(components.items()):
            if name not in original:
                info = zipfile.ZipInfo(name, (2026, 10, 29, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                target.writestr(info, data)
    candidate = output.getvalue()
    device.require(device.sha(candidate) == row['configured_sha256'], 'Composed carrier differs from native-test build')
    with zipfile.ZipFile(io.BytesIO(candidate)) as archive:
        changed = [name for name, data in original.items() if archive.read(name) != data]
        device.require(changed == row['changed_existing_entries'], 'Unexpected existing-class changes')
        device.require(all(archive.read(name) == data for name, data in original.items()
                           if name.startswith('golf/thinkbluefix/')), 'Trainer component changed')
    return candidate, row


def verify():
    build = manifest()
    device.require(build['status'] == 'PASS_NATIVE_OPTIONS_AND_GAUGE_TESTS', 'Native configuration validation missing')
    for name, digest in [('components.jar', build['components_sha256']), *build['ui_sha256'].items()]:
        data = (HERE / name).read_bytes()
        device.require(device.sha(data) == digest, 'Configured payload changed: ' + name)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            device.require(archive.testzip() is None, 'Corrupt payload: ' + name)
    # The stock carrier is read from the connected unit and hash-checked by compose()
    # before staging. No full factory carrier is distributed with this package.
    print('PASS: independent temperature flags, six gauge switches, Power source/unit and needle modes; offline only')


def snapshot(ftp, telnet, recovery=False):
    for path, digest in json.loads((HERE / 'protected-files.json').read_text()).items():
        device.require(device.sha(device.fetch(ftp, path)) == digest, 'Protected startup/configuration file changed: ' + path)
    active = device.fetch(ftp, device.ACTIVE)
    row, configured = identify(active)
    processes = device.shell(telnet, '/proc/boot/pidin ar')
    jvms = [line for line in processes.splitlines() if re.match(r'^\s*\d+\s+\S*j9\s', line)]
    healthy = len(jvms) == 1 and 'de.vw.mib.MIBMain' in jvms[0]
    if not recovery:
        device.require(healthy, 'Expected one native HMI JVM')
        device.require('-Dgolf.' not in jvms[0] and '-Xbootclasspath/p:' not in jvms[0]
                       and 'watchdog.sh' not in processes, 'Old trial overlay/watchdog present')
    device.metadata(telnet, device.ACTIVE)
    def text(path):
        data = device.fetch(ftp, path, True)
        return None if data is None else data.decode('ascii', errors='replace')
    return active, row, {'active_sha256': device.sha(active), 'configured': configured,
        'hmi_pid': int(jvms[0].split()[0]) if healthy else None, 'config_status': text(CONFIG_STATUS),
        'temperature_status': text(TEMP_STATUS), 'sports_status': text(SPORT_STATUS)}


def check_health(ftp, row, snap, profile, phase):
    device.require(snap['active_sha256'] == row['configured_sha256'], 'Wrong configured carrier')
    device.require(device.fetch(ftp, OPTIONS) == properties(profile, phase), 'Selected settings or phase changed')
    device.require(device.sha(device.fetch(ftp, UI)) == manifest()['ui_sha256'][row['ui']], 'Configured UI changed')
    status = snap['config_status'] or ''
    device.require(re.fullmatch(r'sportconfig-v4 \d+ ' + phase + ':' + profile_id(profile) + r'\n', status), 'Native settings not accepted')
    options = profile['options']
    temp = 'disabled:config'
    if phase == 'enabled' and (options['oil_temperature_fix'] or options['coolant_temperature_fix']):
        temp = 'registered:' + ('oil+coolant' if options['oil_temperature_fix'] and options['coolant_temperature_fix'] else 'oil' if options['oil_temperature_fix'] else 'coolant') + '-x10'
    device.require((snap['temperature_status'] or '').endswith(' ' + temp + '\n'), 'Temperature selection did not register')
    sport = 'disabled:config'
    if selection.needs_sports(profile) and phase != 'disabled':
        sport = {'preflight': 'ready:preflight:mutable-car-factory:sport-cached=false',
                 'self-write': 'ready:self-write:both-slots-verified:sport-cached=false',
                 'enabled': None}[phase]
        if sport is None:
            device.require(re.fullmatch(r'sport-v7 \d+ (registered:car-factory|view-created):configured\n', snap['sports_status'] or ''), 'Configured gauges did not register')
            return
    device.require((snap['sports_status'] or '').endswith(' ' + sport + '\n'), 'Native Sports phase did not pass')


LOCK = REMOTE + '/writer.lock'
UNIT = REMOTE + '/unit-id'
JOURNAL = REMOTE + '/transaction.json'
WRITER = REMOTE + '/writer-session.json'
PATHS = {'carrier': device.ACTIVE, 'ui': UI, 'options': OPTIONS, 'receipt': RECEIPT}


class RetryableError(RuntimeError):
    """No live files changed, or exact preimages were restored and recorded."""


def local(name):
    return STATE_ROOT / 'native' / name


def save_state(value):
    durable.write_bytes(STATE, json.dumps(value, indent=2).encode('ascii') + b'\n')


def load_state():
    try:
        journal = durable.load(local('transaction.json'))
    except ValueError:
        journal = None
    if journal:
        if journal['status'] == 'aborted':
            return journal['state_before']
        return state_for(journal)
    try:
        return json.loads(STATE.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return {}


def read_images(ftp):
    return {key: None if (data := device.fetch(ftp, path, True)) is None else data.hex()
            for key, path in PATHS.items()}


def validate_images(images):
    device.require(set(images) == set(PATHS), 'Invalid recovery file inventory')
    for value in images.values():
        device.require(value is None or isinstance(value, str) and len(value) <= 32 * 1024 * 1024,
                       'Invalid recovery file size')
        if value is not None:
            bytes.fromhex(value)
    device.require(images['carrier'] is not None, 'Recovery carrier missing')
    identify(bytes.fromhex(images['carrier']))
    device.require(recognized_ui(None if images['ui'] is None else bytes.fromhex(images['ui'])),
                   'Unrecognized recovery UI')


def validate_journal(journal):
    device.require(journal['schema'] == 1 and re.fullmatch('[0-9a-f]{32}', journal['id']), 'Invalid transaction identity')
    for key in ('owner', 'unit'):
        device.require(re.fullmatch('[0-9a-f]{32}', journal[key]), 'Invalid transaction owner/unit')
    device.require(journal['marker'] == '/tmp/golf-sports-boot-' + journal['id'], 'Invalid boot marker')
    device.require(journal['status'] in ('prepared', 'pending', 'accepted', 'aborted'), 'Invalid transaction status')
    validate_images(journal['before']); validate_images(journal['after'])
    validate_images(journal['recovery']['images'])
    return journal


def state_for(journal):
    state = {'phase': journal['phase'], 'pending': journal['status'] != 'accepted',
             'profile_id': profile_id(journal['profile']), 'transaction': journal['id']}
    state.update(journal.get('acceptance', {}))
    return state


def next_revision():
    """Ordering survives process restart and PC clock corrections."""
    newest = 0
    for name in ('transaction.json', 'recovery.json'):
        try:
            record = durable.load(local(name))
        except ValueError:
            continue
        if record:
            newest = max(newest, record.get('revision', 0))
    return newest + 1


def checkpoint(journal, **changes):
    journal.update(changes, revision=max(journal['revision'] + 1, next_revision()))
    validate_journal(journal)
    durable.save(local('transaction.json'), journal)


def owner_record():
    try:
        owner = durable.load(local('owner.json'))
    except ValueError:
        journal = durable.load(local('transaction.json'))
        if not journal:
            raise
        owner = {key: journal[key] for key in ('owner', 'unit', 'host')}
    if owner is None:
        previous_host = transport.ADDRESS
        try:
            old_session = json.loads((STATE_ROOT / 'session.json').read_text())
            if isinstance(old_session, dict):
                previous_host = old_session.get('host') or previous_host
        except (OSError, ValueError, TypeError):
            pass
        owner = {'owner': uuid.uuid4().hex, 'host': previous_host, 'unit': None}
        durable.save(local('owner.json'), owner)
    device.require(re.fullmatch('[0-9a-f]{32}', owner['owner']), 'Invalid local owner')
    # Address changes require an existing persistent unit token to match.
    return owner


def assert_owner(ftp, owner):
    device.require(device.fetch(ftp, LOCK, True) == owner['owner'].encode('ascii'),
                   'Unit belongs to another active installer; use the original state folder')


def sync(telnet):
    device.shell(telnet, '/ffs/sbin/sync')


def publish(ftp, telnet, target, data, token, owner=None, executable=False):
    """Never truncate a live file. The unique stage is disposable and owned."""
    device.require(re.fullmatch('[0-9a-f]{32}', token), 'Invalid stage owner')
    if owner is not None:
        assert_owner(ftp, owner)
    if data is None:
        if device.fetch(ftp, target, True) is not None:
            device.shell(telnet, '/proc/boot/rm -f ' + target)
            sync(telnet)
        return
    if device.fetch(ftp, target, True) == data:
        return
    stage = target + '.' + token + '.stage'
    if executable:
        # A fresh copy replaces only this transaction's disposable staging file.
        device.shell(telnet, '/proc/boot/cp -p ' + device.ACTIVE + ' ' + stage)
    ftp.storbinary('STOR ' + stage, io.BytesIO(data))
    device.require(device.fetch(ftp, stage) == data, 'Staged file readback failed: ' + target)
    if executable:
        device.metadata(telnet, stage)
    sync(telnet)
    if owner is not None:
        assert_owner(ftp, owner)
    device.shell(telnet, '/proc/boot/mv -f ' + stage + ' ' + target)
    sync(telnet)
    device.require(device.fetch(ftp, target) == data, 'Published file readback failed: ' + target)


def acquire(ftp, telnet, owner):
    remote_unit = device.fetch(ftp, UNIT, True)
    if owner['unit'] is not None:
        device.require(remote_unit == owner['unit'].encode(), 'Different unit or missing unit identity; refusing writes')
    else:
        device.require(owner['host'] == transport.ADDRESS, 'Unbound recovery must use its original unit address')
        if remote_unit is not None:
            device.require(re.fullmatch(b'[0-9a-f]{32}', remote_unit), 'Invalid unit identity')
    existing = device.fetch(ftp, LOCK, True)
    if existing is not None:
        assert_owner(ftp, owner)
        previous = device.fetch(ftp, WRITER, True)
        if previous is not None:
            try:
                lease = json.loads(previous)
                device.require(isinstance(lease, dict) and re.fullmatch('[0-9a-f]{32}', lease['owner'])
                               and type(lease['pid']) is int and lease['pid'] > 0
                               and re.fullmatch('/tmp/golf-sports-writer-[0-9a-f]{32}', lease['marker']),
                               'Invalid writer session record')
            except (ValueError, KeyError, TypeError):
                lease = durable.load(local('writer-session.json'))
            device.require(isinstance(lease, dict), 'Writer session recovery data missing')
            device.require(re.fullmatch('[0-9a-f]{32}', lease['owner']) and type(lease['pid']) is int and lease['pid'] > 0
                           and re.fullmatch('/tmp/golf-sports-writer-[0-9a-f]{32}', lease['marker']),
                           'Invalid writer session record')
            # A previous owner released the lock before this folder acquired it;
            # its old session record can remain until our publication completes.
            if lease['owner'] == owner['owner'] and device.fetch(ftp, lease['marker'], True) is not None:
                processes = device.shell(telnet, '/proc/boot/pidin ar')
                device.require(not re.search(r'(?m)^\s*' + str(lease['pid']) + r'\s', processes),
                               'Previous installer service session is still active; wait for it to end before recovery')
    else:
        device.shell(telnet, '/ffs/sbin/mkdir -p ' + REMOTE)
        token = uuid.uuid4().hex
        source = REMOTE + '/.lock-owner-' + token
        ftp.storbinary('STOR ' + source, io.BytesIO(owner['owner'].encode()))
        device.require(device.fetch(ftp, source) == owner['owner'].encode(), 'Lock owner readback failed')
        sync(telnet)
        # QNX ln normally replaces writable destinations! -i with EOF explicitly
        # refuses replacement. Concurrent link creation must never be forced.
        try:
            device.shell(telnet, '/proc/boot/ln -i ' + source + ' ' + LOCK + ' < /dev/null')
        except ValueError:
            assert_owner(ftp, owner)
        assert_owner(ftp, owner)
        sync(telnet)
    response = device.shell(telnet, 'echo GOLF_SHELL_PID:$$')
    pids = re.findall(r'(?m)^GOLF_SHELL_PID:(\d+)\s*$', response)
    device.require(len(pids) == 1 and int(pids[0]) > 0, 'Cannot identify the writer service session')
    token = uuid.uuid4().hex
    marker = '/tmp/golf-sports-writer-' + token
    ftp.storbinary('STOR ' + marker, io.BytesIO(owner['owner'].encode()))
    device.require(device.fetch(ftp, marker) == owner['owner'].encode(), 'Writer marker readback failed')
    lease = {'owner': owner['owner'], 'pid': int(pids[0]), 'marker': marker}
    durable.save(local('writer-session.json'), lease)
    publish(ftp, telnet, WRITER, durable.encode(lease), token, owner)
    if remote_unit is None:
        remote_unit = uuid.uuid4().hex.encode()
        publish(ftp, telnet, UNIT, remote_unit, uuid.uuid4().hex, owner)
    owner.update(unit=remote_unit.decode(), host=transport.ADDRESS)
    durable.save(local('owner.json'), owner)


def release(ftp, telnet, owner):
    assert_owner(ftp, owner)
    device.shell(telnet, '/proc/boot/rm -f ' + LOCK)
    sync(telnet)


def apply_images(ftp, telnet, images, token, owner):
    validate_images(images)
    # Receipt is retained until every target file is restored. The journal is
    # independent of the receipt, so a repeated rollback keeps the same target.
    for key in ('ui', 'options', 'carrier', 'receipt'):
        value = images[key]
        publish(ftp, telnet, PATHS[key], None if value is None else bytes.fromhex(value),
                token, owner, executable=key in ('carrier', 'ui'))
    device.require(read_images(ftp) == images, 'Transaction readback differs')


def cleanup_stages(ftp, telnet, journal, owner):
    """Remove only scratch files belonging to a validated recorded transaction."""
    validate_journal(journal)
    assert_owner(ftp, owner)
    for target in (*PATHS.values(), JOURNAL):
        stage = target + '.' + journal['id'] + '.stage'
        if device.fetch(ftp, stage, True) is not None:
            ftp.delete(stage)
    sync(telnet)


def receipt_images(ftp, receipt):
    if receipt.get('schema') == 1:
        validate_images(receipt['images'])
        return receipt
    # Import the released v1.0 receipt without relying on its redundant backup JAR.
    old = bytes.fromhex(receipt['carrier_hex'])
    device.require(receipt['backup'] == REMOTE + '/backup-' + device.sha(old)[:16] + '.jar', 'Invalid legacy backup identity')
    previous = receipt.get('previous_receipt_sha256')
    previous_data = None
    if previous is not None:
        device.require(re.fullmatch('[0-9a-f]{64}', previous), 'Invalid legacy receipt identity')
        previous_data = device.fetch(ftp, REMOTE + '/receipt-' + previous + '.json')
        device.require(device.sha(previous_data) == previous, 'Legacy receipt history changed')
    images = {'carrier': old.hex(), 'ui': receipt['ui_hex'], 'options': receipt['options_hex'],
              'receipt': None if previous_data is None else previous_data.hex()}
    validate_images(images)
    return {'schema': 1, 'images': images, 'health': None}


def legacy_local_receipt():
    """Only accept a unique independently hashed preimage from the old installer."""
    candidates = {}
    names = {'carrier': 'carrier.jar', 'ui': 'ui.jar', 'options': 'options.properties', 'receipt': 'previous-receipt.json'}
    for manifest_path in local('logs').glob('*/incoming-backup/manifest.json'):
        try:
            inventory = json.loads(manifest_path.read_text())
            images = {}
            for key, filename in names.items():
                expected = inventory[filename]
                data = None if expected is None else (manifest_path.parent / filename).read_bytes()
                device.require(data is None or device.sha(data) == expected, 'Legacy backup damaged')
                images[key] = None if data is None else data.hex()
            validate_images(images)
            candidates[device.sha(durable.encode(images))] = {'schema': 1, 'images': images, 'health': None}
        except (OSError, ValueError, KeyError, TypeError):
            continue
    device.require(len(candidates) == 1, 'No unique validated recovery backup; keep all state and backup files')
    return next(iter(candidates.values()))


def get_recovery(ftp, journal):
    saved = durable.load(local('recovery.json'))
    if saved is not None and (journal is None or saved.get('revision', 0) > journal['revision']):
        validate_images(saved['images'])
        return saved
    if journal and journal['status'] != 'aborted':
        return journal['recovery']
    try:
        data = device.fetch(ftp, RECEIPT, True)
        if data is not None:
            return receipt_images(ftp, json.loads(data))
    except (ValueError, KeyError, TypeError):
        pass
    if saved is not None:
        validate_images(saved['images'])
        return saved
    return legacy_local_receipt()


def profile_from_options(data):
    rows = [line.split('=', 1) for line in data.decode('ascii').splitlines()]
    device.require(len(rows) == 18 and all(len(row) == 2 for row in rows), 'Invalid restored options')
    values = dict(rows)
    options = dict(selection.CATALOG['defaults'])
    for native, key in [('oil', 'oil_temperature_fix'), ('coolant', 'coolant_temperature_fix'),
                        ('torque', 'enable_torque_gauge'), *zip(
                            ('gauge_boost', 'gauge_gmeter', 'gauge_coolant', 'gauge_power', 'gauge_oil'), selection.GAUGE_KEYS[:-1])]:
        device.require(values[native] in ('true', 'false'), 'Invalid restored flag')
        options[key] = values[native] == 'true'
    for key, native in [('power_source', 'power_source'), ('needle_smoothing', 'smoothing'), ('power_unit', 'power_unit')]:
        options[key] = values[native]
    for key in selection.RANGE_KEYS:
        options[key] = None if values[key] == 'auto' else int(values[key])
    profile = selection.make_profile(options)
    device.require(properties(profile, values['mode']) == data, 'Restored options differ from strict schema')
    return profile, values['mode']


def verify_restored(ftp, row, snap, recovery):
    images = recovery['images']
    device.require(read_images(ftp) == images, 'Restored files changed after reboot')
    if snap['configured']:
        selected, phase = profile_from_options(bytes.fromhex(images['options']))
        check_health(ftp, row, snap, selected, phase)
    else:
        # Older carriers do not emit configurable-v4 status. Compare available
        # baseline component states, never treating an error status as health.
        for key in ('temperature_status', 'sports_status'):
            expected = (recovery.get('health') or {}).get(key)
            actual = snap.get(key)
            if actual is not None:
                device.require(' failed:' not in actual, 'Restored component failed: ' + key)
            if expected is not None:
                expected_tail = expected.split(' ', 2)[-1]
                device.require(actual is not None and actual.split(' ', 2)[-1] == expected_tail,
                               'Restored component status differs: ' + key)


def persist_remote(ftp, telnet, journal, owner):
    publish(ftp, telnet, JOURNAL, durable.envelope(journal), journal['id'], owner)


def prepare(action, profile, phase, before, after, state, snap, recovery, owner):
    token = uuid.uuid4().hex
    journal = {'schema': 1, 'revision': next_revision(), 'id': token, **owner,
               'action': action, 'profile': profile, 'phase': phase, 'status': 'prepared',
               'before': before, 'after': after, 'state_before': state, 'snapshot_before': snap,
               'recovery': recovery, 'marker': '/tmp/golf-sports-boot-' + token}
    validate_journal(journal)
    durable.save(local('transaction.json'), journal)
    return journal


def run(action, profile):
    with durable.lock(local('runtime.lock')):
        return _run(action, profile)


def _run(action, profile):
    verify()
    profile = selection.validate_profile(profile)
    if action in ('install-disabled', 'preflight', 'self-write', 'enable', 'accept-self-write', 'accept-enable'):
        compatibility.require_exportable(profile)
    if action in ('accept-self-write', 'accept-enable'):
        expected = 'preflight' if action == 'accept-self-write' else 'self-write'
        state = load_state()
        device.require(state.get('phase') == expected, 'Expected native phase missing')
        _run('accept', profile)
        return _run('self-write' if action == 'accept-self-write' else 'enable', profile)
    report = {'action': action, 'events': []}
    folder = local('logs') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    def record(step, **details):
        entry = {'step': step, **details}
        report['events'].append(entry)
        try:
            durable.write_bytes(folder / 'report.json', durable.encode(report))
        except OSError:
            pass
        try:
            print(json.dumps(entry), flush=True)
        except OSError:
            pass
    ftp = telnet = owner = transaction = None
    locked = rebooting = False
    try:
        try:
            journal = durable.load(local('transaction.json'))
        except ValueError:
            journal = None  # Validated remote mirror may reconstruct it below.
        ftp = device.ftp_connect(); telnet = device.Telnet()
        recovery_action = action == 'rollback'
        active, row, snap = snapshot(ftp, telnet, recovery=recovery_action)
        record('snapshot', **snap)
        before = read_images(ftp)
        validate_images(before)
        if action in ('install-disabled', 'inspect'):
            candidate, row = compose(active)
            device.require(recognized_ui(None if before['ui'] is None else bytes.fromhex(before['ui'])), 'Foreign configurable UI')
            if snap['configured']:
                old_profile, old_phase = profile_from_options(bytes.fromhex(before['options']))
                check_health(ftp, row, snap, old_profile, old_phase)
                if action == 'install-disabled':
                    device.require(old_phase == 'enabled', 'Existing configurable installation is incomplete; recover its original session')
        if action == 'inspect':
            return {'status': 'inspected', 'snapshot': snap}
        owner = owner_record()
        remote_data = device.fetch(ftp, JOURNAL, True)
        remote_journal = None
        if remote_data is not None:
            try:
                remote_journal = validate_journal(durable.unpack(remote_data))
            except (ValueError, KeyError, TypeError):
                device.require(journal is not None, 'No intact local or remote transaction record')
        if remote_journal and remote_journal['owner'] == owner['owner']:
            if journal is None or remote_journal['revision'] > journal['revision']:
                journal = remote_journal
                durable.save(local('transaction.json'), journal)
        elif remote_journal and journal and action != 'install-disabled':
            raise ValueError('Another installation changed this unit; use its current state folder')
        elif remote_journal and journal is None and action == 'rollback':
            saved_attempt = durable.load(local('recovery.json'))
            if saved_attempt is not None and saved_attempt['images'] == before:
                # A new folder was interrupted before making any managed-file
                # changes. It cannot consume the previous installer's receipt.
                if device.fetch(ftp, LOCK, True) == owner['owner'].encode():
                    release(ftp, telnet, owner)
                return {'status': 'unchanged', 'phase': 'rollback'}
            raise ValueError('Use the state folder that created the current installation')
        if journal:
            validate_journal(journal)
            device.require(journal['owner'] == owner['owner'], 'Recovery owner differs')
        if action == 'install-disabled' and journal:
            device.require(journal['status'] in ('accepted', 'aborted'), 'Interrupted operation requires --rollback')
            device.require(journal['phase'] == 'rollback' or journal['status'] == 'aborted' or
                           journal['phase'] == 'enabled' and journal.get('acceptance', {}).get('observed_seconds', 0) >= 360,
                           'Finish or roll back the existing installation before starting another')
        if action == 'install-disabled':
            # Save this attempt's target before even acquiring remote metadata.
            # A crash while taking the lock must not select an older receipt.
            recovery = {'schema': 1, 'images': before, 'health': snap,
                        'revision': next_revision(), 'owner': owner['owner'], 'host': transport.ADDRESS}
            durable.save(local('recovery.json'), recovery)
        acquire(ftp, telnet, owner); locked = True
        # Re-read after the lock, closing the preflight/acquisition race.
        device.require(read_images(ftp) == before, 'Unit changed while acquiring the installation lock')
        if journal and journal['owner'] == owner['owner']:
            cleanup_stages(ftp, telnet, journal, owner)
        state = load_state()
        if action in ('accept', 'observe-disabled', 'observe-enabled'):
            device.require(journal is not None and journal['status'] in ('pending', 'accepted'), 'No pending boot transaction')
            device.require(device.fetch(ftp, journal['marker'], True) is None, 'Fresh unit reboot not established')
            device.require(before == journal['after'], 'Expected transaction files changed')
            phase = journal['phase']
            if phase == 'rollback':
                verify_restored(ftp, row, snap, journal['recovery'])
            else:
                device.require(profile_id(profile) == profile_id(journal['profile']), 'Selected configuration changed')
                check_health(ftp, row, snap, profile, phase)
            acceptance = {'accepted_snapshot': snap}
            if action.startswith('observe-'):
                expected = 'disabled' if action == 'observe-disabled' else 'enabled'
                device.require(phase == expected, 'Wrong observation phase')
                identity = (snap['hmi_pid'], snap['config_status'])
                began = time.monotonic()
                while time.monotonic() - began < 360:
                    time.sleep(12)
                    _, fresh_row, fresh = snapshot(ftp, telnet)
                    check_health(ftp, fresh_row, fresh, profile, phase)
                    device.require(read_images(ftp) == journal['after'], 'Files changed during observation')
                    device.require((fresh['hmi_pid'], fresh['config_status']) == identity, 'HMI restarted during observation')
                    record('observing', stable_seconds=int(time.monotonic() - began))
                acceptance['observed_seconds'] = time.monotonic() - began
            else:
                acceptance.update({k: v for k, v in journal.get('acceptance', {}).items() if k == 'observed_seconds'})
            checkpoint(journal, status='accepted', acceptance=acceptance)
            persist_remote(ftp, telnet, journal, owner)
            save_state(state_for(journal))
            if phase == 'rollback' or action == 'observe-enabled':
                release(ftp, telnet, owner); locked = False
            record('native_phase_accepted', phase=phase)
            return {'status': 'accepted', 'phase': phase}
        if action == 'rollback':
            if journal and journal['action'] == 'rollback':
                if journal['status'] == 'accepted':
                    device.require(before == journal['after'], 'Accepted rollback files changed')
                    release(ftp, telnet, owner); locked = False
                    return {'status': 'accepted', 'phase': 'rollback'}
                transaction = journal  # Never consume a second receipt on retry.
            else:
                if journal is None and before['ui'] is None and before['options'] is None and before['receipt'] is None and row['name'] == 'stock' and not snap['configured'] and not local('recovery.json').exists() and not list(local('logs').glob('*/incoming-backup/manifest.json')):
                    release(ftp, telnet, owner); locked = False
                    return {'status': 'unchanged', 'phase': 'rollback'}
                recovery = get_recovery(ftp, journal)
                validate_images(recovery['images'])
                # Unknown carriers still stop; a running HMI is not required.
                old_row, _ = identify(bytes.fromhex(recovery['images']['carrier']))
                device.require(row['configured_sha256'] == old_row['configured_sha256'], 'Backup belongs to a different carrier profile')
                transaction = prepare(action, profile, 'rollback', before, recovery['images'], state, snap, recovery, owner)
        elif action == 'install-disabled':
            after = {'carrier': candidate.hex(), 'ui': (HERE / row['ui']).read_bytes().hex(),
                     'options': properties(profile, 'disabled').hex(), 'receipt': durable.encode(recovery).hex()}
            transaction = prepare(action, profile, 'disabled', before, after, state, snap, recovery, owner)
        else:
            required = {'preflight': 'disabled', 'self-write': 'preflight',
                        'enable': 'self-write' if selection.needs_sports(profile) else 'disabled'}
            accepted_state = state_for(journal) if journal is not None else {}
            if journal and journal['status'] == 'aborted':
                device.require(before == journal['before'], 'Restored phase files changed')
                accepted_state = journal['state_before']
            device.require(action in required and accepted_state.get('pending') is False
                           and accepted_state.get('phase') == required[action], 'Required native phase acceptance missing')
            device.require(accepted_state['profile_id'] == profile_id(profile), 'Selected configuration changed')
            check_health(ftp, row, snap, profile, accepted_state['phase'])
            accepted = accepted_state['accepted_snapshot']
            device.require((snap['hmi_pid'], snap['config_status']) == (accepted['hmi_pid'], accepted['config_status']),
                           'Accepted boot identity changed')
            if accepted_state['phase'] == 'disabled':
                device.require(accepted_state.get('observed_seconds', 0) >= 360, 'Six-minute disabled acceptance missing')
            phase = {'preflight': 'preflight', 'self-write': 'self-write', 'enable': 'enabled'}[action]
            after = {**before, 'options': properties(profile, phase).hex()}
            transaction = prepare(action, profile, phase, before, after, state, snap, journal['recovery'], owner)
        persist_remote(ftp, telnet, transaction, owner)
        # /tmp is volatile on the supported QNX image. An absent marker is only
        # accepted for a durably recorded pending reboot, never a prepared write.
        ftp.storbinary('STOR ' + transaction['marker'], io.BytesIO(transaction['id'].encode()))
        device.require(device.fetch(ftp, transaction['marker']) == transaction['id'].encode(), 'Boot marker readback failed')
        apply_images(ftp, telnet, transaction['after'], transaction['id'], owner)
        checkpoint(transaction, status='pending')
        persist_remote(ftp, telnet, transaction, owner)
        save_state(state_for(transaction))
        rebooting = True
        device.normal_reboot(telnet, record)
        return {'status': 'pending', 'phase': transaction['phase']}
    except (Exception, KeyboardInterrupt) as error:
        if isinstance(error, device.NativeRebootRejected):
            rebooting = False
        # Record must never prevent restoring a known preimage.
        record('failed', error=repr(error), reboot_requested=rebooting)
        if transaction is not None and transaction['action'] != 'rollback' and not rebooting:
            try:
                cleanup_stages(ftp, telnet, transaction, owner)
                apply_images(ftp, telnet, transaction['before'], transaction['id'], owner)
                checkpoint(transaction, status='aborted')
                persist_remote(ftp, telnet, transaction, owner)
                save_state(transaction['state_before'])
                record('incoming_configuration_restored')
                if transaction['action'] == 'install-disabled':
                    release(ftp, telnet, owner); locked = False
                raise RetryableError('Previous files restored. The same step may be retried: ' + str(error)) from error
            except RetryableError:
                raise
            except (Exception, KeyboardInterrupt) as recovery_error:
                record('recovery_required', error=repr(recovery_error))
                raise RuntimeError('Recovery incomplete. Keep this folder and run --rollback when service access returns. ' + str(error)) from recovery_error
        if transaction is None and action == 'install-disabled':
            pending = durable.load(local('transaction.json'))
            if pending and pending['status'] not in ('accepted', 'aborted'):
                raise RuntimeError('An incomplete transaction is recorded. Keep this folder and use --rollback.') from error
            if locked:
                try:
                    release(ftp, telnet, owner)
                except Exception:
                    pass
            raise RetryableError('No live installation files were written. Correct the problem and retry: ' + str(error)) from error
        raise
    finally:
        if telnet is not None:
            try: telnet.close()
            except Exception: pass
        if ftp is not None:
            try: ftp.quit()
            except Exception: ftp.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['verify', 'inspect', 'install-disabled', 'observe-disabled', 'preflight', 'self-write', 'enable', 'accept-self-write', 'accept-enable', 'accept', 'observe-enabled', 'rollback'])
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.action == 'verify': verify()
    elif not args.live: parser.error('--live required')
    elif args.profile is None: parser.error('--profile is required')
    else: run(args.action, selection.load_profile(args.profile))


