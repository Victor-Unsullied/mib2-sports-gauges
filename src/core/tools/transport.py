"""Read-only inspection and local backups of a directly attached Delphi MIB2."""
import argparse
import ftplib
import hashlib
import io
import json
import re
import select
import socket
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

# Set by the guided installer after the user reads the address from GEM.
ADDRESS = None
FTP_USER = FTP_PASSWORD = TELNET_USER = TELNET_PASSWORD = None

class Telnet:
    def __init__(self):
        self.sock = socket.create_connection((ADDRESS, 23), timeout=10)
        self.state = self.verb = 0
        self.sock.settimeout(10)
        banner = self.read(1.5)
        if 'login:' not in banner.lower():
            self.send('')
            banner += self.read(3)
        if 'login:' not in banner.lower():
            raise RuntimeError('No Telnet login prompt: ' + repr(banner))
        if not TELNET_USER:
            raise ValueError('Enter the service login in install.py first.')
        self.send(TELNET_USER)
        response = self.read(2)
        if 'password:' in response.lower():
            if TELNET_PASSWORD is None:
                raise ValueError('Telnet service password is required.')
            self.send(TELNET_PASSWORD)
            response = self.read(2)
        if not re.search(r'(?m)#\s*$', response):
            raise RuntimeError('Telnet service login was not accepted.')
        self.login = banner + response

    def send(self, command):
        self.sock.sendall(command.encode('ascii') + b'\r\n')

    def read(self, seconds):
        deadline = time.monotonic() + seconds
        result = bytearray()
        while time.monotonic() < deadline:
            if not select.select([self.sock], [], [], min(.1, max(0, deadline-time.monotonic())))[0]:
                continue
            data = self.sock.recv(65536)
            if not data:
                break
            for b in data:
                if self.state == 0:
                    if b == 255:
                        self.state = 1
                    else:
                        result.append(b)
                elif self.state == 1:
                    if b == 255:
                        result.append(b)
                        self.state = 0
                    elif b in (251,252,253,254):
                        self.verb, self.state = b, 2
                    elif b == 250:
                        self.state = 3
                    else:
                        self.state = 0
                elif self.state == 2:
                    if self.verb == 251:
                        self.sock.sendall(bytes([255,254,b]))
                    elif self.verb == 253:
                        self.sock.sendall(bytes([255,252,b]))
                    self.state = 0
                elif self.state == 3 and b == 255:
                    self.state = 4
                elif self.state == 4:
                    self.state = 0 if b == 240 else 3
        return result.decode('latin1').replace('\r\x00','').replace('\r','')

    def run(self, command, timeout=30):
        marker = '__MIB2_DONE_' + str(time.time_ns()) + '__'
        separator = ' ' if command.rstrip().endswith('&') else '; '
        self.send(command + separator + "echo '" + marker + "'")
        result = ''
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result += self.read(.3)
            if re.search(r'(?m)^' + re.escape(marker) + r'\s*$', result):
                return result
        raise TimeoutError('Command timeout: ' + command + '\n' + result[-3000:])

    def close(self):
        try:
            self.send('exit')
        except OSError:
            pass
        finally:
            self.sock.close()

def ftp_connect():
    ftp = ftplib.FTP()
    ftp.connect(ADDRESS, 21, timeout=15)
    if not FTP_USER or FTP_PASSWORD is None:
        raise ValueError('Enter the service login in install.py first.')
    try:
        ftp.login(FTP_USER, FTP_PASSWORD)
    except ftplib.error_perm:
        ftp.close()
        raise RuntimeError('FTP service login was not accepted.') from None
    ftp.set_pasv(True)
    return ftp

