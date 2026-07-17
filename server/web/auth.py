"""Same-origin signed-cookie authentication for the local WebUI deployment."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.identity import AuthenticatedPrincipal


class AuthenticationError(PermissionError):
    pass


class OriginRejectedError(PermissionError):
    pass


class CsrfRejectedError(PermissionError):
    pass


class SessionClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str
    workspace_ids: frozenset[str] = Field(default_factory=lambda: frozenset({"default"}))
    roles: frozenset[str] = Field(default_factory=frozenset)
    csrf_token: str
    issued_at: int
    expires_at: int

    def principal(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            user_id=self.user_id,
            workspace_ids=self.workspace_ids,
            roles=self.roles,
        )


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(raw: str) -> bytes:
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


class SameOriginSessionAuth:
    """Issues stateless HMAC-signed sessions; no credential is placed in a URL."""

    def __init__(
        self,
        *,
        secret: str = "",
        cookie_name: str = "nlp_session",
        ttl_s: int = 86_400,
        secure: bool = False,
        allowed_origins: list[str] | None = None,
    ) -> None:
        self.ephemeral_secret = not bool(secret)
        self._secret = (secret.encode("utf-8") if secret else secrets.token_bytes(32))
        self.cookie_name = cookie_name
        self.ttl_s = min(max(int(ttl_s), 300), 604_800)
        self.secure = secure
        self.allowed_origins = {
            item.rstrip("/").lower() for item in (allowed_origins or []) if item
        }

    @classmethod
    def from_config(cls, config: dict) -> "SameOriginSessionAuth":
        return cls(
            secret=str(config.get("auth_secret", "")),
            cookie_name=str(config.get("cookie_name", "nlp_session")),
            ttl_s=int(config.get("cookie_ttl_s", 86_400)),
            secure=bool(config.get("cookie_secure", False)),
            allowed_origins=list(config.get("allowed_origins", [])),
        )

    def issue(
        self,
        principal: AuthenticatedPrincipal | None = None,
    ) -> tuple[str, SessionClaims]:
        now = int(time.time())
        principal = principal or AuthenticatedPrincipal(
            user_id="local",
            workspace_ids=frozenset({"default"}),
            roles=frozenset({"admin"}),
        )
        claims = SessionClaims(
            user_id=principal.user_id,
            workspace_ids=principal.workspace_ids,
            roles=principal.roles,
            csrf_token=secrets.token_urlsafe(32),
            issued_at=now,
            expires_at=now + self.ttl_s,
        )
        payload = _b64encode(
            json.dumps(
                claims.model_dump(mode="json"),
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        signature = _b64encode(hmac.new(self._secret, payload.encode("ascii"), hashlib.sha256).digest())
        return f"{payload}.{signature}", claims

    def authenticate(self, token: str | None) -> SessionClaims:
        if not token:
            raise AuthenticationError("authentication cookie is missing")
        try:
            payload, supplied_signature = token.split(".", 1)
            expected = _b64encode(
                hmac.new(self._secret, payload.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(supplied_signature, expected):
                raise AuthenticationError("authentication cookie signature is invalid")
            claims = SessionClaims.model_validate_json(_b64decode(payload))
        except AuthenticationError:
            raise
        except (ValueError, UnicodeError, ValidationError) as error:
            raise AuthenticationError("authentication cookie is invalid") from error
        if claims.expires_at <= int(time.time()):
            raise AuthenticationError("authentication cookie has expired")
        return claims

    def require_csrf(self, claims: SessionClaims, supplied: str | None) -> None:
        if not supplied or not hmac.compare_digest(claims.csrf_token, supplied):
            raise CsrfRejectedError("CSRF token is missing or invalid")

    def require_same_origin(self, origin: str | None, host: str | None) -> None:
        if not origin:
            raise OriginRejectedError("Origin header is required")
        normalized = origin.rstrip("/").lower()
        if normalized in self.allowed_origins:
            return
        try:
            origin_host = urlsplit(origin).netloc.lower()
        except ValueError as error:
            raise OriginRejectedError("Origin header is invalid") from error
        if host and origin_host == host.lower():
            return
        raise OriginRejectedError("cross-origin access is not allowed")
