import json
import os
from pathlib import Path

from dotenv import load_dotenv

from app.console import ensure_utf8_console

# Imported by main and by every script, and it prints before any logger
# exists, so this is the earliest common place to make output safe.
ensure_utf8_console()

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

USER_ERROR = "Sorry, I ran into a problem answering that. Please try again in a moment."
FALLBACK_ANSWER = (
    "I look after HR matters here: company policy, your leave, and anything you "
    "need from the HR team. Could you ask me about one of those?"
)


def required(name):
    value = (os.getenv(name) or "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def optional(name, fallback=""):
    value = os.getenv(name)
    if value is None or value == "":
        return fallback
    return value.strip()


def parse_number(name, fallback):
    raw = optional(name, str(fallback))
    try:
        return float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number, received: {raw}") from error


def parse_boolean(name, fallback=False):
    raw = optional(name, "true" if fallback else "false").lower()
    return raw in {"1", "true", "yes"}


def parse_database_url(url):
    """Parse mysql://user:pass@host:port/db into a settings dict."""
    from urllib.parse import unquote, urlparse

    text = str(url or "").strip().strip('"').strip("'")
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError("DATABASE_URL must start with mysql://")
    database = (parsed.path or "").lstrip("/").split("/")[0]
    if not database:
        raise ValueError("DATABASE_URL is missing the database name")
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": int(parsed.port or 3306),
        "user": unquote(parsed.username or "root"),
        "password": unquote(parsed.password or ""),
        "name": database,
    }


