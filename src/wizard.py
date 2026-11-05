"""Human-paced Windows install/recovery wizard over the guarded native stages."""
import argparse
import contextlib
from datetime import datetime, timezone
import hashlib
import getpass
import json
from pathlib import Path
import platform
import sys
from . import config, integrity, backend

STATE = config.ROOT / 'state'
SESSION = STATE / 'session.json'

STAGES = {
    'install-disabled': ('Back up the current files and prepare the selected fixes without enabling them. The unit will restart.', 'Mevcut dosyaları yedekle ve seçtiğiniz düzeltmeleri kapalı olarak hazırla. Ünite yeniden başlayacak.'),
    'observe-disabled': ('Check that the screen has restarted normally. The installer will watch it for six minutes. Keep the connection and power on.', 'Ekranın normal açıldığını kontrol edin. Program altı dakika boyunca kontrol yapacak. Bağlantıyı ve gücü kesmeyin.'),
    'preflight': ('Check whether the Sports screen can use the new settings. The unit will restart.', 'Spor ekranının yeni ayarları kullanıp kullanamadığını kontrol et. Ünite yeniden başlayacak.'),
    'accept-self-write': ('Confirm the previous restart and check that settings can be written. The unit will restart again.', 'Önceki açılışı kontrol et ve ayarların yazılabildiğini dene. Ünite tekrar başlayacak.'),
    'accept-enable': ('Confirm the checks, then turn on only your selected settings. The unit will restart.', 'Kontrolleri doğrula ve yalnızca seçtiğiniz ayarları aç. Ünite yeniden başlayacak.'),
    'enable': ('Turn on your selected temperature corrections. The unit will restart.', 'Seçtiğiniz sıcaklık düzeltmelerini aç. Ünite yeniden başlayacak.'),
    'observe-enabled': ('Check the screen and gauges. The installer will watch the enabled setup for six minutes.', 'Ekranı ve göstergeleri kontrol edin. Program açık durumdaki sistemi altı dakika izleyecek.'),
}
RISK = (
    'EXPERIMENTAL SOFTWARE. Your engine/head-unit combination is probably untested.\nYou accept all risk. Installation may disable the screen and its functions or brick\nthe unit. Repair or replacement may be necessary. Backups do not guarantee recovery.\nOnly proceed while safely parked, with stable power and a recovery plan.',
    'DENEYSEL YAZILIM. Motor/multimedya kombinasyonunuz büyük olasılıkla denenmedi.\nTüm risk size aittir. Kurulum ekranı ve bağlı işlevleri bozabilir, üniteyi kullanılamaz\nhale getirebilir. Onarım veya değişim gerekebilir. Yedek almak kurtarma garantisi değildir.\nYalnızca park halindeyken, kesintisiz güç ve geri dönüş hazırlığıyla devam edin.'
)


def pick(pair, language):
    return pair[language == 'tr']


def confirm(message, language, ask=input):
    answer = ask(message + (' [evet/Hayır]: ' if language == 'tr' else ' [yes/No]: ')).strip().lower()
    return answer in (('evet', 'e') if language == 'tr' else ('yes', 'y'))


def fingerprint(selected):
    stable = {k: v for k, v in selected.items() if k != 'language'}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


def write_session(session):
    session['revision'] = session.get('revision', 0) + 1
    backend.runtime.durable.save(SESSION.with_suffix('.recovery'), session)
    backend.runtime.durable.write_bytes(SESSION, json.dumps(session, indent=2).encode('ascii') + b'\n')


def read_session(recovery=False):
    try:
        saved = backend.runtime.durable.load(SESSION.with_suffix('.recovery'))
    except ValueError:
        saved = None
    if saved is not None:
        return saved
    try:
        value = json.loads(SESSION.read_text(encoding='utf-8')) if SESSION.exists() else None
        if value is not None and not isinstance(value, dict):
            raise ValueError('Invalid saved session')
        return value
    except ValueError:
        if recovery:
            return None  # Runtime recovery uses its independent journal/receipt.
        raise ValueError('Session file damaged. Keep this folder and use --rollback.') from None


class SafeLog:
    def __init__(self, stream):
        self.stream = stream
    def write(self, value):
        try: self.stream.write(value)
        except OSError: pass
        return len(value)
    def flush(self):
        try: self.stream.flush()
        except OSError: pass


