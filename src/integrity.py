"""Check distributed code/payload bytes; config.xml is intentionally user-editable."""
from pathlib import Path
import hashlib
import json
from .config import ROOT


def verify(root=ROOT):
    root = Path(root).resolve()
    manifest = json.loads((root / 'src/manifest.json').read_text(encoding='utf-8'))
    if manifest['version'] != '1.0.1':
        raise ValueError('Unknown package version.')
    seen = set()
    for row in manifest['files']:
        name = row['path']
        target = (root / name).resolve()
        if name in seen or name == 'config.xml' or not target.is_relative_to(root):
            raise ValueError('Invalid package manifest.')
        data = target.read_bytes()
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Damaged package file: ' + name)
        seen.add(name)
    required = {'install.py', 'configure.py', 'src/config.py', 'src/backend.py', 'src/wizard.py', 'src/core/tools/configurable/runtime.py'}
    if not required <= seen:
        raise ValueError('Incomplete package.')
    return len(seen)
