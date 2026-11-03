"""Independent Sports options; offline preview and independently configured packages."""
import hashlib
import io
import json
from pathlib import Path
import zipfile
import compatibility

ROOT = Path(__file__).resolve().parent
CATALOG = json.loads((ROOT / 'configurator/catalog.json').read_text(encoding='utf-8'))
GAUGE_KEYS = ('enable_boost_gauge', 'enable_gmeter_gauge', 'enable_coolant_gauge', 'enable_power_gauge', 'enable_oil_gauge', 'enable_torque_gauge')
BOOLEAN_KEYS = ('oil_temperature_fix', 'coolant_temperature_fix', *GAUGE_KEYS)
ENUMS = {'power_source': ('factory', 'torque'), 'needle_smoothing': ('none', 'stock500'),
         'power_unit': ('factory', 'hp', 'kw')}
RANGE_KEYS = ('torque_min', 'torque_max', 'power_min', 'power_max')


def make_profile(options, language='en', device=None, risk_acknowledged=False):
    if type(risk_acknowledged) is not bool: raise ValueError('Risk acknowledgement must be true or false.')
    device = compatibility.normalize_device(device)
    if language not in ('en', 'tr'): raise ValueError('Unsupported language.')
    if type(options) is not dict or set(options) != set(BOOLEAN_KEYS) | set(ENUMS) | set(RANGE_KEYS):
        raise ValueError('Choose all Sports settings.')
    for key in BOOLEAN_KEYS:
        if type(options[key]) is not bool:
            raise ValueError('A checkbox must be true or false: ' + key)
    for key, allowed in ENUMS.items():
        if type(options[key]) is not str or options[key] not in allowed:
            raise ValueError('Unsupported selection: ' + key)
    for kind in ('torque', 'power'):
        lower, upper = options[kind + '_min'], options[kind + '_max']
        if lower is None and upper is None: continue
        if type(lower) is not int or type(upper) is not int or not 0 <= lower < upper <= 999:
            raise ValueError('Choose whole-number ' + kind + ' limits: 0 <= lower < upper <= 999, or keep both automatic.')
    return {'schema': CATALOG['schema'], 'language': language, 'options': dict(options), 'device': device,
            'risk_acceptance': {'notice_version': compatibility.NOTICE_VERSION, 'selection_sha256': compatibility.acceptance_digest(options, device)} if risk_acknowledged and device else None}


def validate_profile(profile):
    if type(profile) is not dict:
        raise ValueError('Invalid selection.')
    if profile.get('schema') == 'golf.sports.selection/v2' and set(profile) == {'schema','options'}:
        old = profile['options']
        previous = {'oil_temperature_fix','coolant_temperature_fix','enable_torque_gauge',*ENUMS}
        if type(old) is not dict or set(old) != previous: raise ValueError('Invalid older selection.')
        return make_profile({**CATALOG['defaults'], **old})
    if profile.get('schema') == 'golf.sports.selection/v3' and set(profile) == {'schema','language','options'}:
        return make_profile({**CATALOG['defaults'], **profile['options']}, profile['language'])
    if profile.get('schema') == 'golf.sports.selection/v4' and set(profile) == {'schema','language','options','device','risk_acceptance'}:
        if type(profile['options']) is not dict or set(profile['options']) != set(BOOLEAN_KEYS) | set(ENUMS):
            raise ValueError('Invalid older selection.')
        # New native code requires a fresh export review; old acknowledgements do not carry over.
        return make_profile({**CATALOG['defaults'], **profile['options']}, profile['language'], profile['device'])
    if set(profile) != {'schema','language','options','device','risk_acceptance'} or profile['schema'] != CATALOG['schema']:
        raise ValueError('Unsupported selection version.')
    result = make_profile(profile['options'], profile['language'], profile['device'])
    if profile['risk_acceptance'] is not None:
        expected = {'notice_version': compatibility.NOTICE_VERSION, 'selection_sha256': compatibility.acceptance_digest(result['options'], result['device'])}
        if result['device'] is None or profile['risk_acceptance'] != expected:
            raise ValueError('Risk acknowledgement is outdated or belongs to different settings.')
        result['risk_acceptance'] = expected
    return result



def load_profile(path):
    path = Path(path)
    if path.stat().st_size > 16384:
        raise ValueError('Selection file is too large.')
    return validate_profile(json.loads(path.read_text(encoding='utf-8')))


