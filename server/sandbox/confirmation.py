"""Short-lived, user-bound confirmation credentials for high-risk tools."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from datetime import timedelta


class SandboxConfirmationSigner:
    def __init__(self, secret: str, *, lifetime: timedelta = timedelta(minutes=2)) -> None:
        if not secret:
            raise ValueError("Sandbox confirmation signing requires a secret")
        self._secret = secret.encode("utf-8")
        self._lifetime = lifetime

    def issue(self, *, user_id: str, session_id: str, tool_name: str, code_hash: str) -> str:
        payload = json.dumps(
            {
                "u": user_id,
                "s": session_id,
                "t": tool_name,
                "c": code_hash,
                "e": int(time.time() + self._lifetime.total_seconds()),
                "n": hashlib.sha256(f"{time.time_ns()}:{user_id}".encode()).hexdigest()[:24],
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
        signature = hmac.new(self._secret, encoded, hashlib.sha256).hexdigest()
        return f"{encoded.decode('ascii')}.{signature}"

    def verify(
        self,
        token: str,
        *,
        user_id: str,
        session_id: str,
        tool_name: str,
        code_hash: str,
    ) -> None:
        try:
            encoded, signature = token.split(".", maxsplit=1)
            expected = hmac.new(self._secret, encoded.encode("ascii"), hashlib.sha256).hexdigest()
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        except (binascii.Error, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise PermissionError("invalid sandbox confirmation token") from error
        if not isinstance(payload, dict) or not hmac.compare_digest(signature, expected):
            raise PermissionError("invalid sandbox confirmation token")
        if (
            payload.get("u") != user_id
            or payload.get("s") != session_id
            or payload.get("t") != tool_name
            or payload.get("c") != code_hash
        ):
            raise PermissionError("sandbox confirmation token does not match the requested operation")
        if not isinstance(payload.get("e"), int) or payload["e"] < time.time():
            raise PermissionError("sandbox confirmation token expired")
