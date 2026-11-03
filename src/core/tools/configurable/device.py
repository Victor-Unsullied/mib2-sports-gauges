from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import ftplib,hashlib,re
from transport import Telnet, ftp_connect
ACTIVE="/extbin/apps/hmi/HMI/jar/TestInterface-H28.28.197.jar"

class NativeRebootRejected(RuntimeError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(test, message):
    if not test:
        raise ValueError(message)


def fetch(ftp, path, optional=False):
    data = bytearray()
    try:
        ftp.retrbinary('RETR ' + path, data.extend)
    except ftplib.error_perm as problem:
        if optional and str(problem).startswith('550 ') and 'No such file' in str(problem):
            return None
        raise
    return bytes(data)


def shell(telnet, command, timeout=15):
    result = telnet.run(command + '; echo GOLF_TEMP_RC:$?', timeout=timeout)
    require(re.findall(r'(?m)^GOLF_TEMP_RC:(\d+)\s*$', result) == ['0'], 'Native command failed: ' + result)
    return result


def metadata(telnet, path):
    result = shell(telnet, '/proc/boot/ls -ln ' + path)
    lines = [line.split() for line in result.splitlines() if line.startswith('-')]
    require(len(lines) == 1, 'Ambiguous file metadata: ' + result)
    row = lines[0]
    require(row[0] == '-rwxrwxrwx' and row[2:4] == ['0', '0'], 'Expected preserved0777 root/root metadata: ' + result)
    return {'mode': '0777', 'uid': 0, 'gid': 0, 'bytes': int(row[4])}


def normal_reboot(telnet, record):
    record('normal_native_reboot_request_sending')
    telnet.send('/ffs/sbin/sync && /extbin/apps/usr/bin/shutdown -S reboot -q; reboot_rc=$?; echo GOLF_TEMP_REBOOT_RC:$reboot_rc')
    # Keep the console alive; immediate disconnect previously interrupted reboot.
    try:
        response = telnet.read(4)
        codes = re.findall(r'(?m)^GOLF_TEMP_REBOOT_RC:(\d+)\s*$', response)
        if codes and codes[-1] != '0':
            raise NativeRebootRejected('Native reboot returned failure: ' + response)
        record('normal_native_reboot_requested', console_response=response)
    except OSError as problem:
        record('normal_native_reboot_console_closed', detail=str(problem))

