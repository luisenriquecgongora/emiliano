"""
Signing in to MCP servers that use OAuth 2.1 (PlaatoOS), and the tokens Emiliano sends them.

Login (`emiliano connect plaatoos`): the browser opens the server's consent page, the user picks a business and
approves, the page sends a one-time code to Emiliano at http://localhost:3333/callback, and Emiliano exchanges it
(with PKCE, so an intercepted code is useless) for an access token (1 hour) and a refresh token (30 days). Only the
refresh token is stored, in the OS credential store; access tokens are fetched again whenever needed.
"""

from __future__ import annotations

import base64
import hashlib
import html
import secrets
import ssl
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, Optional

from . import credentials
from .client import McpError

# PlaatoOS knows Emiliano as a built-in client with this id and redirect address (api-takient oauth/index.ts)
PLAATOOS = {
    "api": "https://api-takient.onrender.com",
    "mcp_url": "https://api-takient.onrender.com/mcp",
    "client_id": "emiliano",
}
CALLBACK_PORT = 3333
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
LOGIN_TIMEOUT_S = 300
_REFRESH_MARGIN_S = 120  # refresh this long before the access token expires


def _http():
    import httpx
    return httpx.Client(verify=ssl.create_default_context(), timeout=30, follow_redirects=True)


def discover(api_base: str) -> Dict[str, Any]:
    """The server's OAuth metadata (RFC 8414): authorization, token and revocation endpoints."""
    with _http() as client:
        res = client.get(f"{api_base.rstrip('/')}/.well-known/oauth-authorization-server")
    if res.status_code != 200:
        raise McpError(f"{api_base} does not publish OAuth metadata (HTTP {res.status_code}).")
    meta = res.json()
    for key in ("authorization_endpoint", "token_endpoint"):
        if not meta.get(key):
            raise McpError(f"OAuth metadata from {api_base} has no {key}.")
    return meta


def pkce_pair() -> tuple[str, str]:
    """(verifier, S256 challenge) for PKCE."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url(meta: Dict[str, Any], client_id: str, challenge: str, state: str,
                  scope: str = "business:read business:write") -> str:
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI, "scope": scope,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })
    return f"{meta['authorization_endpoint']}?{query}"


_PAGE = """<!doctype html><meta charset="utf-8"><title>Emiliano</title>
<body style="font-family:system-ui;background:#0f172a;color:#e2e8f0;display:grid;place-items:center;height:90vh">
<div style="text-align:center"><h2>{title}</h2><p>{body}</p></div></body>"""


def wait_for_code(expected_state: str, timeout: float = LOGIN_TIMEOUT_S,
                  on_listening: Optional[Callable[[], None]] = None) -> str:
    """Serves http://localhost:3333/callback until the consent page redirects there; returns the code."""
    result: Dict[str, str] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            if params.get("state") != expected_state:
                title, body, ok = "Sign-in failed", "This response does not belong to this sign-in. Try again.", False
                result.setdefault("error", "state mismatch")
            elif params.get("error"):
                title, body, ok = "Sign-in cancelled", html.escape(params.get("error_description") or params["error"]), False
                result.setdefault("error", params.get("error_description") or params["error"])
            elif params.get("code"):
                title, body, ok = "Connected to Emiliano", "You can close this tab and go back to Emiliano.", True
                result["code"] = params["code"]
            else:
                title, body, ok = "Sign-in failed", "No authorization code was received.", False
                result.setdefault("error", "no code")
            page = _PAGE.format(title=title, body=body).encode("utf-8")
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            done.set()

    try:
        server = HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)
    except OSError as e:
        raise McpError(f"Port {CALLBACK_PORT} is busy, so the sign-in cannot receive its answer. "
                       f"Close what uses it and try again ({e}).") from e
    server.timeout = 0.5
    try:
        if on_listening:
            on_listening()
        deadline = time.monotonic() + timeout
        while not done.is_set() and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" in result:
        return result["code"]
    raise McpError(f"Sign-in did not complete: {result.get('error', 'timed out')}.")