def needs_sports(profile):
    options = validate_profile(profile)['options']
    return (any(not options[key] for key in GAUGE_KEYS[:-1]) or options['enable_torque_gauge'] or options['power_source'] == 'torque'
            or options['needle_smoothing'] == 'stock500' or options['power_unit'] != 'factory'
            or any(options[key] is not None for key in RANGE_KEYS))


def label(item, language):
    return item.get('label_tr', item['label']) if language == 'tr' else item['label']


def summary(profile):
    profile = validate_profile(profile)
    options, language = profile['options'], profile['language']
    rows = []
    for item in CATALOG['checkboxes']:
        value = ('Açık' if options[item['id']] else 'Kapalı') if language == 'tr' else ('On' if options[item['id']] else 'Off')
        rows.append(label(item, language) + ': ' + value)
    for item in CATALOG['dropdowns']:
        choice = next(row for row in item['choices'] if row['value'] == options[item['id']])
        rows.append(label(item, language) + ': ' + label(choice, language))
    for kind in ('torque', 'power'):
        title = ('Tork sınırları' if kind == 'torque' else 'Güç sınırları') if language == 'tr' else kind.title() + ' limits'
        unit = 'Nm' if kind == 'torque' else {'hp':'HP', 'kw':'kW', 'factory': 'fabrika birimi' if language == 'tr' else 'factory unit'}[options['power_unit']]
        value = ('Varsayılan' if language == 'tr' else 'Default') if options[kind + '_min'] is None else str(options[kind + '_min']) + '–' + str(options[kind + '_max']) + ' ' + unit
        rows.append(title + ': ' + value)
    return rows


def build_plan(profile):
    profile = validate_profile(profile)
    steps = []
    def add(action, title, reboot=False, observation=0):
        steps.append({'number': len(steps) + 1, 'component': 'configurable', 'action': action,
                      'title': title, 'reboot_after': reboot, 'observation_seconds': observation})
    add('install-disabled', 'Back up and install the configured runtime with fixes disabled', True)
    add('observe-disabled', 'Verify the disabled boot for six stable minutes', observation=360)
    if needs_sports(profile):
        add('preflight', 'Check native Sports bindings without changing them', True)
        add('accept-self-write', 'Accept the preflight boot and test same-value writes', True)
        add('accept-enable', 'Accept the self-write boot and enable all selected settings', True)
    else:
        add('enable', 'Enable exactly the selected temperature and gauge settings', True)
    add('observe-enabled', 'Observe the selected configuration for six stable minutes', observation=360)
    for step in steps:
        step['command'] = f"python install.py configured selection.json --step {step['number']} --live"
    if profile['language'] == 'tr':
        translations = {'Identify the supported unit and preserve existing components': 'Desteklenen üniteyi ve mevcut bileşenleri kontrol et', 'Back up and install the configured runtime with fixes disabled': 'Yedekle ve düzeltmeler kapalıyken yükle', 'Verify the disabled boot for six stable minutes': 'Kapalı durumdaki açılışı altı dakika gözlemle', 'Check native Sports bindings without changing them': 'Yerel Sports bağlantılarını değiştirmeden kontrol et', 'Accept the fresh preflight boot': 'Ön kontrol sonrası yeni açılışı doğrula', 'Test same-value writes of the native bindings': 'Yerel bağlantılara aynı değerle yazmayı test et', 'Accept the native self-write boot': 'Yazma testi sonrası açılışı doğrula', 'Enable exactly the selected temperature and gauge settings': 'Seçilen sıcaklık ve gösterge ayarlarını uygula', 'Accept the selected configuration on a fresh boot': 'Yeni açılışta seçilen yapılandırmayı doğrula', 'Observe the selected configuration for six stable minutes': 'Seçilen yapılandırmayı altı dakika gözlemle'}
        translations.update({'Accept the preflight boot and test same-value writes':'Ön kontrol açılışını doğrula ve aynı değerle yazmayı test et',
                             'Accept the self-write boot and enable all selected settings':'Yazma testi açılışını doğrula ve seçilen tüm ayarları etkinleştir'})
        for row in steps: row['title'] = translations[row['title']]
    return {'profile': profile, 'summary': summary(profile), 'steps': steps,
            'reboots': sum(row['reboot_after'] for row in steps), 'observation_minutes': 12,
            'compatibility': CATALOG['compatibility'], 'new_runtime_live_validated': False,
            'device_assessment': compatibility.assessment(profile['device'], profile['language']),
            'risk_notice': {'version': compatibility.NOTICE_VERSION, 'paragraphs': compatibility.notice_paragraphs(profile['device'], profile['language'])}}

