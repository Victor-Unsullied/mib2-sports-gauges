"""Offline configuration and human-confirmation regression tests."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config, wizard, backend


def selected(**options):
    c=config.blank(); c.update(train=config.SUPPORTED[0],mu=config.SUPPORTED[1]); c['options'].update(options)
    return c


class ConfigTests(unittest.TestCase):
    def test_roundtrip_and_independent_fixes(self):
        for oil,coolant in ((False,False),(True,False),(False,True),(True,True)):
            c=selected(oil_temperature_fix=oil,coolant_temperature_fix=coolant,power_min=10,power_max=250)
            self.assertEqual(config.parse(config.dumps(c)),c)
            profile=backend.profile(c,'tr',True)
            values=backend.runtime.properties(profile,'enabled').decode()
            self.assertIn('oil='+str(oil).lower(),values)
            self.assertIn('coolant='+str(coolant).lower(),values)
    def test_unknown_duplicate_and_malicious_xml_rejected(self):
        xml=config.dumps(selected())
        for data in (xml.replace(b'<options>',b'<options><option name="unknown" value="true" />'),
                     xml.replace(b'<options>',b'<options><option name="oil_temperature_fix" value="true" />'),
                     xml.replace(b'<device ',b'<device extra="1" '),
                     b'<!DOCTYPE foo [<!ENTITY x "abc">]>'+xml,
                     xml.replace(b'value="false"',b'value="yes"',1)):
            with self.assertRaises((ValueError,config.ET.ParseError)):config.parse(data)
    def test_ranges_and_unknown_versions(self):
        for lo,hi in ((None,2),(4,3),(-1,7),(0,1000),(True,2)):
            with self.assertRaises(ValueError):config.validate(selected(power_min=lo,power_max=hi))
        c=selected();c['train']='OTHER';self.assertEqual(config.parse(config.dumps(c))['train'],'OTHER')
    def test_local_hosts_only(self):
        self.assertEqual(backend.host_address('192.168.1.4'),'192.168.1.4')
        for h in ('8.8.8.8','127.0.0.1','0.0.0.0','host; reboot','::1'):
            with self.assertRaises(ValueError):backend.host_address(h)
    def test_default_has_no_corrections(self):
        self.assertFalse(config.DEFAULTS['oil_temperature_fix'])
        self.assertFalse(config.DEFAULTS['coolant_temperature_fix'])
        self.assertFalse(config.DEFAULTS['enable_torque_gauge'])
        self.assertEqual(config.DEFAULTS['power_source'],'factory')

    def test_credentials_are_prompted_without_serializing_them(self):
        answers=['sample-ftp-user','sample-terminal-user']; passwords=['example-test-secret','']
        with contextlib.redirect_stdout(io.StringIO()):
            wizard.request_credentials('en',lambda _:answers.pop(0),lambda _:passwords.pop(0))
        self.assertEqual(backend.transport.FTP_USER,'sample-ftp-user')
        self.assertEqual(backend.transport.FTP_PASSWORD,'example-test-secret')
        self.assertNotIn(b'example-test-secret',config.dumps(selected()))
        backend.transport.FTP_USER=backend.transport.FTP_PASSWORD=None
        backend.transport.TELNET_USER=backend.transport.TELNET_PASSWORD=None


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)/'state'
        self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(wizard,'STATE',self.state))
        self.stack.enter_context(patch.object(wizard,'request_credentials'))
        self.stack.enter_context(patch.object(wizard,'SESSION',self.state/'session.json'))
        self.stack.enter_context(patch.object(backend.runtime,'STATE',self.state/'native/current.json'))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
    def test_declining_settings_or_risk_never_executes(self):
        for answers in (['no'],['yes','no']):
            calls=[];wizard.install(selected(oil_temperature_fix=True),'en',lambda _:answers.pop(0),lambda *a:calls.append(a))
            self.assertEqual(calls,[])
    def test_untested_versions_warn_and_use_normal_file_check_path(self):
        config_data = selected(oil_temperature_fix=True)
        config_data['mu'] = '9999'
        calls = []
        for responses in (['yes', 'no'], ['yes', 'yes', '192.168.1.4', 'yes', 'no']):
            answers = iter(responses)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                wizard.install(config_data, 'en', lambda _: next(answers), lambda action, *_: calls.append(action))
            self.assertIn('This Train/MU has not been tested', output.getvalue())
        self.assertEqual(calls, ['install-disabled'])
    def test_each_stage_requires_confirmation_and_resume_pins_settings(self):
        c=selected(oil_temperature_fix=True);answers=['yes','yes','192.168.1.4','yes','no'];calls=[]
        wizard.install(c,'en',lambda _:answers.pop(0),lambda a,*_:calls.append(a))
        self.assertEqual(calls,['install-disabled'])
        self.assertEqual(json.loads(wizard.SESSION.read_text())['next'],1)
        altered=selected(coolant_temperature_fix=True)
        with self.assertRaises(ValueError):wizard.install(altered,'en',lambda _:'yes',lambda a,*_:calls.append(a))
        answers=['yes','yes','','yes','yes','yes']
        wizard.install(c,'en',lambda _:answers.pop(0),lambda a,*_:calls.append(a))
        self.assertEqual(calls,['install-disabled','observe-disabled','enable','observe-enabled'])
        self.assertEqual(json.loads(wizard.SESSION.read_text())['status'],'complete')
    def test_failure_blocks_remaining_stages(self):
        c=selected(enable_torque_gauge=True);answers=['yes','yes','192.168.1.4','yes'];calls=[]
        def fail(a,*_):calls.append(a);raise RuntimeError('device check failed')
        with self.assertRaises(RuntimeError):wizard.install(c,'en',lambda _:answers.pop(0),fail)
        self.assertEqual(calls,['install-disabled'])
        self.assertEqual(json.loads(wizard.SESSION.read_text())['status'],'failed')
        with self.assertRaises(ValueError):wizard.install(c,'en',lambda _:'yes',fail)
    def test_full_plan_retains_all_six_stages(self):
        c=selected(enable_torque_gauge=True);answers=['yes','yes','192.168.1.4']+['yes']*6;calls=[]
        wizard.install(c,'en',lambda _:answers.pop(0),lambda a,*_:calls.append(a))
        self.assertEqual(calls,['install-disabled','observe-disabled','preflight','accept-self-write','accept-enable','observe-enabled'])
    def test_rollback_uses_saved_config_and_accepts_next_boot(self):
        c=selected(oil_temperature_fix=True)
        wizard.write_session({'config':c,'fingerprint':wizard.fingerprint(c),'host':'192.168.1.4','status':'failed','next':0})
        answers=['yes','','yes'];calls=[]
        wizard.rollback('en',lambda _:answers.pop(0),lambda a,cfg,*_:calls.append((a,cfg)))
        self.assertEqual([a for a,_ in calls],['rollback','accept'])
        self.assertTrue(all(cfg==c for _,cfg in calls))
        self.assertEqual(json.loads(wizard.SESSION.read_text())['status'],'rollback-complete')
    def test_windows_gate_never_calls_device(self):
        cpath=Path(self.temp.name)/'config.xml';config.save(selected(oil_temperature_fix=True),cpath)
        with patch.object(wizard.integrity,'verify',return_value=1),patch.object(wizard.platform,'system',return_value='Darwin'),patch.object(wizard.backend,'execute') as device,contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(wizard.main(['--config',str(cpath)],lambda _:''),1)
            device.assert_not_called()

if __name__=='__main__':unittest.main()