def exchange_code(token_endpoint: str, client_id: str, code: str, verifier: str) -> Dict[str, Any]:
    return _token_request(token_endpoint, {"grant_type": "authorization_code", "code": code,
                                           "redirect_uri": REDIRECT_URI, "client_id": client_id,
                                           "code_verifier": verifier})


def _token_request(token_endpoint: str, form: Dict[str, str]) -> Dict[str, Any]:
    with _http() as client:
        res = client.post(token_endpoint, json=form)
    try:
        body = res.json()
    except ValueError:
        body = {}
    if res.status_code != 200 or not body.get("access_token"):
        reason = body.get("error_description") or body.get("error") or f"HTTP {res.status_code}"
        raise McpError(f"The server did not issue a token: {reason}")
    return body


def login(server: str = "plaatoos", api_base: str = PLAATOOS["api"], client_id: str = PLAATOOS["client_id"],
          open_browser: Callable[[str], Any] = webbrowser.open,
          on_url: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Runs the browser sign-in and stores the refresh token; returns the stored record."""
    meta = discover(api_base)
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    url = authorize_url(meta, client_id, challenge, state)

    def start_browser():
        if on_url:
            on_url(url)
        open_browser(url)

    code = wait_for_code(state, on_listening=start_browser)
    tokens = exchange_code(meta["token_endpoint"], client_id, code, verifier)
    record = {
        "kind": "oauth",
        "client_id": client_id,
        "token_endpoint": meta["token_endpoint"],
        "revocation_endpoint": meta.get("revocation_endpoint") or f"{api_base.rstrip('/')}/oauth/revoke",
        "refresh_token": tokens.get("refresh_token", ""),
    }
    if not record["refresh_token"]:
        raise McpError("The server did not issue a refresh token, so the sign-in cannot be kept.")
    credentials.save(server, record)
    return record


def save_static_token(server: str, token: str) -> None:
    """Stores a fixed bearer token (a PlaatoOS pak_ agent token) instead of an OAuth sign-in."""
    credentials.save(server, {"kind": "token", "token": token.strip()})


def logout(server: str) -> bool:
    """Revokes the sign-in on the server (best effort) and forgets it locally. False when nothing was stored."""
    record = credentials.load(server)
    if not record:
        return False
    if record.get("kind") == "oauth" and record.get("refresh_token"):
        try:
            with _http() as client:
                client.post(record["revocation_endpoint"],
                            json={"token": record["refresh_token"], "client_id": record.get("client_id")})
        except Exception:
            pass  # the local copy is removed either way
    credentials.delete(server)
    return True


@dataclass
class TokenProvider:
    """Hands McpHttpClient a valid bearer token for a server, refreshing OAuth access tokens as they expire."""
    server: str
    _access: Optional[str] = None
    _expires_at: float = 0.0

    def _record(self) -> Dict[str, Any]:
        record = credentials.load(self.server)
        if not record:
            raise McpError(f"Not connected to '{self.server}'. Run: emiliano connect {self.server}")
        return record

    def token(self) -> str:
        record = self._record()
        if record.get("kind") == "token":
            return record["token"]
        if self._access and time.time() < self._expires_at - _REFRESH_MARGIN_S:
            return self._access
        return self.refresh(record)

    def refresh(self, record: Optional[Dict[str, Any]] = None) -> str:
        """A fresh access token from the stored refresh token. A static token cannot be refreshed."""
        record = record or self._record()
        if record.get("kind") != "oauth":
            return record["token"]
        try:
            body = _token_request(record["token_endpoint"], {"grant_type": "refresh_token",
                                                              "refresh_token": record["refresh_token"],
                                                              "client_id": record["client_id"]})
        except McpError as e:
            raise McpError(f"The sign-in to '{self.server}' has expired or was revoked ({e}). "
                           f"Run: emiliano connect {self.server}") from e
        self._access = body["access_token"]
        self._expires_at = time.time() + float(body.get("expires_in") or 3600)
        return self._access

    def can_refresh(self) -> bool:
        record = credentials.load(self.server) or {}
        return record.get("kind") == "oauth"
