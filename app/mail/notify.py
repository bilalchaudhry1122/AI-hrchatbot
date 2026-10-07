from app.mail.leave import approved_mail_recipients, leave_mail_html, leave_mail_subject, leave_mail_text
from app.mail.sendgrid import send_email


def _mail_card(bot, card, ticket_name=""):
    from app.records.employees import get_employee_by_discord_id
    from app.discord.leave_inbox import polish_reviewer_card
    from app.hr.departments import normalize_department

    mail_card = polish_reviewer_card(
        card,
        client=bot.hr.client,
        logger=bot.logger,
        ticket_name=ticket_name,
    )
    channel_id = (mail_card.get("ticketChannelId") or (card or {}).get("ticketChannelId") or "")
    ticket = bot.store.get_by_channel(channel_id) if channel_id else None
    if ticket is None and (card or {}).get("discordUserId"):
        ticket = bot.store.find_open((card or {}).get("discordUserId")) or bot.store.find_by_user(
            (card or {}).get("discordUserId")
        )
    if ticket:
        mail_card["hodInboxChannelId"] = ticket.get("hodInboxChannelId") or mail_card.get("hodInboxChannelId")
        mail_card["hodApprovedId"] = ticket.get("hodApprovedId") or mail_card.get("hodApprovedId")
        mail_card["hodApprovedName"] = ticket.get("hodApprovedName") or mail_card.get("hodApprovedName")
        mail_card["hodApprovedBy"] = ticket.get("hodApprovedBy") or mail_card.get("hodApprovedBy")
        if not str(mail_card.get("managerApprovedBy") or "").strip():
            mail_card["managerApprovedBy"] = ticket.get("hodApprovedBy") or ticket.get("hodApprovedName") or ""
        if not str(mail_card.get("ticketName") or "").strip():
            mail_card["ticketName"] = ticket.get("channelName") or ticket_name or ""
        if not str(mail_card.get("ticketChannelId") or "").strip():
            mail_card["ticketChannelId"] = ticket.get("channelId") or channel_id
    if not normalize_department(mail_card.get("department")) and (card or {}).get("discordUserId"):
        try:
            person = get_employee_by_discord_id(
                bot.hr.client, (card or {}).get("discordUserId"), logger=bot.logger
            )
            if person:
                mail_card["department"] = normalize_department(person.get("department")) or mail_card.get("department")
        except Exception:
            pass
    return mail_card


async def _send_leave_mail(bot, card, *, outcome="approved", exclude_email="", ticket_name=""):
    if bot.hr is None or bot.hr.client is None:
        return False
    import asyncio

    del exclude_email
    company = str((bot.config or {}).get("companyName") or "WebAiry")

    def send():
        mail_card = _mail_card(bot, card, ticket_name)
        to_addresses, cc_addresses = approved_mail_recipients(
            bot.hr.client,
            bot.config,
            mail_card,
            logger=bot.logger,
            outcome=outcome,
        )
        return send_email(
            bot.config,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            subject=leave_mail_subject(mail_card, outcome=outcome),
            body=leave_mail_text(mail_card, company=company, outcome=outcome),
            html=leave_mail_html(mail_card, company=company, outcome=outcome),
            logger=bot.logger,
        )

    try:
        return await asyncio.to_thread(send)
    except Exception as error:
        bot.logger.warn("Leave mail failed", {"message": str(error)[:200]})
        return False


async def notify_leave_approved_mail(bot, card, *, exclude_email="", ticket_name=""):
    """Email HR after HOD and HR have both approved. Cc the approving HOD."""
    return await _send_leave_mail(
        bot, card, outcome="approved", exclude_email=exclude_email, ticket_name=ticket_name
    )


async def notify_leave_cancelled_mail(bot, card, *, exclude_email="", ticket_name=""):
    """Email HR after an approved leave is cancelled. Cc the HOD who approved it."""
    return await _send_leave_mail(
        bot, card, outcome="cancelled", exclude_email=exclude_email, ticket_name=ticket_name
    )