def load_channel_map():
    from_env = optional("DISCORD_CHANNEL_NAMESPACES", "")
    file_path = ROOT_DIR / "channels.json"
    parsed = {"channels": {}, "respondMode": optional("DISCORD_RESPOND_MODE", "all")}

    if file_path.exists():
        parsed = json.loads(file_path.read_text(encoding="utf-8"))
    elif from_env:
        parsed["channels"] = json.loads(from_env)

    channels = {}
    for channel_id, namespace in (parsed.get("channels") or {}).items():
        cid = str(channel_id).strip()
        ns = str(namespace).strip().lower()
        if not cid or "PASTE_" in cid or "CHANNEL_ID" in cid or not ns:
            continue
        channels[cid] = ns

    respond_mode = str(parsed.get("respondMode") or optional("DISCORD_RESPOND_MODE", "all")).strip().lower()
    if respond_mode not in {"all", "mention", "slash", "command"}:
        raise ValueError('DISCORD_RESPOND_MODE / respondMode must be "all", "mention", or "slash"')

    tickets = parsed.get("tickets") or {}
    ticket_category_id = str(tickets.get("categoryId") or optional("TICKET_CATEGORY_ID", "")).strip()
    ticket_admin_role_id = str(tickets.get("adminRoleId") or optional("TICKET_ADMIN_ROLE_ID", "")).strip()
    ticket_staff_role_id = str(tickets.get("staffRoleId") or optional("TICKET_STAFF_ROLE_ID", "")).strip()
    leave_review_channel_id = str(
        tickets.get("leaveReviewChannelId") or optional("LEAVE_REVIEW_CHANNEL_ID", "")
    ).strip()
    leave_category_id = str(tickets.get("leaveCategoryId") or optional("LEAVE_CATEGORY_ID", "")).strip()
    hr_category_id = str(tickets.get("hrCategoryId") or optional("HR_CATEGORY_ID", "")).strip()
    hod_category_id = str(tickets.get("hodCategoryId") or optional("HOD_CATEGORY_ID", "")).strip()
    onboarding_channel_id = str(
        tickets.get("onboardingChannelId") or optional("ONBOARDING_CHANNEL_ID", "")
    ).strip()
    announcement_channel_id = str(
        tickets.get("announcementChannelId") or optional("ANNOUNCEMENT_CHANNEL_ID", "")
    ).strip()
    hr_profile_channel_id = str(
        tickets.get("hrProfileChannelId") or optional("HR_PROFILE_CHANNEL_ID", "")
    ).strip()
    hr_announcement_channel_id = str(
        tickets.get("hrAnnouncementChannelId") or optional("HR_ANNOUNCEMENT_CHANNEL_ID", "")
    ).strip()
    hod_channels_raw = tickets.get("hodChannels") or {}
    hod_role_ids_raw = tickets.get("hodRoleIds") or {}
    hod_channels = {}
    hod_role_ids = {}
    for key in ("bi", "cs", "marketing"):
        label = {"bi": "BI", "cs": "CS", "marketing": "Marketing"}[key]
        cid = str(hod_channels_raw.get(key) or hod_channels_raw.get(label) or "").strip()
        rid = str(hod_role_ids_raw.get(key) or hod_role_ids_raw.get(label) or "").strip()
        if cid.isdigit():
            hod_channels[label] = cid
        if rid and "PASTE_" not in rid:
            hod_role_ids[label] = rid
    clean_admin = "" if not ticket_admin_role_id or "PASTE_" in ticket_admin_role_id else ticket_admin_role_id
    clean_category = "" if not ticket_category_id or "PASTE_" in ticket_category_id else ticket_category_id
    clean_staff = "" if not ticket_staff_role_id or "PASTE_" in ticket_staff_role_id else ticket_staff_role_id
    clean_review = "" if not leave_review_channel_id or "PASTE_" in leave_review_channel_id else leave_review_channel_id
    clean_leave_category = "" if not leave_category_id or "PASTE_" in leave_category_id else leave_category_id
    clean_hr_category = "" if not hr_category_id or "PASTE_" in hr_category_id else hr_category_id
    clean_hod_category = "" if not hod_category_id or "PASTE_" in hod_category_id else hod_category_id
    clean_onboarding_channel = (
        "" if not onboarding_channel_id or "PASTE_" in onboarding_channel_id else onboarding_channel_id
    )
    clean_announcement_channel = (
        "" if not announcement_channel_id or "PASTE_" in announcement_channel_id else announcement_channel_id
    )
    clean_hr_profile_channel = (
        "" if not hr_profile_channel_id or "PASTE_" in hr_profile_channel_id else hr_profile_channel_id
    )
    clean_hr_announcement_channel = (
        ""
        if not hr_announcement_channel_id or "PASTE_" in hr_announcement_channel_id
        else hr_announcement_channel_id
    )
    enabled_default = tickets.get("enabled")
    if enabled_default is None:
        enabled_default = bool(clean_category or clean_staff)
    tickets_enabled = parse_boolean("TICKET_MODE", bool(enabled_default))

    return {
        "channels": channels,
        "respondMode": respond_mode,
        "tickets": {
            "enabled": tickets_enabled,
            "categoryId": clean_category,
            "staffRoleId": clean_staff,
            "adminRoleId": clean_admin,
            "leaveReviewChannelId": clean_review,
            "leaveCategoryId": clean_hr_category or clean_leave_category,
            "hrCategoryId": clean_hr_category,
            "hodCategoryId": clean_hod_category,
            "hodChannels": hod_channels,
            "hodRoleIds": hod_role_ids,
            "onboardingChannelId": clean_onboarding_channel,
            "announcementChannelId": clean_announcement_channel,
            "hrProfileChannelId": clean_hr_profile_channel,
            "hrAnnouncementChannelId": clean_hr_announcement_channel,
        },
    }


