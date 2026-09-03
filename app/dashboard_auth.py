from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, Response

from app.config import Settings


@dataclass
class OtpChallenge:
    digest: str
    expires_at: int
    attempts: int = 0


class DashboardAuth:
    cookie_name = "edge_lab_session"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._challenges: dict[str, OtpChallenge] = {}
        self._last_issued_at = 0.0

    def configured(self) -> bool:
        return bool(
            self.settings.dashboard_auth_secret
            and self.settings.dashboard_resend_api_key
            and self.settings.dashboard_auth_from_email
        )

    def _secret(self) -> bytes:
        secret = self.settings.dashboard_auth_secret.strip()
        if not secret:
            raise HTTPException(status_code=503, detail="dashboard authentication unavailable")
        return secret.encode("utf-8")

    def _digest_otp(self, challenge_id: str, code: str) -> str:
        return hmac.new(
            self._secret(),
            f"otp:{challenge_id}:{code}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def issue_otp(self) -> str:
        if not self.configured():
            raise HTTPException(status_code=503, detail="dashboard OTP email is not configured")

        now = time.time()
        with self._lock:
            if now - self._last_issued_at < self.settings.dashboard_otp_cooldown_seconds:
                raise HTTPException(status_code=429, detail="please wait before requesting another code")
            self._last_issued_at = now

        challenge_id = secrets.token_urlsafe(24)
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = int(now + self.settings.dashboard_otp_ttl_seconds)
        digest = self._digest_otp(challenge_id, code)
        with self._lock:
            self._challenges[challenge_id] = OtpChallenge(digest=digest, expires_at=expires_at)
            stale = [key for key, item in self._challenges.items() if item.expires_at < int(now)]
            for key in stale:
                self._challenges.pop(key, None)

        payload = {
            "from": self.settings.dashboard_auth_from_email,
            "to": [self.settings.dashboard_owner_email],
            "subject": "Your Edge Lab sign-in code",
            "text": (
                f"Your Edge Lab sign-in code is {code}.\n\n"
                f"It expires in {self.settings.dashboard_otp_ttl_seconds // 60} minutes. "
                "If you did not request this code, ignore this email."
            ),
        }
        try:
            response = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {self.settings.dashboard_resend_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=10.0,
            )
            response.raise_for_status()
        except Exception as exc:
            with self._lock:
                self._challenges.pop(challenge_id, None)
            raise HTTPException(status_code=503, detail="unable to send sign-in code") from exc

        return challenge_id

    def verify_otp(self, challenge_id: str, code: str) -> str:
        now = int(time.time())
        with self._lock:
            item = self._challenges.get(challenge_id)
            if item is None or item.expires_at < now:
                self._challenges.pop(challenge_id, None)
                raise HTTPException(status_code=401, detail="code expired or invalid")
            item.attempts += 1
            if item.attempts > self.settings.dashboard_otp_max_attempts:
                self._challenges.pop(challenge_id, None)
                raise HTTPException(status_code=401, detail="code expired or invalid")
            expected = item.digest

        if not hmac.compare_digest(expected, self._digest_otp(challenge_id, code.strip())):
            raise HTTPException(status_code=401, detail="code expired or invalid")

        with self._lock:
            self._challenges.pop(challenge_id, None)
        return self.create_session()

    def create_session(self) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "email": self.settings.dashboard_owner_email.lower(),
            "iat": now,
            "exp": now + self.settings.dashboard_session_ttl_seconds,
            "nonce": secrets.token_urlsafe(12),
        }
        encoded = self._b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = self._b64(hmac.new(self._secret(), encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def session_valid(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            encoded, signature = token.split(".", 1)
            expected = self._b64(
                hmac.new(self._secret(), encoded.encode("ascii"), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(signature, expected):
                return False
            payload = json.loads(self._unb64(encoded))
            return (
                str(payload.get("email") or "").lower()
                == self.settings.dashboard_owner_email.lower()
                and int(payload.get("exp") or 0) >= int(time.time())
            )
        except Exception:
            return False

    def set_session_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            self.cookie_name,
            token,
            max_age=self.settings.dashboard_session_ttl_seconds,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(self.cookie_name, path="/", secure=True, httponly=True, samesite="lax")