def run_stage(action, selected, lang, host, execute=backend.execute):
    logs = STATE / 'logs'
    target = logs / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + action + '.txt')
    print(pick(('Working. Keep the connection on; detailed output is saved to ', 'İşlem sürüyor. Bağlantıyı kesmeyin; ayrıntılı kayıt: '), lang) + str(target), flush=True)
    with contextlib.ExitStack() as stack:
        try:
            logs.mkdir(parents=True, exist_ok=True)
            log = target.open('w', encoding='utf-8')
            def close_log():
                try: log.close()
                except OSError: pass
            stack.callback(close_log)
            stack.enter_context(contextlib.redirect_stdout(SafeLog(log)))
            stack.enter_context(contextlib.redirect_stderr(SafeLog(log)))
        except OSError:
            pass  # Durable transaction backups remain mandatory in the runtime.
        result = execute(action, selected, lang, host)
    print(pick(('Step completed.', 'Adım tamamlandı.'), lang), flush=True)
    return result


def request_credentials(lang, ask=input, secret=getpass.getpass):
    print(pick(('Enter your unit service login details. Passwords are hidden and not saved.',
                'Ünitenin servis giriş bilgilerini girin. Şifreler görünmez ve kaydedilmez.'), lang))
    user = ask(pick(('FTP username: ', 'FTP kullanıcı adı: '), lang)).strip()
    password = secret(pick(('FTP password: ', 'FTP şifresi: '), lang))
    telnet_user = ask(pick(('Telnet username: ', 'Telnet kullanıcı adı: '), lang)).strip()
    telnet_password = secret(pick(('Telnet password (Enter if none): ', 'Telnet şifresi (yoksa Enter): '), lang))
    if not user or not telnet_user or any('\r' in v or '\n' in v for v in (user,password,telnet_user,telnet_password)):
        raise ValueError(pick(('Invalid service login.', 'Servis giriş bilgileri geçersiz.'), lang))
    backend.transport.FTP_USER, backend.transport.FTP_PASSWORD = user, password
    backend.transport.TELNET_USER, backend.transport.TELNET_PASSWORD = telnet_user, telnet_password


def request_host(lang, ask=input, previous=''):
    hint = f' [{previous}]' if previous else ''
    value = ask(pick(('Head-unit IPv4 address shown in Green Engineering Menu', 'Green Engineering Menu’de görünen ünite IPv4 adresi'), lang) + hint + ': ').strip()
    return backend.host_address(value or previous)


def rollback(lang, ask=input, execute=backend.execute):
    saved = read_session(recovery=True)
    try:
        selected = config.validate(saved['config']) if saved else config.blank()
    except (ValueError, KeyError, TypeError):
        selected = config.blank()  # Recovery's target is in the native journal.
    print(pick(('Rollback requires working service access. An unreachable unit cannot be recovered by this program.', 'Geri dönüş için servis bağlantısının çalışması gerekir. Erişilemeyen ünite bu programla kurtarılamaz.'), lang))
    if not confirm(pick(('Restore the backup saved before installation?', 'Kurulumdan önceki yedeği geri yüklemek istiyor musunuz?'), lang), lang, ask):
        return 0
    try:
        owner = backend.runtime.durable.load(backend.runtime.local('owner.json'))
    except ValueError:
        owner = None
    host = request_host(lang, ask, saved.get('host', '') if saved else (owner or {}).get('host', ''))
    request_credentials(lang, ask)
    session = saved or {'config': selected, 'fingerprint': fingerprint(selected), 'host': host, 'next': 0}
    session['host'] = host
    session['status'] = 'rollback-started'
    # Failure to write wizard bookkeeping must not prevent runtime recovery.
    try: write_session(session)
    except OSError: pass
    result = run_stage('rollback', selected, lang, host, execute)
    if result and result.get('status') in ('accepted', 'unchanged'):
        session['status'] = 'rollback-complete'; write_session(session)
        message = ('No installer changes were found; no files needed restoration.', 'Kurulum değişikliği bulunmadı; geri yüklenecek dosya yok.') if result['status'] == 'unchanged' else ('The recorded rollback is already complete.', 'Kayıtlı geri dönüş zaten tamamlandı.')
        print(pick(message, lang))
        return 0
    session['status'] = 'rollback-awaiting-boot'; write_session(session)
    if not confirm(pick(('Wait for the normal screen to return. Has it restarted normally?', 'Normal ekran gelene kadar bekleyin. Ünite normal açıldı mı?'), lang), lang, ask):
        print(pick(('Stopped. Run install.py --rollback again when service access is available.', 'Durduruldu. Servis erişimi geldiğinde install.py --rollback komutunu tekrar çalıştırın.'), lang))
        return 0
    run_stage('accept', selected, lang, host, execute)
    session['status'] = 'rollback-complete'; write_session(session)
    print(pick(('Rollback verified. Keep this folder and its state directory.', 'Geri dönüş doğrulandı. Bu klasörü ve state klasörünü saklayın.'), lang))
    return 0