def load_config():
    echo_mode = parse_boolean("ECHO_MODE", False)
    channel_map = load_channel_map()
    config = {
        "rootDir": ROOT_DIR,
        "echoMode": echo_mode,
        "logLevel": optional("LOG_LEVEL", "debug").lower(),
        # The employer's name, used in replies. The Discord server may be
        # called something else entirely, so never infer it from the guild.
        "companyName": optional("COMPANY_NAME", "WebAiry"),
        "assistantName": optional("ASSISTANT_NAME", "HR Assistant"),
        "discord": {
            "token": required("DISCORD_TOKEN"),
            "clientId": optional("DISCORD_CLIENT_ID", ""),
            "respondMode": channel_map["respondMode"],
            "channels": channel_map["channels"],
            "tickets": channel_map["tickets"],
        },
        "pinecone": {
            "apiKey": optional("PINECONE_API_KEY", "") if echo_mode else required("PINECONE_API_KEY"),
            "indexName": optional("PINECONE_INDEX_NAME", "document"),
            "topK": int(parse_number("PINECONE_TOP_K", 5)),
        },
        "answer": {
            "provider": (optional("ANSWER_PROVIDER", "openrouter") or "openrouter").strip().lower(),
            "rateLimitCooldownMs": 2 * 60 * 1000,
        },
        "gemini": {
            "apiKey": optional("GEMINI_API_KEY", "") if echo_mode else required("GEMINI_API_KEY"),
            "embeddingModel": optional("GEMINI_EMBEDDING_MODEL", "gemini-embedding-2"),
            "embeddingTaskType": optional("GEMINI_EMBEDDING_TASK_TYPE", "RETRIEVAL_QUERY"),
            "answerModel": optional("GEMINI_ANSWER_MODEL", "gemini-3.5-flash"),
        },
        "openrouter": {
            "apiKey": "",
            # Tried in order after OPENROUTER_API_KEY fails, before Gemini.
            "fallbackApiKeys": [
                key.strip()
                for key in optional("OPENROUTER_FALLBACK_API_KEYS", "").split(",")
                if key.strip()
            ],
            "answerModel": optional("OPENROUTER_ANSWER_MODEL", "google/gemma-4-31b-it"),
        },
        "rag": {
            "relevanceThreshold": parse_number("RELEVANCE_THRESHOLD", 0.45),
        },
        "hr": {
            "hrRoleId": optional("HR_ROLE_ID", ""),
            # Admin sits above HR: can override any HR decision.
            "adminRoleId": optional("HR_ADMIN_ROLE_ID", ""),
            # Optional blanket manager role. Line managers are resolved from the
            # Manager field on the employee record and do not need this.
            "managerRoleId": optional("MANAGER_ROLE_ID", ""),
            "twoStepApproval": parse_boolean("LEAVE_TWO_STEP_APPROVAL", True),
            "whoamiEnabled": parse_boolean("HR_WHOAMI_ENABLED", False),
        },
        "db": {
            "backend": "mysql",
            "url": optional("DATABASE_URL", ""),
            "host": optional("MYSQL_HOST", "127.0.0.1"),
            "port": int(parse_number("MYSQL_PORT", 3306)),
            "user": optional("MYSQL_USER", "root"),
            "password": optional("MYSQL_PASSWORD", ""),
            "name": optional("MYSQL_DATABASE", "hr"),
        },
        "messages": {
            "userError": USER_ERROR,
            "fallback": FALLBACK_ANSWER,
        },
        "mail": {
            # Leave notification emails go out via the SendGrid HTTP API.
            "apiKey": optional("SENDGRID_API_KEY", ""),
            "fromAddress": optional("EMAIL_FROM_ADDRESS", ""),
            "fromName": optional("EMAIL_FROM_NAME", "WebAiry HR"),
            "replyTo": optional("EMAIL_FROM_ADDRESS", ""),
            "dryRun": parse_boolean("DRY_RUN", False),
            # HR_LEAVE_TO replaces the old LEAVE_MAIL_HR; the older name still
            # works if HR_LEAVE_TO is not set.
            "hr": optional("HR_LEAVE_TO", "") or optional("LEAVE_MAIL_HR", ""),
        },
    }

    task = str(config["gemini"]["embeddingTaskType"] or "").strip()
    if task.lower() in {"", "none", "off"}:
        config["gemini"]["embeddingTaskType"] = ""

    if config["answer"]["provider"] not in {"openrouter", "gemini"}:
        raise ValueError('ANSWER_PROVIDER must be "openrouter" or "gemini"')

    if not echo_mode and config["answer"]["provider"] == "openrouter":
        config["openrouter"]["apiKey"] = required("OPENROUTER_API_KEY")

    hr = config["hr"]
    # Admin above HR defaults to the ticket Admin role when not set separately.
    if not hr["adminRoleId"]:
        hr["adminRoleId"] = config["discord"]["tickets"]["adminRoleId"]

    db = config["db"]
    if db.get("url"):
        db.update(parse_database_url(db["url"]))
    db["backend"] = "mysql"
    db["enabled"] = bool(db.get("name") and db.get("user") is not None)

    mail = config["mail"]
    if not mail["fromAddress"]:
        mail["fromAddress"] = "noreply@webairy.com"
    if not mail["replyTo"]:
        mail["replyTo"] = "noreply@webairy.com"
    mail["enabled"] = bool(mail["apiKey"] and mail["fromAddress"])
    if not echo_mode and not db["enabled"]:
        print("[config] MySQL is not configured. Set DATABASE_URL (or MYSQL_*). Live HR data will be unavailable.")

    if not echo_mode and not config["discord"]["channels"]:
        print(
            "[config] No Discord channel -> namespace mappings found. "
            "Copy channels.example.json to channels.json and add real channel IDs."
        )

    return config
