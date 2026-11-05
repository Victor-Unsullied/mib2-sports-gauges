"""Small durable records and process locks; no device access."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import uuid


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')


def envelope(value):
    return encode({'sha256': hashlib.sha256(encode(value)).hexdigest(), 'value': value})


def unpack(data):
    record = json.loads(data)
    if not isinstance(record, dict) or set(record) != {'value', 'sha256'} or not isinstance(record['value'], dict) or hashlib.sha256(encode(record['value'])).hexdigest() != record['sha256']:
        raise ValueError('Damaged recovery record')
    return record['value']


def write_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Windows does not expose directory fsync through os.open.
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def save(path, value):
    data = envelope(value)
    write_bytes(path, data)
    write_bytes(Path(str(path) + '.mirror'), data)


def load(path, missing=None):
    path = Path(path)
    records = []
    present = False
    for copy in (path, Path(str(path) + '.mirror')):
        try:
            data = copy.read_bytes()
        except FileNotFoundError:
            continue
        present = True
        try:
            records.append(unpack(data))
        except (ValueError, TypeError, KeyError):
            continue
    if records:
        return max(records, key=lambda record: record.get('revision', 0))
    if present:
        raise ValueError('Both recovery record copies are damaged: ' + str(path))
    return missing


@contextmanager
def lock(path):
    """OS releases this lock after process death; never delete the lock file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Another installer is using this state folder') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
