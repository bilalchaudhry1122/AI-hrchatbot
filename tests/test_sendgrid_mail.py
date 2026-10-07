"""SendGrid mail transport: recipients, dedupe, dry-run, and API call shape."""

import httpx

from app.mail.sendgrid import SENDGRID_URL, send_email


def _config(**overrides):
    mail = {
        "enabled": True,
        "apiKey": "SG.test-key",
        "fromAddress": "noreply@webairy.com",
        "fromName": "WebAiry HR",
        "replyTo": "noreply@webairy.com",
        "dryRun": False,
    }
    mail.update(overrides)
    return {"mail": mail}


def test_send_email_skips_when_mail_disabled():
    config = _config(enabled=False)
    assert send_email(config, to_addresses=["hr@example.com"], subject="s", body="b") is False


def test_send_email_skips_when_no_recipients():
    config = _config()
    assert send_email(config, to_addresses=[], subject="s", body="b") is False


def test_send_email_dry_run_does_not_call_sendgrid(monkeypatch):
    called = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: called.append(1))
    config = _config(dryRun=True)
    result = send_email(config, to_addresses=["hr@example.com"], subject="s", body="b")
    assert result is True
    assert called == []


def test_send_email_posts_to_sendgrid_with_expected_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 202
        text = ""

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(httpx, "post", fake_post)
    config = _config()
    result = send_email(
        config,
        to_addresses=["hr@example.com", "hr@example.com"],
        cc_addresses=["hod@example.com", "hr@example.com"],
        subject="Leave approved",
        body="plain body",
        html="<p>html body</p>",
    )
    assert result is True
    assert captured["url"] == SENDGRID_URL
    assert captured["headers"]["Authorization"] == "Bearer SG.test-key"
    personalization = captured["json"]["personalizations"][0]
    assert personalization["to"] == [{"email": "hr@example.com"}, {"email": "hr@example.com"}]
    # The applicant's own address is dropped from Cc when it also appears in To.
    assert personalization["cc"] == [{"email": "hod@example.com"}]
    assert personalization["subject"] == "Leave approved"
    assert captured["json"]["from"] == {"email": "noreply@webairy.com", "name": "WebAiry HR"}
    assert {"type": "text/plain", "value": "plain body"} in captured["json"]["content"]
    assert {"type": "text/html", "value": "<p>html body</p>"} in captured["json"]["content"]


def test_send_email_returns_false_on_sendgrid_error(monkeypatch):
    class FakeResponse:
        status_code = 401
        text = "Unauthorized"

    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResponse())
    config = _config()
    result = send_email(config, to_addresses=["hr@example.com"], subject="s", body="b")
    assert result is False


def test_send_email_returns_false_on_network_error(monkeypatch):
    def fake_post(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "post", fake_post)
    config = _config()
    result = send_email(config, to_addresses=["hr@example.com"], subject="s", body="b")
    assert result is False
