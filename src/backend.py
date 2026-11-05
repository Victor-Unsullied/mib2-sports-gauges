"""Adapter around the staged native installer. No connection on import."""
from pathlib import Path
import sys
import ipaddress
from .config import ROOT

CORE = Path(__file__).parent / 'core'
for path in (CORE, CORE / 'tools', CORE / 'tools/configurable'):
    sys.path.insert(0, str(path))
import runtime
import selection
import transport


def profile(config, language, accepted=False):
    device = {'train': config['train'], 'mu': config['mu']} if config['train'] else None
    return selection.make_profile(config['options'], language, device, accepted)


def steps(config, language='en'):
    return selection.build_plan(profile(config, language))['steps']


def host_address(host):
    address = ipaddress.IPv4Address(host.strip())
    allowed = any(address in ipaddress.IPv4Network(cidr) for cidr in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    if not allowed or address.is_multicast or address.is_unspecified:
        raise ValueError('Use the local IPv4 address shown by the head unit.')
    return str(address)


def execute(action, config, language, host):
    transport.ADDRESS = host_address(host)
    return runtime.run(action, profile(config, language, True))
