"""Version evidence and the export risk notice; no vehicle access."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
NOTICE_VERSION = '2026-11-04.v1.0.1'
REGISTRY = json.loads((ROOT / 'TESTED_DEVICES.json').read_text(encoding='utf-8'))


def normalize_device(device):
    if device is None: return None
    if type(device) is not dict or set(device) != {'train', 'mu'}:
        raise ValueError('Enter the software train and MU version.')
    if type(device['train']) is not str or type(device['mu']) is not str:
        raise ValueError('Versions must be text.')
    train, mu = device['train'].strip().upper(), device['mu'].strip()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_.-]{2,79}', train) or not re.fullmatch(r'[0-9]{3,4}', mu):
        raise ValueError('Enter a valid software train and a three- or four-digit MU version.')
    return {'train': train, 'mu': mu.zfill(4)}


def assessment(device, language='en'):
    device = normalize_device(device)
    record = next((r for r in REGISTRY['records'] if device and
                   r['train'] == device['train'] and r['mu'] == device['mu']), None)
    tested = bool(record and record['device_version_tested'])
    patch_tested = bool(record and record['configurable_patch_tested'])
    if language == 'tr':
        title = 'Sürümleri girin' if device is None else 'Test edilmiş sürüm' if tested else 'Test edilmemiş sürüm'
        message = ('Dışa aktarmadan önce yazılım train ve MU sürümünü girin.' if device is None else
                   record['scope_tr'] if record else
                   'Bu Train/MU denenmedi. Yükleyici, değişiklik yapmadan önce ünitenin dosyalarını kontrol eder.')
    else:
        title = 'Enter versions' if device is None else 'Tested version' if tested else 'Not tested'
        message = ('Enter the software train and MU version before exporting.' if device is None else
                   record['scope_en'] if record else
                   'This Train/MU has not been tested. The installer checks the unit’s files before making changes.')
    caution = ('Test edilmiş sürümlerde bile arıza ve cihazın kullanılamaz hale gelmesi (brick) mümkündür. Dışa aktarmadan önce tüm kurulum ve trafik güvenliği uyarılarını okuyun.' if language == 'tr' else
               'Failure and a bricked unit are still possible, even on tested versions. Read all installation and traffic-safety warnings before exporting.')
    return {'device_version_status': 'missing' if device is None else 'tested' if tested else 'not_tested',
            'configurable_patch_status': 'tested' if patch_tested else 'not_tested',
            'installation_supported': bool(record and record['installation_profile_available']),
            'hardware': None if record is None else record['hardware'], 'title': title, 'message': message, 'caution': caution}


def notice_paragraphs(device, language='en'):
    status = assessment(device, language)
    if language == 'tr':
        return [status['title'] + '. ' + status['message'],
            'Bu yama orta ekran ünitesinin yazılımını değiştirir. Test edilmiş sürümlerde bile kurulum başarısız olabilir ve cihazı kullanılamaz hale getirebilir (brick). Test edilmiş olması güvenli kurulum veya kurtarma garantisi değildir.',
            'Ünite yanıt vermiyorsa güç düğmesini basılı tutarak yeniden başlatmak yardımcı olabilir; başarılı olacağı garanti edilmez. Ünite normal yollarla kurtarılamazsa profesyonel müdahale gerekir. Onarım, yeniden programlama veya ünitenin değiştirilmesi gerekebilir.',
            'Kurulumu yalnızca araç güvenli bir yerde park halindeyken yapın. Ancak riskleri anlıyorsanız ve olası bir arıza için hazırlıklıysanız devam edin. Beklenmeyen bir arızada orta ekrana bağlı işlevler kısmen veya tamamen çalışmayabilir.',
            'Trafik güvenliğini korumak ve ekran işlevleri kullanılamaz hale gelirse gerekli önlemleri almak sizin sorumluluğunuzdadır. Sürüş sırasında kurulum, yeniden başlatma veya arıza giderme yapmayın; gerekiyorsa güvenli bir yerde durun.']
    return [status['title'] + '. ' + status['message'],
        'This patch modifies the centre-display unit\'s software. Installation can fail and may leave the unit unusable (bricked), even on a tested version. Tested status does not guarantee a successful installation or recovery.',
        'If the unit becomes unresponsive, holding down the power button to restart it may help, but success is not guaranteed. Professional intervention will be required if the unit cannot be recovered through normal means. Repair, reprogramming or replacement may be necessary.',
        'Install only while the vehicle is safely parked. Proceed only if you understand these risks and are prepared for a possible failure. An unexpected failure may leave some or all functions associated with the centre display unavailable.',
        'You remain responsible for traffic safety and for taking appropriate precautions if display-related functions become unavailable. Do not install, restart or troubleshoot the unit while driving; stop safely if necessary.']


def acceptance_digest(options, device):
    data = {'notice_version': NOTICE_VERSION, 'options': options, 'device': normalize_device(device)}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode('utf-8')).hexdigest()


def require_exportable(profile):
    if profile['device'] is None: raise ValueError('Software train and MU version are required before export.')
    acceptance = profile['risk_acceptance']
    expected = {'notice_version': NOTICE_VERSION, 'selection_sha256': acceptance_digest(profile['options'], profile['device'])}
    if acceptance != expected: raise ValueError('Review and acknowledge the current risk notice before exporting.')
