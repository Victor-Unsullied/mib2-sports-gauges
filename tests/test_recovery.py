"""Fault-injected device filesystem. No sockets, audio, or private firmware needed."""
import contextlib
import ftplib
import io
import json
from pathlib import Path
import shlex
import socket
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import backend, config, wizard
r = backend.runtime


class CutPower(BaseException):
    """Model process death, bypassing cleanup in the runtime."""


def selected(**changes):
    return backend.profile(config.validate({'language':'en', 'train':config.SUPPORTED[0], 'mu':config.SUPPORTED[1],
        'options': {**config.DEFAULTS, 'oil_temperature_fix':True, 'enable_torque_gauge':True, **changes}}), 'en', True)


class Unit:
    def __init__(self):
        self.stock, self.candidate, self.ui = b'known-stock-fixture', b'known-configured-fixture', b'known-ui-fixture'
        self.files = {r.device.ACTIVE:self.stock, '/protected':b'protected-fixture'}
        self.pid, self.clock, self.running = 100, 0, True
        self.events, self.hook = [], None
        self.shell_count, self.live_shells = 200, set()
        self.reboot_fault, self.offline = False, False
        self.build = {'ui_sha256':{'sport-ui-factory.jar':r.device.sha(self.ui)},
                      'profiles':[{'name':'stock','incoming_sha256':r.device.sha(self.stock),
                                   'configured_sha256':r.device.sha(self.candidate),'ui':'sport-ui-factory.jar'}]}

    def event(self, kind, path):
        self.events.append((kind, path))
        if self.hook:
            self.hook(kind, path)

    def fetch(self, ftp, path, optional=False):
        if self.offline:
            raise ConnectionResetError('connection unavailable')
        if path not in self.files:
            if optional: return None
            raise ftplib.error_perm('550 No such file')
        return self.files[path]

    def connect(self):
        unit = self
        if self.offline: raise ConnectionRefusedError('connection unavailable')
        class FTP:
            def storbinary(self, command, stream):
                if unit.offline: raise ConnectionResetError('connection unavailable')
                path = command[5:]
                unit.files[path] = stream.read()
                unit.event('store', path)
            def delete(self, path):
                if unit.offline: raise ConnectionResetError('connection unavailable')
                del unit.files[path]
                unit.event('delete', path)
            def quit(self): pass
            def close(self): pass
        return FTP()

    def shell(self, telnet, command, **kwargs):
        if self.offline: raise ConnectionResetError('connection unavailable')
        parts = shlex.split(command)
        if parts[0].endswith('/pidin'):
            return (f'{self.pid} j9 de.vw.mib.MIBMain\n' if self.running else '') + ''.join(f'{pid} ksh\n' for pid in self.live_shells)
        if command == 'echo GOLF_SHELL_PID:$$':
            return f'GOLF_SHELL_PID:{telnet.pid}\n'
        if parts[0].endswith('/cp'):
            self.files[parts[-1]] = self.files[parts[-2]]
            self.event('copy', parts[-1])
        elif parts[0].endswith('/mv'):
            self.files[parts[-1]] = self.files.pop(parts[-2])
            self.event('rename', parts[-1])
        elif parts[0].endswith('/ln'):
            source, dest = parts[2:4]
            if dest in self.files:
                # Interactive ln with stdin at EOF must leave the winner intact.
                raise ValueError('link destination exists')
            self.files[dest] = self.files[source]
            self.event('link', dest)
        elif parts[0].endswith('/sync'):
            self.event('sync', '')
        elif parts[0].endswith('/rm'):
            self.files.pop(parts[-1],None)
            self.event('delete',parts[-1])
        elif parts[0].endswith('/mkdir'):
            self.event('mkdir', parts[-1])
        else:
            raise AssertionError('Unexpected shell command: ' + command)
        return ''

    def boot(self, telnet=None, record=lambda *a, **k:None):
        if self.reboot_fault: raise r.device.NativeRebootRejected('reboot rejected')
        self.pid += 1; self.running = True
        for path in list(self.files):
            if path.startswith('/tmp/'):
                del self.files[path]
        if self.files[r.device.ACTIVE] == self.candidate:
            try:
                p, phase = r.profile_from_options(self.files[r.OPTIONS])
            except Exception:
                self.files[r.CONFIG_STATUS] = f'sportconfig-v4 {self.pid} invalid:invalid\n'.encode()
                return
            self.files[r.CONFIG_STATUS] = f'sportconfig-v4 {self.pid} {phase}:{r.profile_id(p)}\n'.encode()
            o = p['options']; temp = 'disabled:config'
            if phase == 'enabled' and (o['oil_temperature_fix'] or o['coolant_temperature_fix']):
                suffix = 'oil+coolant' if o['oil_temperature_fix'] and o['coolant_temperature_fix'] else 'oil' if o['oil_temperature_fix'] else 'coolant'
                temp = 'registered:' + suffix + '-x10'
            sport = 'disabled:config'
            if r.selection.needs_sports(p) and phase != 'disabled':
                sport = {'preflight':'ready:preflight:mutable-car-factory:sport-cached=false',
                         'self-write':'ready:self-write:both-slots-verified:sport-cached=false',
                         'enabled':'registered:car-factory:configured'}[phase]
            self.files[r.TEMP_STATUS] = f'temperature-hook-v3 {self.pid} {temp}\n'.encode()
            self.files[r.SPORT_STATUS] = f'sport-v7 {self.pid} {sport}\n'.encode()
        self.event('reboot', '')

    @contextlib.contextmanager
    def use(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.ExitStack() as stack:
            here = Path(temp); state = here/'state'
            (here/'sport-ui-factory.jar').write_bytes(self.ui)
            (here/'protected-files.json').write_text(json.dumps({'/protected':r.device.sha(self.files['/protected'])}))
            def no_network(*a, **k): raise AssertionError('Real device access prohibited')
            for name in ('create_connection',): stack.enter_context(patch.object(socket,name,no_network))
            stack.enter_context(patch.object(socket.socket,'connect',no_network))
            stack.enter_context(patch.object(socket.socket,'connect_ex',no_network))
            for name, value in {'HERE':here,'STATE_ROOT':state,'STATE':state/'native/current.json',
                                'verify':lambda:None,'manifest':lambda:self.build,
                                'compose':lambda data:(self.candidate,r.identify(data)[0])}.items():
                stack.enter_context(patch.object(r,name,value))
            unit=self
            class Telnet:
                def __init__(self):
                    unit.shell_count+=1; self.pid=unit.shell_count;unit.live_shells.add(self.pid)
                def close(self): unit.live_shells.discard(self.pid)
            for name, value in {'fetch':self.fetch,'ftp_connect':self.connect,'Telnet':Telnet,
                                'shell':self.shell,'metadata':lambda *a:None,'normal_reboot':self.boot}.items():
                stack.enter_context(patch.object(r.device,name,value))
            stack.enter_context(patch.object(r.transport,'ADDRESS','192.168.1.4'))
            stack.enter_context(patch.object(r.time,'monotonic',lambda:self.clock))
            def sleep(seconds): self.clock += seconds
            stack.enter_context(patch.object(r.time,'sleep',sleep))
            stack.enter_context(patch.object(wizard,'STATE',state))
            stack.enter_context(patch.object(wizard,'SESSION',state/'session.json'))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            yield self

    def install(self, p=None):
        p = p or selected()
        for step in r.selection.build_plan(p)['steps']:
            r.run(step['action'], p)

    def rollback(self, p=None):
        p = p or selected()
        result = r.run('rollback', p)
        if result['status'] not in ('accepted','unchanged'): r.run('accept', p)


class RecoveryTests(unittest.TestCase):
    def test_clock_correction_and_failed_mirror_do_not_select_an_older_target(self):
        with Unit().use() as unit:
            unit.install(selected(power_unit='hp'));before=r.read_images(unit.connect())
            write=r.durable.write_bytes;failed=[False]
            def fail_mirror(path,data):
                if Path(path).name=='transaction.json.mirror' and not failed[0]:
                    failed[0]=True;raise OSError('interrupted mirror write')
                return write(path,data)
            with patch.object(r.time,'time_ns',return_value=1),patch.object(r.durable,'write_bytes',fail_mirror):
                with self.assertRaises(RuntimeError):r.run('install-disabled',selected(power_unit='kw'))
            unit.rollback();self.assertEqual(r.read_images(unit.connect()),before)

    def test_inspect_does_not_write_to_unit(self):
        with Unit().use() as unit:
            r.run('inspect',selected())
            self.assertEqual(unit.events,[])

    def test_failed_phase_retries_after_restoring_accepted_phase(self):
        with Unit().use() as unit:
            p=selected(); r.run('install-disabled',p); r.run('observe-disabled',p)
            previous=unit.files[r.OPTIONS]; unit.reboot_fault=True
            with self.assertRaises(r.RetryableError): r.run('preflight',p)
            self.assertEqual(unit.files[r.OPTIONS],previous)
            unit.reboot_fault=False
            r.run('preflight',p);r.run('accept-self-write',p);r.run('accept-enable',p);r.run('observe-enabled',p)
            self.assertEqual(r.load_state()['phase'],'enabled')

    def test_legacy_receipt_restores_without_legacy_backup_jar(self):
        with Unit().use() as unit:
            unit.install()
            shutil.rmtree(r.STATE_ROOT)
            for path in (r.UNIT,r.JOURNAL,r.LOCK): unit.files.pop(path,None)
            unit.files[r.RECEIPT]=json.dumps({'backup':r.REMOTE+'/backup-'+r.device.sha(unit.stock)[:16]+'.jar',
                'carrier_hex':unit.stock.hex(),'ui_hex':None,'options_hex':None,'previous_receipt_sha256':None}).encode()
            unit.running=False; unit.rollback()
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_legacy_local_backup_restores_corrupt_remote_receipt(self):
        with Unit().use() as unit:
            unit.install();shutil.rmtree(r.STATE_ROOT)
            for path in (r.UNIT,r.JOURNAL,r.LOCK):unit.files.pop(path,None)
            unit.files[r.RECEIPT]=b'{'
            folder=r.local('logs')/'legacy/incoming-backup';folder.mkdir(parents=True)
            (folder/'carrier.jar').write_bytes(unit.stock)
            (folder/'manifest.json').write_text(json.dumps({'carrier.jar':r.device.sha(unit.stock),
                'ui.jar':None,'options.properties':None,'previous-receipt.json':None}))
            unit.rollback();self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_damaged_wizard_session_uses_runtime_recovery(self):
        with Unit().use() as unit:
            unit.install();wizard.SESSION.write_text('{')
            answers=iter(['yes','192.168.1.4','yes'])
            with patch.object(wizard,'request_credentials'):
                wizard.rollback('en',lambda _:next(answers),backend.execute)
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)
            self.assertEqual(wizard.read_session()['status'],'rollback-complete')

    def test_valid_json_with_missing_session_fields_does_not_block_recovery(self):
        with Unit().use() as unit:
            unit.install();wizard.SESSION.write_text('{"host":"192.168.1.4"}')
            answers=iter(['yes','','yes'])
            with patch.object(wizard,'request_credentials'):
                wizard.rollback('en',lambda _:next(answers),backend.execute)
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_new_folder_interrupted_before_transaction_does_not_roll_back_another_install(self):
        with Unit().use() as unit:
            unit.install();before=r.read_images(unit.connect())
            with tempfile.TemporaryDirectory() as other,patch.object(r,'STATE_ROOT',Path(other)),patch.object(r,'STATE',Path(other)/'native/current.json'):
                def stop(kind,path):
                    if kind=='link' and path==r.LOCK:raise CutPower()
                unit.hook=stop
                with self.assertRaises(CutPower):r.run('install-disabled',selected(power_unit='hp'))
                unit.hook=None
                self.assertEqual(r.run('rollback',selected())['status'],'unchanged')
            self.assertEqual(r.read_images(unit.connect()),before)

    def test_wizard_retries_failed_login_without_poisoning_session(self):
        with Unit().use() as unit:
            c=config.blank();c.update(train=config.SUPPORTED[0],mu=config.SUPPORTED[1]);c['options']['oil_temperature_fix']=True
            answers=iter(['yes','yes','192.168.1.4','yes']);unit.offline=True
            with patch.object(wizard,'request_credentials'):
                with self.assertRaises(r.RetryableError):wizard.install(c,'en',lambda _:next(answers),backend.execute)
                self.assertEqual(wizard.read_session()['status'],'retryable')
                unit.offline=False;answers=iter(['yes','yes','','yes','yes','yes','yes'])
                wizard.install(c,'en',lambda _:next(answers),backend.execute)
            self.assertEqual(wizard.read_session()['status'],'complete')

    def test_unit_token_mismatch_stops_recovery_without_writes(self):
        with Unit().use() as unit:
            unit.install();before=len(unit.events)
            unit.files[r.UNIT]=b'0'*32
            with self.assertRaisesRegex(ValueError,'Different unit'):unit.rollback()
            self.assertEqual(len(unit.events),before)

    def test_lock_acquisition_race_never_replaces_another_owner(self):
        with Unit().use() as unit:
            shell=unit.shell
            def other_wins(telnet,command,**kwargs):
                if '/ln -i ' in command:unit.files[r.LOCK]=b'f'*32
                return shell(telnet,command,**kwargs)
            with patch.object(r.device,'shell',other_wins):
                with self.assertRaises(r.RetryableError):r.run('install-disabled',selected())
            self.assertEqual(unit.files[r.LOCK],b'f'*32)
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_no_changes_rollback_on_clean_stock_is_a_noop(self):
        with Unit().use() as unit:
            self.assertEqual(r.run('rollback',selected())['status'],'unchanged')
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_missing_six_minute_acceptance_and_changed_selection_stop(self):
        with Unit().use() as unit:
            p=selected();r.run('install-disabled',p);r.run('accept',p)
            with self.assertRaisesRegex(ValueError,'Six-minute'):r.run('preflight',p)
            r.run('observe-disabled',p)
            with self.assertRaisesRegex(ValueError,'Selected configuration'):r.run('preflight',selected(power_unit='hp'))
            self.assertEqual(unit.files[r.OPTIONS],r.properties(p,'disabled'))

    def test_full_install_and_exact_rollback(self):
        with Unit().use() as unit:
            unit.install(); unit.rollback()
            self.assertEqual(unit.files[r.device.ACTIVE], unit.stock)
            for path in (r.UI,r.OPTIONS,r.RECEIPT,r.LOCK): self.assertNotIn(path,unit.files)
            self.assertFalse(r.load_state()['pending'])

    def test_recovery_works_with_hmi_stopped(self):
        with Unit().use() as unit:
            unit.install(); unit.running=False
            unit.rollback()
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_unknown_carrier_or_protected_file_still_stops_before_writes(self):
        for path in (r.device.ACTIVE,'/protected'):
            with self.subTest(path=path), Unit().use() as unit:
                unit.files[path]=b'foreign'
                with self.assertRaises((ValueError,r.RetryableError)): r.run('install-disabled',selected())
                self.assertEqual(unit.events,[])

    def test_corrupt_state_and_one_journal_copy_do_not_block_recovery(self):
        with Unit().use() as unit:
            unit.install(); r.STATE.write_text('{')
            r.local('transaction.json').write_text('{')
            unit.rollback(); self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_remote_mirror_recovers_both_local_journal_copies(self):
        with Unit().use() as unit:
            unit.install()
            r.local('transaction.json').write_text('{')
            Path(str(r.local('transaction.json'))+'.mirror').write_text('{')
            unit.rollback(); self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_missing_remote_backup_and_corrupt_receipt_use_local_preimages(self):
        with Unit().use() as unit:
            unit.install(); unit.files[r.RECEIPT]=b'{'
            unit.rollback(); self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_rollback_retry_never_consumes_next_generation(self):
        with Unit().use() as unit:
            unit.install(selected(power_unit='hp'))
            first=unit.files[r.OPTIONS]
            unit.install(selected(power_unit='kw'))
            cut=[False]
            def fail(kind,path):
                if kind=='rename' and path==r.RECEIPT and not cut[0]:
                    cut[0]=True; raise CutPower()
            unit.hook=fail
            with self.assertRaises(CutPower): r.run('rollback',selected(power_unit='kw'))
            unit.hook=None; unit.rollback()
            self.assertEqual(unit.files[r.OPTIONS],first)
            unit.rollback(); self.assertEqual(unit.files[r.OPTIONS],first)

    def test_rollback_interruption_after_stock_carrier_can_resume(self):
        with Unit().use() as unit:
            unit.install()
            def fail(kind,path):
                if kind=='rename' and path==r.device.ACTIVE: raise CutPower()
            unit.hook=fail
            with self.assertRaises(CutPower): r.run('rollback',selected())
            unit.hook=None; unit.rollback()
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_diagnostic_disk_failure_does_not_block_install_or_restore(self):
        with Unit().use() as unit:
            write=r.durable.write_bytes
            def failed_logs(path,data):
                if Path(path).name=='report.json': raise OSError('disk full for diagnostics')
                return write(path,data)
            with patch.object(r.durable,'write_bytes',failed_logs):
                unit.reboot_fault=True
                with self.assertRaises(r.RetryableError): r.run('install-disabled',selected())
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_state_disk_failure_restores_before_attempting_more_logs(self):
        with Unit().use() as unit:
            write=r.durable.write_bytes
            def failed_state(path,data):
                if Path(path)==r.STATE or Path(path).name=='report.json': raise OSError('disk full')
                return write(path,data)
            with patch.object(r.durable,'write_bytes',failed_state):
                with self.assertRaises(RuntimeError): r.run('install-disabled',selected())
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)
            unit.rollback(); self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_first_connection_failure_is_retryable_without_rollback(self):
        with Unit().use() as unit:
            unit.offline=True
            with self.assertRaises(r.RetryableError): r.run('install-disabled',selected())
            unit.offline=False; unit.install()
            self.assertEqual(unit.files[r.device.ACTIVE],unit.candidate)

    def test_partial_upload_does_not_publish_and_retry_is_supported(self):
        with Unit().use() as unit:
            hit=[False]
            def fail(kind,path):
                if kind=='store' and path.startswith(r.device.ACTIVE+'.') and not hit[0]:
                    hit[0]=True; unit.files[path]=b'partial'; raise ConnectionResetError('partial upload')
            unit.hook=fail
            with self.assertRaises(r.RetryableError): r.run('install-disabled',selected())
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)
            unit.hook=None; unit.install(); self.assertEqual(unit.files[r.device.ACTIVE],unit.candidate)

    def test_persistent_connection_loss_retains_recoverable_transaction(self):
        with Unit().use() as unit:
            def fail(kind,path):
                if kind=='rename' and path==r.UI:
                    unit.offline=True; raise ConnectionResetError('cable removed')
            unit.hook=fail
            with self.assertRaises(RuntimeError): r.run('install-disabled',selected())
            unit.hook=None; unit.offline=False; unit.rollback()
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_partial_recovery_stage_is_disposable_on_retry(self):
        with Unit().use() as unit:
            unit.install()
            def fail(kind,path):
                if kind=='store' and path.startswith(r.device.ACTIVE+'.'):
                    unit.files[path]=b'partial'; raise CutPower()
            unit.hook=fail
            with self.assertRaises(CutPower): r.run('rollback',selected())
            unit.hook=None; unit.rollback(); self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_keyboard_interrupt_restores_exact_preimage(self):
        with Unit().use() as unit:
            hit=[False]
            def fail(kind,path):
                if kind=='rename' and path==r.OPTIONS and not hit[0]:
                    hit[0]=True; raise KeyboardInterrupt()
            unit.hook=fail
            with self.assertRaises(r.RetryableError): r.run('install-disabled',selected())
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)
            self.assertNotIn(r.OPTIONS,unit.files)

    def test_second_folder_cannot_modify_an_active_installation(self):
        with Unit().use() as unit:
            r.run('install-disabled',selected())
            original=dict(unit.files)
            with tempfile.TemporaryDirectory() as other, patch.object(r,'STATE_ROOT',Path(other)),patch.object(r,'STATE',Path(other)/'native/current.json'):
                with self.assertRaises(r.RetryableError): r.run('install-disabled',selected(power_unit='hp'))
            for key,value in original.items(): self.assertEqual(unit.files[key],value)

    def test_local_lock_excludes_second_process(self):
        with Unit().use():
            with r.durable.lock(r.local('runtime.lock')):
                with self.assertRaises(RuntimeError): r.run('install-disabled',selected())

    def test_same_folder_cannot_resume_while_old_remote_shell_still_runs(self):
        with Unit().use() as unit:
            r.run('install-disabled',selected())
            lease=json.loads(unit.files[r.WRITER])
            unit.files[lease['marker']]=b'still-same-boot'
            unit.live_shells.add(lease['pid'])
            before=r.read_images(unit.connect())
            with self.assertRaisesRegex(ValueError,'Previous installer service session'):unit.rollback()
            self.assertEqual(r.read_images(unit.connect()),before)
            unit.live_shells.clear();unit.rollback()
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_corrupt_writer_metadata_uses_verified_local_copy(self):
        with Unit().use() as unit:
            unit.install();unit.files[r.WRITER]=b'{}'
            unit.rollback();self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_invalid_status_or_changed_options_fail_rollback_acceptance(self):
        for corrupt_options in (False,True):
            with self.subTest(options=corrupt_options),Unit().use() as unit:
                unit.install(selected(power_unit='hp')); unit.install(selected(power_unit='kw'))
                r.run('rollback',selected())
                if corrupt_options: unit.files[r.OPTIONS]=b'corrupt'
                else: unit.files[r.CONFIG_STATUS]=b'sportconfig-v4 999 invalid:invalid\n'
                with self.assertRaises(ValueError): r.run('accept',selected())
                self.assertTrue(r.load_state()['pending'])

    def test_stock_acceptance_requires_a_real_boot_marker_clear(self):
        with Unit().use() as unit:
            unit.install()
            with patch.object(r.device,'normal_reboot',lambda *a:None): r.run('rollback',selected())
            with self.assertRaisesRegex(ValueError,'Fresh unit reboot'): r.run('accept',selected())
            unit.boot(); r.run('accept',selected()); self.assertFalse(r.load_state()['pending'])

    def test_failed_first_boot_can_restore_and_accept_stock(self):
        with Unit().use() as unit:
            with patch.object(r.device,'normal_reboot',lambda *a:None): r.run('install-disabled',selected())
            unit.rollback(); self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)

    def test_rollback_reboot_rejection_keeps_restored_target_for_retry(self):
        with Unit().use() as unit:
            unit.install(); unit.reboot_fault=True
            with self.assertRaises(r.device.NativeRebootRejected): r.run('rollback',selected())
            self.assertEqual(unit.files[r.device.ACTIVE],unit.stock)
            unit.reboot_fault=False; unit.rollback()
            self.assertFalse(r.load_state()['pending'])


if __name__=='__main__': unittest.main(verbosity=2)