def install(selected, lang, ask=input, execute=backend.execute):
    print('\n' + '\n'.join(config.summary(selected, lang)) + '\n')
    if not confirm(pick(('Are these the settings you want?', 'İstediğiniz ayarlar bunlar mı?'), lang), lang, ask):
        print(pick(('Run configure.py, save config.xml, then return here.', 'configure.py ile ayarları düzenleyip config.xml kaydedin, sonra yeniden başlayın.'), lang))
        return 0
    if not selected['train'] or not selected['mu']:
        raise ValueError(pick(('Enter the software Train and MU before installing.', 'Kurulumdan önce yazılım Train ve MU bilgilerini girin.'), lang))
    options = selected['options']
    if not options['oil_temperature_fix'] and not options['coolant_temperature_fix'] and not backend.selection.needs_sports(backend.profile(selected, lang)):
        print(pick(('No corrections or custom settings selected. Nothing to install.', 'Düzeltme veya özel ayar seçilmedi. Kurulacak bir değişiklik yok.'), lang))
        return 0
    if (selected['train'], selected['mu']) != config.SUPPORTED:
        print(pick((
            'WARNING: This Train/MU has not been tested. The installer will check the unit’s files before making any changes.',
            'UYARI: Bu Train/MU denenmedi. Yükleyici, değişiklik yapmadan önce ünitenin dosyalarını kontrol edecek.',
        ), lang))
    print('\n' + pick(RISK, lang) + '\n')
    if not confirm(pick(('Do you understand and accept these risks?', 'Bu riskleri anlayıp kabul ediyor musunuz?'), lang), lang, ask):
        return 0
    current = read_session()
    if current and current.get('status') not in ('rollback-complete',):
        if current['fingerprint'] != fingerprint(selected):
            raise ValueError(pick(('Settings changed since installation started. Use the saved config or roll back first.', 'Kurulum başladıktan sonra ayarlar değişmiş. Kaydedilen ayarlara dönün veya önce geri alın.'), lang))
        if current.get('status') in ('running', 'failed', 'rollback-started', 'rollback-awaiting-boot'):
            raise ValueError(pick(('An interrupted/failed step needs recovery. Do not retry blindly. Use --rollback with the same folder.', 'Yarım kalan/başarısız işlem geri dönüş gerektiriyor. Körlemesine tekrar denemeyin. Aynı klasörde --rollback kullanın.'), lang))
        if current.get('status') == 'complete':
            print(pick(('This configuration is already installed. Roll it back before starting another installation.', 'Bu yapılandırma zaten kuruldu. Yeni kuruluma başlamadan önce geri alın.'), lang))
            return 0
    host = request_host(lang, ask, current.get('host', '') if current else '')
    request_credentials(lang, ask)
    session = current if current and current.get('status') != 'rollback-complete' else {'config': selected, 'fingerprint': fingerprint(selected), 'next': 0, 'status': 'ready'}
    session['host'] = host
    stages = backend.steps(selected, lang)
    for index in range(session['next'], len(stages)):
        stage = stages[index]
        print(f'\n{index+1}/{len(stages)} — ' + pick(STAGES[stage['action']], lang))
        if not confirm(pick(('Screen normal, vehicle parked, power stable and ready to continue?', 'Ekran normal, araç park halinde, güç kesintisiz; devam etmeye hazır mısınız?'), lang), lang, ask):
            print(pick(('Paused. Keep this folder. Run install.py to continue with the same config.', 'Duraklatıldı. Klasörü saklayın. Aynı ayarlarla devam etmek için install.py çalıştırın.'), lang))
            return 0
        session['status'] = 'running'; write_session(session)
        try:
            run_stage(stage['action'], selected, lang, host, execute)
        except (Exception, KeyboardInterrupt) as error:
            session['status'] = 'retryable' if isinstance(error, backend.runtime.RetryableError) else 'failed'
            try: write_session(session)
            except OSError: pass
            raise
        session.update(next=index+1, status='ready'); write_session(session)
        if stage['reboot_after']:
            print(pick(('Wait for the normal screen before proceeding.', 'Sonraki adıma geçmeden önce normal ekranın gelmesini bekleyin.'), lang))
    session['status'] = 'complete'; write_session(session)
    print(pick(('Installation checks passed. Verify the gauges in your car. Keep the entire folder, backups and state. Report results on the forum.', 'Kurulum kontrolleri geçti. Göstergeleri kendi aracınızda kontrol edin. Klasörü, yedekleri ve state klasörünü saklayın. Sonucu forumda paylaşın.'), lang))
    return 0


