from app.config import Settings
from app.dashboard_auth import DashboardAuth


class _OkResponse:
    def raise_for_status(self):
        return None


def _settings() -> Settings:
    return Settings(
        dashboard_owner_email="fafikennedy20@gmail.com",
        dashboard_auth_secret="unit-test-session-placeholder",
        dashboard_resend_api_key="unit-test-resend-placeholder",
        dashboard_auth_from_email="edge-lab@example.com",
        dashboard_otp_ttl_seconds=600,
        dashboard_otp_cooldown_seconds=0,
        dashboard_otp_max_attempts=5,
        dashboard_session_ttl_seconds=3600,
    )


def test_otp_is_emailed_but_only_digest_is_retained(monkeypatch):
    sent = {}

    def fake_post(url, *, headers, json, timeout):
        sent["url"] = url
        sent["headers"] = headers
        sent["json"] = json
        sent["timeout"] = timeout
        return _OkResponse()

    monkeypatch.setattr("app.dashboard_auth.httpx.post", fake_post)
    monkeypatch.setattr("app.dashboard_auth.secrets.randbelow", lambda _: 123456)
    auth = DashboardAuth(_settings())

    challenge = auth.issue_otp()

    assert sent["url"] == "https://api.resend.com/emails"
    assert sent["json"]["to"] == ["fafikennedy20@gmail.com"]
    assert "123456" in sent["json"]["text"]
    assert auth._challenges[challenge].digest != "123456"
    assert "123456" not in repr(auth._challenges[challenge])


def test_valid_code_creates_signed_owner_session(monkeypatch):
    monkeypatch.setattr("app.dashboard_auth.httpx.post", lambda *args, **kwargs: _OkResponse())
    monkeypatch.setattr("app.dashboard_auth.secrets.randbelow", lambda _: 654321)
    auth = DashboardAuth(_settings())

    challenge = auth.issue_otp()
    token = auth.verify_otp(challenge, "654321")

    assert challenge not in auth._challenges
    assert auth.session_valid(token) is True
    assert auth.session_valid(token + "tampered") is False


def test_wrong_code_is_bounded_and_never_creates_session(monkeypatch):
    settings = _settings()
    settings.dashboard_otp_max_attempts = 2
    monkeypatch.setattr("app.dashboard_auth.httpx.post", lambda *args, **kwargs: _OkResponse())
    monkeypatch.setattr("app.dashboard_auth.secrets.randbelow", lambda _: 111111)
    auth = DashboardAuth(settings)
    challenge = auth.issue_otp()

    for _ in range(2):
        try:
            auth.verify_otp(challenge, "222222")
        except Exception:
            pass

    try:
        auth.verify_otp(challenge, "111111")
    except Exception:
        pass

    assert challenge not in auth._challenges


def test_auth_requires_separate_email_and_session_secrets():
    settings = _settings()
    settings.dashboard_resend_api_key = ""
    auth = DashboardAuth(settings)
    assert auth.configured() is False
