"""Save the API credential using the current Windows user's DPAPI protection."""

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
from tempfile import NamedTemporaryFile


class DataBlob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.c_void_p)]


def _protect(data, decrypt=False):
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    local_free = kernel.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    transform = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    transform.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                          wintypes.DWORD, ctypes.POINTER(DataBlob)]
    transform.restype = wintypes.BOOL

    buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.addressof(buffer))
    result = DataBlob()
    try:
        # CRYPTPROTECT_UI_FORBIDDEN, with the default user scope.
        if not transform(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.memset(buffer, 0, ctypes.sizeof(buffer))
        if result.data:
            if decrypt:
                ctypes.memset(result.data, 0, result.size)
            local_free(result.data)


def load_key(path):
    try:
        ciphertext = path.read_bytes()
    except FileNotFoundError:
        return None
    record = json.loads(_protect(ciphertext, decrypt=True))
    if not isinstance(record, dict) or not all(isinstance(record.get(field), str)
                                                and record[field] for field in ('endpoint', 'key')):
        raise ValueError('凭据文件格式无效')
    return record['endpoint'], record['key']


def save_key(path, endpoint, key):
    ciphertext = _protect(json.dumps({'endpoint': endpoint, 'key': key}).encode('utf-8'))
    temporary_path = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix='.api-', suffix='.tmp', delete=False) as temp:
            temporary_path = Path(temp.name)
            temp.write(ciphertext)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