def main(argv=None, ask=input):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check package/config offline; no vehicle access')
    parser.add_argument('--plan', action='store_true', help='Show stages offline; no vehicle access')
    parser.add_argument('--rollback', action='store_true', help='Restore using the saved installation/recovery state')
    parser.add_argument('--inspect', action='store_true', help='Read-only unit compatibility check; no device writes')
    parser.add_argument('--state-dir', type=Path, help='Existing state folder, including an original v1.0 installation')
    parser.add_argument('--config', type=Path, default=config.ROOT / 'config.xml')
    args = parser.parse_args(argv)
    if args.state_dir is not None:
        global STATE, SESSION
        STATE = args.state_dir.resolve()
        if not STATE.is_dir():
            parser.error('--state-dir must be an existing state directory')
        SESSION = STATE / 'session.json'
        backend.runtime.STATE_ROOT = STATE
        backend.runtime.STATE = STATE / 'native/current.json'
    lang = 'en'
    try:
        if not args.check and not args.plan:
            lang = ask('Language / Dil [en/tr, default en]: ').strip().lower() or 'en'
            if lang not in ('en', 'tr'):
                raise ValueError('Choose en or tr.')
        count = integrity.verify()
        if args.inspect and (args.check or args.plan):
            raise ValueError('Use --inspect on its own.')
        if args.rollback:
            if args.check or args.plan or args.inspect:
                raise ValueError('Use --rollback on its own.')
            if platform.system() != 'Windows':
                raise ValueError(pick(('Installation/recovery is supported on Windows only.', 'Kurulum/geri dönüş yalnızca Windows içindir.'), lang))
            with backend.runtime.durable.lock(STATE / 'wizard.lock'):
                return rollback(lang, ask)
        selected = config.read(args.config)
        if args.check:
            backend.runtime.verify()
            print(f'PASS: {count} package files and config.xml validated. No vehicle connection.')
            return 0
        if args.plan:
            for step in backend.steps(selected):
                print(str(step['number']) + '. ' + STAGES[step['action']][0])
            return 0
        if platform.system() != 'Windows':
            raise ValueError(pick(('Installation is for Windows. --check and --plan work offline here.', 'Kurulum Windows içindir. Burada --check ve --plan ile çevrimdışı inceleyebilirsiniz.'), lang))
        if args.inspect:
            host = request_host(lang, ask)
            request_credentials(lang, ask)
            run_stage('inspect', selected, lang, host)
            print(pick(('Read-only file and HMI checks passed. No unit files changed.', 'Salt okunur dosya ve HMI kontrolleri geçti. Ünitede dosya değiştirilmedi.'), lang))
            return 0
        with backend.runtime.durable.lock(STATE / 'wizard.lock'):
            return install(selected, lang, ask)
    except (Exception, KeyboardInterrupt) as error:
        print('\n' + pick(('STOPPED. No following step will run. ', 'DURDURULDU. Sonraki adım çalıştırılmayacak. '), lang) + str(error), file=sys.stderr)
        print(pick(('If installation started, keep the folder and logs. Use --rollback only with working service access.', 'Kurulum başladıysa klasörü ve kayıtları saklayın. --rollback yalnızca servis erişimi çalışırken kullanılabilir.'), lang), file=sys.stderr)
        return 1
