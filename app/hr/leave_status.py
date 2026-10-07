"""Leave request states and who may act on them.

Every request goes straight to HR (PENDING_HR). HR or Admin approves or
declines; the department HOD is only notified. Balance is deducted when HR
approves. PENDING_MANAGER is kept only so older rows still read correctly.

Rows written before two-step approval existed carry the old PENDING status.
They are treated as waiting for HR so nothing in Airtable has to be migrated.
"""

LEGACY_PENDING = "PENDING"
PENDING_MANAGER = "PENDING_MANAGER"
PENDING_HR = "PENDING_HR"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"

# Anything still awaiting a decision. One of these open per employee at a time.
OPEN_STATUSES = frozenset({LEGACY_PENDING, PENDING_MANAGER, PENDING_HR})
# States where the balance has already been reduced.
DEDUCTED_STATUSES = frozenset({APPROVED})
FINAL_STATUSES = frozenset({APPROVED, REJECTED, CANCELLED})

# Tiers, lowest first. A tier may always act where a lower tier can.
EMPLOYEE = "employee"
MANAGER = "manager"
HR = "hr"
ADMIN = "admin"
TIER_ORDER = (EMPLOYEE, MANAGER, HR, ADMIN)


def normalize(status):
    return str(status or "").strip().upper()


def is_open(status):
    return normalize(status) in OPEN_STATUSES


def is_final(status):
    return normalize(status) in FINAL_STATUSES


def was_deducted(status):
    return normalize(status) in DEDUCTED_STATUSES


def tier_rank(tier):
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


def outranks(tier, other):
    return tier_rank(tier) > tier_rank(other)


def stage_for(status):
    """Which tier is expected to act on this request next."""
    current = normalize(status)
    if current == PENDING_MANAGER:
        return MANAGER
    if current in {PENDING_HR, LEGACY_PENDING}:
        return HR
    return None


def can_act_on(status, tier, *, is_line_manager=False):
    """May this actor approve or reject the request in its current state?

    HOD (manager tier) acts only while the request is waiting for HOD.
    HR acts only after that. Admin may act at either step.
    `is_line_manager` stays on the signature so existing callers do not break.
    """
    del is_line_manager
    current = normalize(status)
    if current == PENDING_MANAGER:
        return tier in {MANAGER, ADMIN}
    if current in {PENDING_HR, LEGACY_PENDING}:
        return tier in {HR, ADMIN}
    return False


def next_status_after_approval(status, tier):
    """HOD approval sends the request to HR. HR/Admin at the HR step finishes it."""
    current = normalize(status)
    if current == PENDING_MANAGER and tier in {MANAGER, ADMIN}:
        return PENDING_HR
    if current in {PENDING_HR, LEGACY_PENDING} and tier in {HR, ADMIN}:
        return APPROVED
    return APPROVED


def display_status(status, locale=None):
    from app.routing.language import pick_locale_text

    current = normalize(status)
    if current == PENDING_MANAGER:
        return pick_locale_text(
            locale,
            english="Waiting for HOD",
            roman="HOD ke paas",
            urdu="HOD کے پاس",
            mix="Waiting for HOD",
        )
    if current in {PENDING_HR, LEGACY_PENDING}:
        return pick_locale_text(
            locale,
            english="Waiting for HR",
            roman="HR ke paas",
            urdu="HR کے پاس",
            mix="Waiting for HR",
        )
    if current == APPROVED:
        return pick_locale_text(
            locale, english="Approved", roman="Approved", urdu="منظور", mix="Approved"
        )
    if current == REJECTED:
        return pick_locale_text(
            locale, english="Rejected", roman="Reject ho gayi", urdu="مسترد", mix="Rejected"
        )
    if current == CANCELLED:
        return pick_locale_text(
            locale, english="Cancelled", roman="Cancel ho gayi", urdu="منسوخ", mix="Cancelled"
        )
    return current.title() or "Unknown"
