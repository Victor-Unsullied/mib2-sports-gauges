"""Strict shared XML configuration. Parsing never connects to a head unit."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((Path(__file__).parent / 'core/configurator/catalog.json').read_text(encoding='utf-8'))
DEFAULTS = CATALOG['defaults']
BOOLS = {row['id'] for row in CATALOG['checkboxes']}
ENUMS = {row['id']: [v['value'] for v in row['choices']] for row in CATALOG['dropdowns']}
RANGES = {'power_min', 'power_max', 'torque_min', 'torque_max'}
SUPPORTED = ('MST2_EU_VW_P0635D', '0757')


def validate(config):
    if not isinstance(config, dict) or set(config) != {'language', 'train', 'mu', 'options'}:
        raise ValueError('Invalid config fields.')
    language, train, mu, options = (config[k] for k in ('language', 'train', 'mu', 'options'))
    if language not in ('en', 'tr') or not all(isinstance(v, str) for v in (train, mu)):
        raise ValueError('Invalid language or device versions.')
    train, mu = train.strip().upper(), mu.strip()
    if train and not re.fullmatch(r'[A-Z0-9][A-Z0-9_.-]{2,79}', train):
        raise ValueError('Invalid software train.')
    if mu and not re.fullmatch(r'[0-9]{3,4}', mu):
        raise ValueError('Invalid MU version.')
    if bool(train) != bool(mu):
        raise ValueError('Enter both software train and MU version.')
    if not isinstance(options, dict) or set(options) != set(DEFAULTS):
        raise ValueError('Missing or unknown options.')
    for key in BOOLS:
        if type(options[key]) is not bool:
            raise ValueError('Expected true/false: ' + key)
    for key, allowed in ENUMS.items():
        if options[key] not in allowed:
            raise ValueError('Invalid option: ' + key)
    for kind in ('power', 'torque'):
        lo, hi = options[kind + '_min'], options[kind + '_max']
        if lo is None and hi is None:
            continue
        if type(lo) is not int or type(hi) is not int or not 0 <= lo < hi <= 999:
            raise ValueError('Limits must be whole numbers: 0 <= lower < upper <= 999, or both auto.')
    return {'language': language, 'train': train, 'mu': mu.zfill(4) if mu else '', 'options': dict(options)}


def parse(data):
    if len(data) > 16384:
        raise ValueError('config.xml is too large.')
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('XML entities and document types are not supported.')
    root = ET.fromstring(data)
    if root.tag != 'mib2-sports' or set(root.attrib) != {'version', 'language'} or root.get('version') != '1.0':
        raise ValueError('Expected a v1.0 mib2-sports configuration.')
    if [c.tag for c in root] != ['device', 'options'] or (root.text or '').strip():
        raise ValueError('Expected one device followed by one options element.')
    device, settings = root
    if set(device.attrib) != {'train', 'mu'} or len(device) or (device.text or '').strip() or settings.attrib or (settings.text or '').strip():
        raise ValueError('Invalid device/options element.')
    options = {}
    for item in settings:
        key = item.get('name')
        if item.tag != 'option' or set(item.attrib) != {'name', 'value'} or len(item) or (item.text or '').strip():
            raise ValueError('Invalid option element.')
        if key not in DEFAULTS or key in options:
            raise ValueError('Unknown or duplicate option: ' + str(key))
        value = item.get('value')
        if key in BOOLS:
            if value not in ('true', 'false'):
                raise ValueError('Expected true/false: ' + key)
            value = value == 'true'
        elif key in RANGES:
            if value != 'auto' and not re.fullmatch(r'0|[1-9][0-9]{0,2}', value):
                raise ValueError('Invalid limit: ' + key)
            value = None if value == 'auto' else int(value)
        options[key] = value
    return validate({'language': root.get('language'), 'train': device.get('train'), 'mu': device.get('mu'), 'options': options})


def read(path=ROOT / 'config.xml'):
    return parse(Path(path).read_bytes())


def dumps(config):
    config = validate(config)
    root = ET.Element('mib2-sports', version='1.0', language=config['language'])
    ET.SubElement(root, 'device', train=config['train'], mu=config['mu'])
    settings = ET.SubElement(root, 'options')
    for key in DEFAULTS:
        value = config['options'][key]
        text = 'auto' if value is None else str(value).lower() if type(value) is bool else str(value)
        ET.SubElement(settings, 'option', name=key, value=text)
    ET.indent(root, space='  ')
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding='utf-8', short_empty_elements=True) + b'\n'


def save(config, path=ROOT / 'config.xml'):
    path = Path(path)
    data = dumps(config)
    temp = path.with_name(path.name + '.tmp')
    temp.write_bytes(data)
    temp.replace(path)


def blank():
    return {'language': 'en', 'train': '', 'mu': '', 'options': dict(DEFAULTS)}


def summary(config, language='en'):
    config = validate(config)
    tr = language == 'tr'
    rows = [('Yazılım / MU' if tr else 'Software / MU') + ': ' + (config['train'] or '—') + ' / ' + (config['mu'] or '—')]
    label = lambda item: item.get('label_tr', item['label']) if tr else item['label']
    for item in CATALOG['checkboxes']:
        rows.append(label(item) + ': ' + (('Açık' if tr else 'On') if config['options'][item['id']] else ('Kapalı' if tr else 'Off')))
    for item in CATALOG['dropdowns']:
        choice = next(c for c in item['choices'] if c['value'] == config['options'][item['id']])
        rows.append(label(item) + ': ' + label(choice))
    for kind in ('power', 'torque'):
        lo, hi = (config['options'][kind + '_' + x] for x in ('min', 'max'))
        title = ('Güç' if kind == 'power' else 'Tork') if tr else kind.title()
        rows.append(title + ': ' + ('auto' if lo is None else f'{lo}–{hi}'))
    return rows
