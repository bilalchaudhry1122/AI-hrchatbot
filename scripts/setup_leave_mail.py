"""Create SMTP + reviewer Emails for leave notices."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ethereal_user():
    body = json.dumps({"requestor": "nodemailer", "version": "7.0.0"}).encode("utf-8")
    errors = []
    for url in ("https://api.nodemailer.com/user", "https://ethereal.email/user"):
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            errors.append(f"{url}: {error}")
            continue
        nested = payload.get("user")
        data = nested if isinstance(nested, dict) else payload
        smtp = data.get("smtp") if isinstance(data.get("smtp"), dict) else {}
        email = data.get("user")
        if isinstance(email, dict):
            email = email.get("user")
        email = str(email or "").strip()
        password = str(data.get("pass") or "")
        host = str(smtp.get("host") or "smtp.ethereal.email").strip()
        port = int(smtp.get("port") or 587)
        if email and password:
            return {"email": email, "password": password, "host": host, "port": port}
        errors.append(f"{url}: unexpected payload keys {list(payload)[:8]}")
    raise RuntimeError("Ethereal did not return a mailbox; " + "; ".join(errors))


def _upsert_env(path: Path, updates: dict):
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    seen = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    missing = [key for key in updates if key not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append("# Leave request email (Ethereal test SMTP; messages are previewed at ethereal.email)")
        for key in missing:
            out.append(f"{key}={updates[key]}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _role_names(person):
    return [line.strip() for line in str(person.get("discordRoles") or "").splitlines() if line.strip()]


def main():
    from app.records.employees import list_employees
    from app.config import load_config
    from app.db.client import create_mysql_client
    from app.hr.departments import DEPARTMENTS, hod_department_from_role_names, normalize_department
    from app.logger import create_logger
    from app.mail.leave import is_email

    config = load_config()
    logger = create_logger("info")
    smtp = _ethereal_user()
    mailbox = smtp["email"]
    boxes = {key: {"email": mailbox} for key in ("BI", "CS", "Marketing", "HR")}
    updates = {
        "SMTP_HOST": smtp["host"],
        "SMTP_PORT": str(smtp["port"]),
        "SMTP_USERNAME": smtp["email"],
        "SMTP_PASSWORD": smtp["password"],
        "SMTP_FROM": smtp["email"],
        "SMTP_STARTTLS": "true",
    }
    _upsert_env(ROOT / ".env", updates)

    client = create_mysql_client(config, logger)
    assigned = []
    if client is not None:
        for person in list_employees(client, logger=logger):
            if not person.get("active") or not person.get("id"):
                continue
            names = _role_names(person)
            hod = hod_department_from_role_names(names)
            if not hod and str(person.get("hrRole") or "") == "HOD":
                hod = normalize_department(person.get("department"))
            is_hr = str(person.get("hrRole") or "") in {"HR", "Admin"} or any(
                line.lower() == "hr" for line in names
            )
            mailbox = None
            if hod in DEPARTMENTS:
                mailbox = boxes[hod]["email"]
            elif is_hr:
                mailbox = boxes["HR"]["email"]
            if not mailbox:
                continue
            current = str(person.get("email") or "").strip()
            if is_email(current):
                assigned.append(person.get("name") or person["id"])
                continue
            client.table("employees").update(person["id"], {"Email": mailbox})
            assigned.append(person.get("name") or person["id"])

    print(f"SMTP enabled via {smtp['host']}")
    print(f"Reviewer Email filled for {len(assigned)} staff rows")
    print("Preview mail at https://ethereal.email using SMTP_USERNAME from .env")


if __name__ == "__main__":
    main()
