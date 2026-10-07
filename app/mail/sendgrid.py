"""Send leave notification emails via the SendGrid HTTP API.

Same job as the old Outlook SMTP sender: given a config, recipients, and a
subject/body/html, send one email and return True/False. No other
functionality changes — recipients, dedupe, and the enabled/disabled check
all work exactly as before.
"""

import httpx

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


def send_email(config, *, to_addresses, subject, body, html=None, cc_addresses=None, logger=None):
    mail = (config or {}).get("mail") or {}
    if not mail.get("enabled"):
        if logger:
            logger.info("Leave mail skipped; SendGrid is not configured")
        return False
    recipients = [str(item).strip() for item in (to_addresses or []) if str(item or "").strip()]
    copied = [str(item).strip() for item in (cc_addresses or []) if str(item or "").strip()]
    copied = [item for item in copied if item.lower() not in {addr.lower() for addr in recipients}]
    if not recipients:
        if logger:
            logger.warn("Leave mail skipped; no reviewer emails")
        return False

    sender = str(mail.get("fromAddress") or "").strip()
    from_name = str(mail.get("fromName") or "WebAiry HR").strip() or "WebAiry HR"
    reply_to = str(mail.get("replyTo") or "noreply@webairy.com").strip()

    if mail.get("dryRun"):
        if logger:
            logger.info("Leave mail dry-run; not actually sent", {"to": len(recipients), "subject": subject})
        return True

    personalization = {"to": [{"email": addr} for addr in recipients]}
    if copied:
        personalization["cc"] = [{"email": addr} for addr in copied]
    personalization["subject"] = subject

    content = [{"type": "text/plain", "value": body}]
    if html:
        content.append({"type": "text/html", "value": html})

    payload = {
        "personalizations": [personalization],
        "from": {"email": sender, "name": from_name},
        "reply_to": {"email": reply_to},
        "content": content,
    }
    api_key = str(mail.get("apiKey") or "").strip()
    try:
        response = httpx.post(
            SENDGRID_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30.0,
        )
        if response.status_code >= 300:
            if logger:
                logger.warn("Leave mail failed", {
                    "status": response.status_code,
                    "message": response.text[:240],
                    "to": len(recipients),
                })
            return False
    except Exception as error:
        if logger:
            logger.warn("Leave mail failed", {"message": str(error)[:240], "to": len(recipients)})
        return False
    if logger:
        logger.info("Leave mail sent", {"to": len(recipients), "cc": len(copied), "subject": subject})
    return True
