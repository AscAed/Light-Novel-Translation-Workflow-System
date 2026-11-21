"""Minimal Windows Credential Manager adapter for generic credentials."""

import ctypes
import os
from ctypes import wintypes


class CredentialStoreError(RuntimeError):
    pass


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _api():
    if os.name != "nt":
        raise CredentialStoreError("持久化凭据需要 Windows Credential Manager。")
    api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def write_secret(target, secret):
    encoded = secret.encode("utf-8")
    if not encoded or len(encoded) > 2560:
        raise CredentialStoreError("Key 为空或超过凭据存储支持的长度。")
    data = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = _Credential()
    credential.Type = 1
    credential.TargetName = target
    credential.CredentialBlobSize = len(encoded)
    credential.CredentialBlob = data
    credential.Persist = 2
    credential.UserName = "TranslatorAI"
    if not _api().CredWriteW(ctypes.byref(credential), 0):
        raise CredentialStoreError(f"Windows 凭据写入失败（错误码 {ctypes.get_last_error()}）。")


def read_secret(target):
    api = _api()
    result = ctypes.POINTER(_Credential)()
    if not api.CredReadW(target, 1, 0, ctypes.byref(result)):
        raise CredentialStoreError(f"Windows 凭据读取失败（错误码 {ctypes.get_last_error()}）。")
    try:
        credential = result.contents
        return ctypes.string_at(
            credential.CredentialBlob, credential.CredentialBlobSize
        ).decode("utf-8")
    finally:
        api.CredFree(result)


def delete_secret(target):
    api = _api()
    if not api.CredDeleteW(target, 1, 0):
        error = ctypes.get_last_error()
        if error != 1168:
            raise CredentialStoreError(f"Windows 凭据删除失败（错误码 {error}）。")
