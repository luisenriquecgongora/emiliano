"""
Where Emiliano keeps secrets for MCP servers (OAuth refresh tokens, pak_ tokens): Windows Credential Manager on
Windows, so they are encrypted for the signed-in user and never sit in a config file; elsewhere a file under
~/.emiliano readable only by the user.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, Optional

_TARGET_PREFIX = "emiliano:mcp:"
_FALLBACK_FILE = Path.home() / ".emiliano" / "mcp-credentials.json"

if sys.platform == "win32":
    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
            ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
        ]

    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168


def _win_write(target: str, secret: bytes) -> None:
    blob = ctypes.create_string_buffer(secret, len(secret))
    cred = _CREDENTIAL()
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.CredentialBlobSize = len(secret)
    cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_char))
    cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "emiliano"
    if not _advapi.CredWriteW(ctypes.byref(cred), 0):
        raise OSError(f"Windows Credential Manager refused to save {target} (error {ctypes.get_last_error()})")


def _win_read(target: str) -> Optional[bytes]:
    pcred = ctypes.POINTER(_CREDENTIAL)()
    if not _advapi.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return None
        raise OSError(f"Windows Credential Manager could not read {target} (error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(pcred.contents.CredentialBlob, pcred.contents.CredentialBlobSize)
    finally:
        _advapi.CredFree(pcred)


def _win_delete(target: str) -> None:
    if not _advapi.CredDeleteW(target, _CRED_TYPE_GENERIC, 0) and ctypes.get_last_error() != _ERROR_NOT_FOUND:
        raise OSError(f"Windows Credential Manager could not delete {target} (error {ctypes.get_last_error()})")


def _file_load() -> Dict[str, Any]:
    try:
        return json.loads(_FALLBACK_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _file_save(data: Dict[str, Any]) -> None:
    _FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FALLBACK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, _FALLBACK_FILE)


def save(server: str, record: Dict[str, Any]) -> None:
    """Stores a server's credential record (e.g. {"kind": "oauth", "refresh_token": ..., "token_endpoint": ...})."""
    if sys.platform == "win32":
        _win_write(_TARGET_PREFIX + server, json.dumps(record).encode("utf-8"))
    else:
        data = _file_load()
        data[server] = record
        _file_save(data)


def load(server: str) -> Optional[Dict[str, Any]]:
    if sys.platform == "win32":
        raw = _win_read(_TARGET_PREFIX + server)
        return json.loads(raw.decode("utf-8")) if raw else None
    return _file_load().get(server)


def delete(server: str) -> None:
    if sys.platform == "win32":
        _win_delete(_TARGET_PREFIX + server)
    else:
        data = _file_load()
        if data.pop(server, None) is not None:
            _file_save(data)
