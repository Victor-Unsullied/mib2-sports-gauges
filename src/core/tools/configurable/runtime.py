"""Staged, hash-gated configurable Sports runtime. No vehicle access without --live."""
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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
import selection
import compatibility
import device

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


def snapshot(ftp, telnet):
    for path, digest in json.loads((HERE / 'protected-files.json').read_text()).items():
        device.require(device.sha(device.fetch(ftp, path)) == digest, 'Protected startup/configuration file changed: ' + path)
    active = device.fetch(ftp, device.ACTIVE)
    row, configured = identify(active)
    processes = device.shell(telnet, '/proc/boot/pidin ar')
    jvms = [line for line in processes.splitlines() if re.match(r'^\s*\d+\s+\S*j9\s', line)]
    device.require(len(jvms) == 1 and 'de.vw.mib.MIBMain' in jvms[0], 'Expected one native HMI JVM')
    device.require('-Dgolf.' not in jvms[0] and '-Xbootclasspath/p:' not in jvms[0]
                   and 'watchdog.sh' not in processes, 'Old trial overlay/watchdog present')
    device.metadata(telnet, device.ACTIVE)
    def text(path):
        data = device.fetch(ftp, path, True)
        return None if data is None else data.decode('ascii')
    return active, row, {'active_sha256': device.sha(active), 'configured': configured,
        'hmi_pid': int(jvms[0].split()[0]), 'config_status': text(CONFIG_STATUS),
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


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')


def restore(ftp, telnet, receipt):
    old = bytes.fromhex(receipt['carrier_hex'])
    identify(old)
    device.require(receipt['backup'] == REMOTE + '/backup-' + device.sha(old)[:16] + '.jar', 'Unknown recovery backup path')
    device.require(device.fetch(ftp, receipt['backup']) == old, 'Exact recovery carrier missing/corrupt')
    staged = device.fetch(ftp, STAGE, True)
    if staged is not None: identify(staged)
    previous_receipt = receipt.get('previous_receipt_sha256')
    receipt_data = None
    if previous_receipt is not None:
        device.require(re.fullmatch('[0-9a-f]{64}', previous_receipt), 'Unknown receipt backup identity')
        receipt_data = device.fetch(ftp, REMOTE + '/receipt-' + previous_receipt + '.json')
        device.require(device.sha(receipt_data) == previous_receipt, 'Previous recovery receipt changed')
    device.shell(telnet, '/proc/boot/cp -p ' + receipt['backup'] + ' ' + STAGE)
    device.require(device.fetch(ftp, STAGE) == old, 'Recovery stage differs')
    device.metadata(telnet, STAGE)
    for target, key in ((UI, 'ui_hex'), (OPTIONS, 'options_hex')):
        previous = receipt[key]
        if previous is None:
            if device.fetch(ftp, target, True) is not None:
                ftp.delete(target)
        else:
            data = bytes.fromhex(previous)
            ftp.storbinary('STOR ' + target, io.BytesIO(data))
            device.require(device.fetch(ftp, target) == data, 'Recovery file differs')
    device.shell(telnet, '/proc/boot/mv -f ' + STAGE + ' ' + device.ACTIVE)
    device.require(device.fetch(ftp, device.ACTIVE) == old, 'Carrier recovery failed')
    device.metadata(telnet, device.ACTIVE)
    if previous_receipt is None:
        if device.fetch(ftp, RECEIPT, True) is not None:
            ftp.delete(RECEIPT)
    else:
        ftp.storbinary('STOR ' + RECEIPT, io.BytesIO(receipt_data))
        device.require(device.fetch(ftp, RECEIPT) == receipt_data, 'Previous recovery receipt readback failed')
    device.shell(telnet, '/ffs/sbin/sync')


def run(action, profile):
    verify()
    profile = selection.validate_profile(profile)
    if action in ('install-disabled', 'preflight', 'self-write', 'enable', 'accept-self-write', 'accept-enable'):
        compatibility.require_installable(profile)
    if action in ('accept-self-write', 'accept-enable'):
        # Acceptance checks the fresh boot before any next-phase write. Each
        # phase remains its own transaction and can be recovered independently.
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
        expected = 'preflight' if action == 'accept-self-write' else 'self-write'
        device.require(state.get('phase') == expected and state.get('pending') is True,
                       'Expected phase is not awaiting fresh-boot acceptance')
        run('accept', profile)
        run('self-write' if action == 'accept-self-write' else 'enable', profile)
        return
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    folder = STATE_ROOT / 'native/logs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    report = {'action': action, 'profile_id': profile_id(profile), 'events': []}
    def record(step, **details):
        report['events'].append({'step': step, **details})
        (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'step': step, **details}), flush=True)
    ftp = telnet = None
    changed = rebooting = False
    receipt = None
    incoming_options = None
    try:
        ftp = device.ftp_connect(); telnet = device.Telnet()
        active, row, snap = snapshot(ftp, telnet)
        incoming_options = device.fetch(ftp, OPTIONS, True)
        record('snapshot', **snap)
        if action == 'inspect':
            return
        if action == 'rollback':
            saved = device.fetch(ftp, RECEIPT)
            target_receipt = json.loads(saved.decode('utf-8'))
            expected_backup = REMOTE + '/backup-' + device.sha(bytes.fromhex(target_receipt['carrier_hex']))[:16] + '.jar'
            device.require(target_receipt['backup'] == expected_backup and snap['configured'], 'Unrecognized recovery receipt/state')
            # Preserve the accepted configuration if the native reboot is rejected.
            backup = REMOTE + '/backup-' + device.sha(active)[:16] + '.jar'
            existing = device.fetch(ftp, backup, True)
            device.require(existing in (None, active), 'Foreign recovery carrier')
            if existing is None: device.shell(telnet, '/proc/boot/cp -p ' + device.ACTIVE + ' ' + backup)
            device.require(device.fetch(ftp, backup) == active, 'Rollback fallback carrier differs')
            receipt_backup = REMOTE + '/receipt-' + device.sha(saved) + '.json'
            previous = device.fetch(ftp, receipt_backup, True)
            device.require(previous in (None, saved), 'Foreign receipt fallback')
            if previous is None: ftp.storbinary('STOR ' + receipt_backup, io.BytesIO(saved))
            device.require(device.fetch(ftp, receipt_backup) == saved, 'Rollback fallback receipt differs')
            current_ui = device.fetch(ftp, UI, True)
            receipt = {'backup': backup, 'carrier_hex': active.hex(),
                       'ui_hex': None if current_ui is None else current_ui.hex(),
                       'options_hex': None if incoming_options is None else incoming_options.hex(),
                       'previous_receipt_sha256': device.sha(saved)}
            changed = True
            restore(ftp, telnet, target_receipt)
            save_state({'phase': 'rollback', 'pending': True, 'expected_sha256': device.sha(bytes.fromhex(target_receipt['carrier_hex'])),
                        'previous_config_status': snap['config_status']})
            rebooting = True; device.normal_reboot(telnet, record)
            return
        if action == 'accept' and state.get('phase') == 'rollback':
            device.require(state.get('pending') and snap['active_sha256'] == state['expected_sha256'], 'Recovery boot not pending/matched')
            device.require(snap['config_status'] != state['previous_config_status'], 'Fresh rollback boot not established')
            state.update(pending=False); save_state(state); record('rollback_boot_accepted'); return
        if action in ('accept', 'observe-disabled', 'observe-enabled'):
            device.require(state.get('profile_id') == profile_id(profile), 'No matching selected installation session')
            phase = state['phase']
            check_health(ftp, row, snap, profile, phase)
            if state.get('pending'):
                device.require(snap['config_status'] != state['previous_config_status'], 'Fresh configuration boot missing')
            if action.startswith('observe-'):
                expected = 'disabled' if action == 'observe-disabled' else 'enabled'
                device.require(phase == expected, 'Wrong observation phase')
                identity = (snap['hmi_pid'], snap['config_status'])
                began = time.monotonic()
                while time.monotonic() - began < 360:
                    time.sleep(12)
                    _, fresh_row, fresh = snapshot(ftp, telnet)
                    check_health(ftp, fresh_row, fresh, profile, phase)
                    device.require((fresh['hmi_pid'], fresh['config_status']) == identity, 'HMI/configuration restarted during observation')
                    record('observing', stable_seconds=int(time.monotonic() - began))
                state['observed_seconds'] = time.monotonic() - began
            state.update(pending=False, accepted_snapshot=snap)
            save_state(state); record('native_phase_accepted', phase=phase); return
        if action == 'install-disabled':
            device.require(not state.get('pending'), 'A previous reboot still needs acceptance')
            candidate, row = compose(active)
            current_ui = device.fetch(ftp, UI, True)
            current_options = device.fetch(ftp, OPTIONS, True)
            device.require(recognized_ui(current_ui), 'Foreign configurable UI')
            previous_receipt = device.fetch(ftp, RECEIPT, True)
            # Keep an independent local copy before touching the unit. A failed
            # disk write aborts the step before any remote mutation.
            local_backup = folder / 'incoming-backup'
            local_backup.mkdir()
            backup_files = {'carrier.jar': active, 'ui.jar': current_ui,
                            'options.properties': current_options,
                            'previous-receipt.json': previous_receipt}
            inventory = {}
            for name, data in backup_files.items():
                inventory[name] = None if data is None else device.sha(data)
                if data is not None:
                    (local_backup / name).write_bytes(data)
                    device.require((local_backup / name).read_bytes() == data, 'Local backup readback failed')
            (local_backup / 'manifest.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
            backup = REMOTE + '/backup-' + device.sha(active)[:16] + '.jar'
            device.shell(telnet, '/ffs/sbin/mkdir -p ' + REMOTE)
            existing = device.fetch(ftp, backup, True)
            device.require(existing in (None, active), 'Foreign recovery carrier')
            if existing is None: device.shell(telnet, '/proc/boot/cp -p ' + device.ACTIVE + ' ' + backup)
            device.require(device.fetch(ftp, backup) == active, 'Recovery backup readback failed')
            previous_receipt = device.fetch(ftp, RECEIPT, True)
            if previous_receipt is not None:
                receipt_backup = REMOTE + '/receipt-' + device.sha(previous_receipt) + '.json'
                saved = device.fetch(ftp, receipt_backup, True)
                device.require(saved in (None, previous_receipt), 'Foreign receipt backup')
                if saved is None:
                    ftp.storbinary('STOR ' + receipt_backup, io.BytesIO(previous_receipt))
                device.require(device.fetch(ftp, receipt_backup) == previous_receipt, 'Receipt backup differs')
            receipt = {'backup': backup, 'carrier_hex': active.hex(),
                       'ui_hex': None if current_ui is None else current_ui.hex(),
                       'options_hex': None if current_options is None else current_options.hex(),
                       'previous_receipt_sha256': None if previous_receipt is None else device.sha(previous_receipt)}
            stage = device.fetch(ftp, STAGE, True)
            device.require(stage is None or device.sha(stage) in (device.sha(active), device.sha(candidate)), 'Foreign carrier staging file')
            if stage is None: device.shell(telnet, '/proc/boot/cp -p ' + device.ACTIVE + ' ' + STAGE)
            ftp.storbinary('STOR ' + STAGE, io.BytesIO(candidate))
            device.require(device.fetch(ftp, STAGE) == candidate, 'Carrier stage readback failed'); device.metadata(telnet, STAGE)
            ui_data = (HERE / row['ui']).read_bytes()
            staged_ui = device.fetch(ftp, UI_STAGE, True)
            device.require(recognized_ui(staged_ui), 'Foreign UI stage')
            if staged_ui is None:
                device.shell(telnet, '/proc/boot/cp -p ' + device.ACTIVE + ' ' + UI_STAGE)
            ftp.storbinary('STOR ' + UI_STAGE, io.BytesIO(ui_data))
            device.require(device.fetch(ftp, UI_STAGE) == ui_data, 'UI stage readback failed')
            device.metadata(telnet, UI_STAGE)
            device.require(device.fetch(ftp, device.ACTIVE) == active and device.fetch(ftp, UI, True) == current_ui
                           and device.fetch(ftp, OPTIONS, True) == current_options, 'Incoming configuration changed while staging')
            changed = True
            ftp.storbinary('STOR ' + RECEIPT, io.BytesIO(json.dumps(receipt).encode()))
            device.require(json.loads(device.fetch(ftp, RECEIPT)) == receipt, 'Recovery receipt readback failed')
            device.shell(telnet, '/proc/boot/mv -f ' + UI_STAGE + ' ' + UI)
            phase = 'disabled'
        else:
            required = {'preflight': 'disabled', 'self-write': 'preflight',
                        'enable': 'self-write' if selection.needs_sports(profile) else 'disabled'}
            device.require(action in required and state.get('phase') == required[action] and state.get('pending') is False,
                           'Required native phase acceptance missing')
            device.require(state.get('profile_id') == profile_id(profile), 'Selected configuration changed between stages')
            check_health(ftp, row, snap, profile, state['phase'])
            device.require(snap['hmi_pid'] == state['accepted_snapshot']['hmi_pid'] and
                           snap['config_status'] == state['accepted_snapshot']['config_status'], 'Accepted boot identity changed')
            if state['phase'] == 'disabled':
                device.require(state.get('observed_seconds', 0) >= 360, 'Six-minute disabled acceptance missing')
            phase = {'preflight': 'preflight', 'self-write': 'self-write', 'enable': 'enabled'}[action]
            changed = True
        ftp.storbinary('STOR ' + OPTIONS, io.BytesIO(properties(profile, phase)))
        device.require(device.fetch(ftp, OPTIONS) == properties(profile, phase), 'Selected options readback failed')
        device.require(device.sha(device.fetch(ftp, UI)) == manifest()['ui_sha256'][row['ui']], 'UI readback failed')
        if action == 'install-disabled':
            device.shell(telnet, '/proc/boot/mv -f ' + STAGE + ' ' + device.ACTIVE)
        device.require(device.sha(device.fetch(ftp, device.ACTIVE)) == row['configured_sha256'], 'Active carrier differs')
        device.metadata(telnet, device.ACTIVE); device.shell(telnet, '/ffs/sbin/sync')
        save_state({'phase': phase, 'pending': True, 'profile_id': profile_id(profile),
                    'previous_config_status': snap['config_status'], 'log': str(folder)})
        rebooting = True; device.normal_reboot(telnet, record)
    except Exception as error:
        if isinstance(error, device.NativeRebootRejected): rebooting = False
        record('failed', error=repr(error), reboot_requested=rebooting)
        if changed and not rebooting and receipt is not None:
            restore(ftp, telnet, receipt)
            save_state(state)
            record('incoming_configuration_restored')
        elif changed and not rebooting:
            if incoming_options is None:
                if device.fetch(ftp, OPTIONS, True) is not None: ftp.delete(OPTIONS)
            else:
                ftp.storbinary('STOR ' + OPTIONS, io.BytesIO(incoming_options))
                device.require(device.fetch(ftp, OPTIONS) == incoming_options, 'Previous phase settings were not restored')
            device.shell(telnet, '/ffs/sbin/sync')
            save_state(state)
            record('accepted_phase_settings_restored')
        raise
    finally:
        if telnet is not None: telnet.close()
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
