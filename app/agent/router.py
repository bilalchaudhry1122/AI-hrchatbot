import re
from datetime import date, timedelta

from app.agent.draft_store import create_draft_store
from app.agent.extraction import infer_leave_reason, infer_leave_type
from app.hr.dates import resolve_date_phrase, resolve_date_range
from app.hr.workdays import normalize_half_day, weekend_day_answer
from app.agent.verification import (
    is_cancel_submit,
    is_cancel_approved_leave,
    is_confirm_submit,
    is_asset_conduct_policy_question,
    is_company_leave_allowance_question,
    is_company_leave_policy_question,
    is_explicit_leave_apply,
    is_new_leave_start,
    is_policy_conversation_followup,
    is_quota_or_status_question,
    is_withdraw_leave,
    is_refuse_withdraw,
    is_bare_deny,
    is_bare_affirm,
    looks_like_leave_form_reply,
    should_cancel_leave_form,
    should_confirm_leave_form,
)
from app.agent.tools import get_my_attendance, get_my_leave_balance, prepare_leave_request, search_hr_policy
from app.discord.messages import format_support_reply
from app.errors import AppError, ErrorCodes
from app.generation.context_window import history_for_intent, history_for_llm, ticket_notes
from app.routing.data_source import source_for_intent
from app.routing.intent import classify_hr_intent, classify_hr_route, classify_social, is_about_bot, is_conversation_continue
from app.routing.questions import split_user_questions
from app.routing.scope import is_profile_pii_request, off_topic_kind, profile_privacy_reply, redirect_reply
from app.routing.language import detect_reply_language, pick_locale_text
from app.routing.webairy import CLARIFY_QUESTION, CLARIFY_QUESTION_ROMAN
from app.sessions.followup import (
    is_expand_followup,
    is_format_followup,
    is_repeat_followup,
    is_session_followup,
    last_knowledge_question,
)
from app.sessions.store import merge_histories


MISSING_LEAVE = (
    "I can submit a leave request only after you clearly apply and give both the leave type and the date. "
    "Example: I want to apply for sick leave tomorrow."
)
MISSING_LEAVE_ROMAN = (
    "Leave request tabhi submit hogi jab aap clearly apply karein aur leave type aur date dono dein. "
    "Example: mujhe kal sick leave chahiye / I want to apply for sick leave tomorrow."
)
CONFIRM_LEAVE = (
    "Nothing is sent to HR until you tap **Submit to HR**, or reply **yes**."
)
CONFIRM_LEAVE_ROMAN = (
    "HR ko tabhi bhejunga jab aap **Submit to HR** dabayein, ya **haan** likhein."
)


class AgentRouter:
    def __init__(self, *, config, logger, rag, hr, drafts=None, sessions=None):
        self.config = config
        self.logger = logger
        self.rag = rag
        self.hr = hr
        # Behaves like a dict, but a half-filled leave form survives a restart.
        self.drafts = drafts if drafts is not None else create_draft_store()
        self.sessions = sessions

    def _handle_split_parts(self, parts, *, namespace, channel_id, discord_user_id, identity, conversation_history):
        answers = []
        form = None
        for part in parts:
            result = self.handle(
                question=part,
                namespace=namespace,
                channel_id=channel_id,
                discord_user_id=discord_user_id,
                identity=identity,
                conversation_history=conversation_history,
                _from_split=True,
            ) or {}
            ui = result.get("ui") or ""
            if ui in {"leave_form", "leave_confirm", "leave_pending", "leave_cancel_form"}:
                form = result
            text = str(result.get("answer") or "").strip()
            if ui in {"leave_form", "leave_confirm"} and not result.get("speakAnswer"):
                text = ""
            if text:
                answers.append(text)
        blob = "\n\n".join(answers)
        if form:
            payload = dict(form)
            payload["answer"] = blob
            payload["speakAnswer"] = bool(blob)
            return payload
        return {"answer": blob, "fallback": True, "chunks": []}

    def _leave_disabled_reply(self, identity, question=""):
        from app.hr.leave_access import leave_disabled_for_roles, leave_disabled_message

        roles = (identity or {}).get("memberRoleNames") or []
        if not leave_disabled_for_roles(roles):
            return None
        locale = (identity or {}).get("replyLanguage") or detect_reply_language(question)
        return {
            "answer": leave_disabled_message(locale),
            "fallback": True,
            "chunks": [],
            "ui": "leave_not_available",
        }

    def handle(self, *, question, namespace, channel_id, discord_user_id, identity, conversation_history, _from_split=False):
        key = str(channel_id)
        draft = self.drafts.get(key) or {}
        session = self.sessions.get(key) if self.sessions else {}
        conversation_history = merge_histories(
            (session or {}).get("turns"),
            conversation_history,
        )
        intent_history = history_for_intent(conversation_history)
        prompt_identity = dict(identity or {})
        prompt_identity["conversationHistory"] = history_for_llm(conversation_history)
        prompt_identity["sessionTopic"] = (session or {}).get("lastTopic") or last_knowledge_question(intent_history)
        prompt_identity["sessionAnswer"] = (session or {}).get("lastAnswer") or ""
        notes = ticket_notes(draft)
        if notes:
            prompt_identity["ticketNotes"] = notes
        prompt_identity["replyLanguage"] = _sticky_locale(
            question,
            draft.get("locale") or (identity or {}).get("replyLanguage"),
        )

        if not _from_split:
            parts = split_user_questions(question)
            if len(parts) > 1:
                return self._handle_split_parts(
                    parts,
                    namespace=namespace,
                    channel_id=channel_id,
                    discord_user_id=discord_user_id,
                    identity=identity,
                    conversation_history=conversation_history,
                )

        if is_profile_pii_request(question):
            locale = prompt_identity.get("replyLanguage") or detect_reply_language(question)
            return {
                "answer": profile_privacy_reply(question, locale),
                "fallback": True,
                "chunks": [],
                "ui": "profile_privacy",
            }

        from app.discord.team_directory import (
            parse_roster_query,
            resolve_my_department,
            roster_need_department_reply,
        )

        if not draft.get("awaiting_details") and not draft.get("awaiting_confirm"):
            my_dept = resolve_my_department(
                identity=prompt_identity,
                hr=self.hr,
                discord_user_id=discord_user_id,
                logger=self.logger,
            )
            roster = parse_roster_query(question, my_department=my_dept)
            if roster:
                if roster.get("needDepartment") or not roster.get("department"):
                    return {
                        "answer": roster_need_department_reply(question),
                        "fallback": True,
                        "chunks": [],
                        "ui": "team_directory_clarify",
                    }
                return {
                    "answer": "",
                    "fallback": True,
                    "chunks": [],
                    "ui": "team_directory",
                    "directoryDepartment": roster["department"],
                }

        if is_refuse_withdraw(question):
            locale = detect_reply_language(question)
            return {
                "answer": pick_locale_text(
                    locale,
                    english="Okay. I did not withdraw your leave request. It stays with HR as it is.",
                    roman="Theek hai. Maine leave request withdraw nahi ki. HR ke paas waisi hi pending hai.",
                    urdu="ٹھیک ہے۔ میں نے لیو درخواست واپس نہیں لی۔ HR کے پاس وہی پینڈنگ ہے۔",
                    mix="Theek hai. Maine leave request withdraw nahi ki. It stays pending with HR.",
                ),
                "fallback": True,
                "chunks": [],
                "ui": "leave_kept",
            }

        form_open = bool(draft.get("awaiting_details") or draft.get("awaiting_confirm"))
        if should_cancel_leave_form(question, draft, intent_history):
            self.drafts.pop(key, None)
            locale = detect_reply_language(question)
            return {
                "answer": pick_locale_text(
                    locale,
                    english="Cancelled. No leave request was sent to HR.",
                    roman="Cancel ho gaya. HR ko koi leave request nahi gayi.",
                    urdu="منسوخ ہو گیا۔ HR کو کوئی لیو درخواست نہیں گئی۔",
                    mix="Cancel ho gaya. No leave request was sent to HR.",
                ),
                "fallback": True,
                "chunks": [],
                "ui": "leave_cancelled",
            }

        if is_cancel_approved_leave(question) and not form_open:
            return self._open_cancel_form(
                key,
                discord_user_id,
                detect_reply_language(question),
                identity,
                question=question,
            )

        if is_withdraw_leave(question) and not is_company_leave_policy_question(question):
            return self._withdraw_pending(channel_id, discord_user_id, detect_reply_language(question), identity)

        if (
            (is_bare_deny(question) or is_bare_affirm(question))
            and not should_cancel_leave_form(question, draft, intent_history)
            and not should_confirm_leave_form(question, draft, intent_history)
        ):
            locale = detect_reply_language(question)
            return {
                "answer": pick_locale_text(
                    locale,
                    english="Okay. Ask about policy, your leave, or this ticket.",
                    roman="Theek hai. Policy, leave, ya is ticket ke baare mein poochhein.",
                    urdu="ٹھیک ہے۔ پالیسی، لیو، یا اس ٹکٹ کے بارے میں پوچھیں۔",
                    mix="Theek hai. Policy, leave, ya ticket ke baare mein poochhein.",
                ),
                "fallback": True,
                "chunks": [],
                "ui": "polarity_ack",
            }

        last_answer = prompt_identity.get("sessionAnswer") or ""
        last_topic = prompt_identity.get("sessionTopic") or ""
        followup = is_session_followup(question)

        if followup and not last_answer and not last_topic:
            locale = detect_reply_language(question)
            return {
                "answer": pick_locale_text(
                    locale,
                    english="Which policy should I show — leave, OPD/medical, WFH, holidays, or working hours?",
                    roman="Kaunsi policy chahiye — leave, OPD/medical, WFH, holidays, ya working hours?",
                    urdu="کون سی پالیسی چاہیے — لیو، میڈیکل/OPD، WFH، چھٹیاں، یا ورکنگ آورز؟",
                    mix="Kaunsi policy chahiye — leave, OPD/medical, WFH, holidays, or working hours?",
                ),
                "fallback": True,
                "chunks": [],
                "ui": "session_prompt",
            }

        if followup and last_answer and is_repeat_followup(question) and not is_format_followup(question):
            return {"answer": last_answer, "fallback": False, "chunks": [], "ui": "session_repeat"}

        if (
            followup
            and last_answer
            and is_format_followup(question)
            and not is_expand_followup(question)
        ):
            return self._rewrite_session_answer(question=question, identity=prompt_identity, last_answer=last_answer)

        # A new policy question must not reuse the last personal-balance card.
        if is_company_leave_policy_question(question) and not is_company_leave_allowance_question(question):
            prompt_identity["sessionAnswer"] = ""

        chatting = (
            is_conversation_continue(question)
            and not is_explicit_leave_apply(question)
            and not is_confirm_submit(question)
            and not followup
        )
        if chatting and not draft.get("awaiting_confirm"):
            self.drafts.pop(key, None)
        draft_open = bool(draft.get("awaiting_details") or draft.get("awaiting_confirm"))
        if (
            draft_open
            and looks_like_leave_form_reply(question, draft)
            and not is_company_leave_policy_question(question)
            and not is_asset_conduct_policy_question(question)
            and not is_policy_conversation_followup(question, intent_history)
            and not followup
        ):
            return self._handle_leave_request(
                question=question,
                channel_id=channel_id,
                discord_user_id=discord_user_id,
                conversation_history=intent_history,
                identity=identity,
            )

        # Clearly out of scope (maths, trivia, coding, news): answer from here.
        # Doing this before retrieval means no lookup is spent on it, and no
        # loosely matching handbook chunk can be turned into an answer.
        off_topic = off_topic_kind(question)
        if off_topic and not draft_open:
            self.logger.info("Off-topic message redirected", {"kind": off_topic})
            return {
                "answer": redirect_reply(question, off_topic, prompt_identity["replyLanguage"]),
                "fallback": True,
                "chunks": [],
                "offTopic": off_topic,
            }

        social = classify_social(question)
        if (social or is_about_bot(question)) and not followup:
            return search_hr_policy(
                self.rag,
                question=question,
                namespace=namespace,
                channel_id=channel_id,
                identity=prompt_identity,
                conversation_history=prompt_identity["conversationHistory"],
            )

        route = classify_hr_route(question, intent_history)
        intent = classify_hr_intent(question, intent_history)
        self.logger.debug("Query source", {
            "intent": intent,
            "source": source_for_intent(intent),
            "webairy": route.get("intent"),
            "sub_intent": route.get("sub_intent"),
        })
        if intent in {"LEAVE_BALANCE", "ATTENDANCE", "LEAVE_REQUEST", "HUMAN_HR", "MIXED"} and self.hr is None:
            return {
                "answer": pick_locale_text(
                    prompt_identity["replyLanguage"],
                    english="HR data is not connected yet. You can still ask policy questions.",
                    roman="HR data abhi connect nahi hai. Policy ke sawal phir bhi pooch sakte hain.",
                    urdu="HR ڈیٹا ابھی منسلک نہیں ہے۔ آپ پالیسی کے سوال پھر بھی پوچھ سکتے ہیں۔",
                    mix="HR data abhi connect nahi hai. You can still ask policy questions.",
                ),
                "fallback": True,
                "chunks": [],
            }

        if intent == "CLARIFY":
            locale = detect_reply_language(question)
            text = pick_locale_text(
                locale,
                english=route.get("clarification_question") or CLARIFY_QUESTION,
                roman=CLARIFY_QUESTION_ROMAN,
                urdu=CLARIFY_QUESTION_ROMAN,
                mix=CLARIFY_QUESTION_ROMAN,
            )
            return {"answer": text, "fallback": True, "chunks": [], "ui": "clarify"}

        if intent == "HUMAN_HR":
            mention = _hr_mention(self.config)
            text = pick_locale_text(
                detect_reply_language(question),
                english=f"An HR teammate can help in this ticket. {mention}".strip(),
                roman=f"Is ticket mein HR teammate madad kar sakta hai. {mention}".strip(),
                urdu=f"اس ٹکٹ میں HR مدد کر سکتا ہے۔ {mention}".strip(),
                mix=f"HR teammate is ticket mein madad kar sakta hai. {mention}".strip(),
            )
            return {"answer": text, "fallback": True, "chunks": []}

        if intent == "LEAVE_BALANCE":
            blocked = self._leave_disabled_reply(prompt_identity, question)
            if blocked:
                return blocked
            result = get_my_leave_balance(
                self.hr,
                discord_user_id,
                infer_leave_type(question),
                locale=_locale(question),
                role_names=(prompt_identity or {}).get("memberRoleNames") or [],
            )
            return _leave_balance_result(result)

        if intent == "ATTENDANCE":
            return search_hr_policy(
                self.rag,
                question=question,
                namespace=namespace,
                channel_id=channel_id,
                identity=prompt_identity,
                conversation_history=prompt_identity["conversationHistory"],
            )

        if intent == "LEAVE_REQUEST":
            blocked = self._leave_disabled_reply(prompt_identity, question)
            if blocked:
                return blocked
            return self._handle_leave_request(
                question=question,
                channel_id=channel_id,
                discord_user_id=discord_user_id,
                identity=prompt_identity,
                conversation_history=prompt_identity["conversationHistory"],
            )

        if intent == "MIXED":
            blocked = self._leave_disabled_reply(prompt_identity, question)
            if blocked and route.get("sub_intent") in {
                "holiday_plus_create",
                "wfh_plus_create",
                "policy_plus_create",
                "policy_plus_balance",
                "holiday_plus_status",
            }:
                # Policy-only part can still answer if we strip leave — for create/balance
                # intents, refuse leave entirely.
                if "create" in str(route.get("sub_intent") or "") or "balance" in str(route.get("sub_intent") or ""):
                    return blocked
            return self._handle_mixed(
                question=question,
                namespace=namespace,
                channel_id=channel_id,
                discord_user_id=discord_user_id,
                identity=prompt_identity,
                conversation_history=prompt_identity["conversationHistory"],
                sub_intent=route.get("sub_intent"),
            )

        if is_explicit_leave_apply(question) and not is_quota_or_status_question(question):
            blocked = self._leave_disabled_reply(prompt_identity, question)
            if blocked:
                return blocked
            return self._handle_mixed(
                question=question,
                namespace=namespace,
                channel_id=channel_id,
                discord_user_id=discord_user_id,
                identity=prompt_identity,
                conversation_history=prompt_identity["conversationHistory"],
                sub_intent="policy_plus_create",
            )

        policy = search_hr_policy(
            self.rag,
            question=question,
            namespace=namespace,
            channel_id=channel_id,
            identity=prompt_identity,
            conversation_history=prompt_identity["conversationHistory"],
        )
        # "How many leaves are allowed?" can use the recorded yearly entitlement
        # when the handbook has no numbers. "What is the leave policy?" must stay
        # on the handbook — personal remaining days are a different route.
        if is_company_leave_allowance_question(question) and not _mentions_entitlement(
            policy.get("chunks")
        ):
            entitlement = self._entitlement_answer(
                discord_user_id, prompt_identity["replyLanguage"]
            )
            if entitlement:
                return entitlement
        return policy

    def _entitlement_answer(self, discord_user_id, locale):
        """Leave allowance taken from the employee's recorded entitlement."""
        summary = getattr(getattr(self.hr, "leave", None), "entitlement_summary", None)
        if not callable(summary):
            return None
        try:
            result = summary(discord_user_id, locale)
        except AppError:
            return None
        if not result:
            return None
        self.logger.info("Answered a leave allowance question from entitlements")
        return _leave_balance_result(result)

    def _remember(self, key, draft):
        """Store the draft and flush it, including flags set while building
        the reply payload."""
        self.drafts[str(key)] = draft
        saver = getattr(self.drafts, "save", None)
        if callable(saver):
            saver()

    def _rewrite_session_answer(self, *, question, identity, last_answer):
        if self.rag is None or getattr(self.rag, "llm", None) is None:
            return {"answer": last_answer, "fallback": False, "chunks": [], "ui": "session_repeat"}
        rewritten = self.rag.llm.generate_answer(
            question=question,
            context_blocks=[{"source": "previous ticket answer", "text": last_answer}],
            mode="knowledge",
            identity=identity,
        )
        return {
            "answer": rewritten or last_answer,
            "fallback": False,
            "chunks": [],
            "ui": "session_repeat",
        }

    def _reply_if_pending_leave(self, key, discord_user_id, locale):
        leave = getattr(getattr(self, "hr", None), "leave", None)
        checker = getattr(leave, "pending_already_open_error", None)
        if not callable(checker):
            return None
        error = checker(discord_user_id, locale)
        if error is None:
            return None
        self.drafts.pop(key, None)
        card = None
        builder = getattr(leave, "pending_card_for_member", None)
        if callable(builder):
            card = builder(discord_user_id, locale)
        payload = {
            "answer": str(error),
            "fallback": True,
            "chunks": [],
            "stickyPending": True,
        }
        if card:
            payload["ui"] = "leave_pending"
            payload["leaveCard"] = card
        return payload

    def _withdraw_pending(self, channel_id, discord_user_id, locale, identity=None):
        self.drafts.pop(str(channel_id), None)
        leave = getattr(getattr(self, "hr", None), "leave", None)
        withdraw = getattr(leave, "withdraw_pending_for_member", None)
        if not callable(withdraw):
            return {
                "answer": pick_locale_text(
                    locale,
                    english="HR data is not connected yet.",
                    roman="HR data connected nahi hai.",
                    urdu="HR ڈیٹا منسلک نہیں ہے۔",
                    mix="HR data connected nahi hai.",
                ),
                "fallback": True,
                "chunks": [],
            }
        identity = identity or {}
        name = identity.get("memberName") or "Staff"
        saved = withdraw(
            discord_user_id,
            withdrawn_by=f"{name} ({discord_user_id})",
            locale=locale,
        )
        answer = pick_locale_text(
            locale,
            english="Your leave request was withdrawn. HR will not process it. You can apply again when you are ready.",
            roman="Leave request withdraw ho gayi. HR isay process nahi karega. Jab tayar hon, dubara apply kar sakte ho.",
            urdu="آپ کی لیو درخواست واپس لے لی گئی۔ HR اسے پروسیس نہیں کرے گا۔ جب تیار ہوں دوبارہ درخواست دے سکتے ہیں۔",
            mix="Leave request withdraw ho gayi. You can apply again when you are ready.",
        )
        return {
            "answer": answer,
            "fallback": True,
            "chunks": [],
            "ui": "leave_withdrawn",
            "leaveCard": {
                "locale": locale,
                "leave_type": saved.get("leaveType") or "Leave",
                "start_date": saved.get("startDate"),
                "end_date": saved.get("endDate"),
                "days": saved.get("daysRequested") or 1,
                "name": saved.get("employeeName") or name,
                "reason": saved.get("reason") or "",
                "status": "Withdrawn",
            },
        }

    def _open_cancel_form(self, key, discord_user_id, locale, identity=None, question=""):
        leave = getattr(getattr(self, "hr", None), "leave", None)
        rows = []
        if leave is not None:
            try:
                rows = leave.list_cancellable_approved(discord_user_id)
            except AppError:
                rows = []
        if not rows:
            return {
                "answer": pick_locale_text(
                    locale,
                    english="You have no leave to be cancelled.",
                    roman="Cancel karne ke liye koi approved leave nahi hai.",
                    urdu="منسوخ کرنے کے لیے کوئی منظور شدہ لیو نہیں ہے۔",
                    mix="You have no leave to be cancelled.",
                ),
                "fallback": True,
                "chunks": [],
                "ui": "leave_cancel_none",
            }
        start = end = None
        request_id = ""
        if len(rows) == 1:
            start = _as_form_day(rows[0].get("start_date"))
            end = _as_form_day(rows[0].get("end_date")) or start
            request_id = rows[0].get("id") or rows[0].get("requestId") or ""
        prompt = str(question or "")
        reason = ""
        if re.search(r"\b(because|waja|reason)\b", prompt, re.I):
            reason = infer_leave_reason(prompt) or ""
        draft = {
            "awaiting_cancel": True,
            "awaiting_details": False,
            "awaiting_confirm": False,
            "locale": locale,
            "reason": reason,
            "start_date": start,
            "end_date": end,
            "request_id": request_id,
            "approved": rows,
        }
        self._remember(key, draft)
        return _cancel_form_payload(draft, locale)

    def _submit_cancel_leave(self, key, discord_user_id, identity=None):
        draft = self.drafts.get(key) or {}
        locale = draft.get("locale") or "english"
        leave = getattr(getattr(self, "hr", None), "leave", None)
        if leave is None:
            return {
                "error": pick_locale_text(
                    locale,
                    english="HR data is not connected yet.",
                    roman="HR data connected nahi hai.",
                    urdu="HR ڈیٹا منسلک نہیں ہے۔",
                    mix="HR data connected nahi hai.",
                )
            }
        start = draft.get("start_date")
        end = draft.get("end_date") or start
        reason = str(draft.get("reason") or "").strip()
        request_id = str(draft.get("request_id") or "").strip()
        if not request_id and (not start or not end):
            return {
                "error": pick_locale_text(
                    locale,
                    english="Choose which approved leave to cancel, then add a reason.",
                    roman="Pehle approved leave choose karein, phir reason likhein.",
                    urdu="پہلے منظور شدہ لیو منتخب کریں، پھر وجہ لکھیں۔",
                    mix="Pehle approved leave choose karein, then add a reason.",
                )
            }
        if not reason:
            return {
                "error": pick_locale_text(
                    locale,
                    english="Add a reason for cancelling this leave.",
                    roman="Leave cancel karne ki reason likhein.",
                    urdu="لیو منسوخ کرنے کی وجہ لکھیں۔",
                    mix="Add a reason for cancelling this leave.",
                )
            }
        identity = identity or {}
        name = identity.get("memberName") or "Staff"
        from app.hr.leave_status import EMPLOYEE

        saved = leave.cancel_approved_for_member(
            discord_user_id,
            request_id=request_id or None,
            start_date=start,
            end_date=end,
            actor_id=discord_user_id,
            actor_name=name,
            tier=EMPLOYEE,
            reason=reason,
        )
        self.drafts.pop(key, None)
        span_start = saved.get("startDate")
        span_end = saved.get("endDate") or span_start
        answer = pick_locale_text(
            locale,
            english="That approved leave is cancelled. The days were returned to your balance.",
            roman="Woh approved leave cancel ho gayi. Days wapas balance mein add ho gaye.",
            urdu="وہ منظور شدہ لیو منسوخ ہو گئی۔ دن بیلنس میں واپس آ گئے۔",
            mix="Woh approved leave cancel ho gayi. The days were returned to your balance.",
        )
        return {
            "answer": answer,
            "fallback": True,
            "chunks": [],
            "ui": "leave_approved_cancelled",
            "leaveCard": {
                "locale": locale,
                "leave_type": saved.get("leaveType") or "Leave",
                "start_date": span_start,
                "end_date": span_end,
                "days": saved.get("daysRequested") or 1,
                "name": saved.get("employeeName") or name,
                "reason": reason,
                "status": "Cancelled",
            },
            "saved": saved,
        }

    def _handle_mixed(self, *, question, namespace, channel_id, discord_user_id, identity, conversation_history, sub_intent=None):
        policy = {"answer": "", "chunks": []}
        if self.rag is not None:
            try:
                policy = search_hr_policy(
                    self.rag,
                    question=question,
                    namespace=namespace,
                    channel_id=channel_id,
                    identity=identity,
                    conversation_history=conversation_history,
                )
            except AppError:
                policy = {"answer": "", "chunks": []}
        locale = _locale(question)
        fact = weekend_day_answer(question, locale)
        policy_text = "\n\n".join(
            part for part in (fact, (policy.get("answer") or "").strip()) if part
        ).strip()
        if sub_intent in {"holiday_plus_create", "wfh_plus_create", "policy_plus_create"}:
            form = self._handle_leave_request(
                question=question,
                channel_id=channel_id,
                discord_user_id=discord_user_id,
                identity=identity,
                conversation_history=conversation_history,
            )
            if form.get("stickyPending") or form.get("ui") in {
                "leave_pending",
                "leave_cancelled",
                "leave_withdrawn",
            }:
                return form
            payload = dict(form)
            if policy_text:
                payload["answer"] = policy_text
                payload["speakAnswer"] = True
            payload["chunks"] = policy.get("chunks") or form.get("chunks") or []
            return payload
        leave_type = infer_leave_type(question)
        live = ""
        try:
            live_result = get_my_leave_balance(
                self.hr,
                discord_user_id,
                leave_type,
                locale=_locale(question),
                role_names=(identity or {}).get("memberRoleNames") or [],
            )
            live = live_result["text"]
        except AppError as error:
            if error.code == ErrorCodes.LEAVE_NOT_AVAILABLE and error.expose:
                # Still answer the policy half; skip personal balance.
                live = ""
            elif error.expose:
                live = error.args[0]
            else:
                raise
        if self.rag is None:
            if not live and not policy_text:
                blocked = self._leave_disabled_reply(identity, question)
                if blocked:
                    return blocked
            return {"answer": f"{policy.get('answer')}\n\n{live}".strip(), "fallback": True, "chunks": policy.get("chunks") or []}
        if not live:
            # Policy-only mixed answer when leave is disabled for this role.
            answer = self.rag.llm.generate_answer(
                question=question,
                context_blocks=policy.get("chunks") or [],
                mode="knowledge",
                identity=identity or {},
            )
            return {"answer": answer, "fallback": False, "chunks": policy.get("chunks") or []}
        mixed_identity = dict(identity or {})
        mixed_identity["liveFacts"] = live
        mixed_identity["conversationHistory"] = conversation_history or []
        answer = self.rag.llm.generate_answer(
            question=question,
            context_blocks=policy.get("chunks") or [],
            mode="mixed",
            identity=mixed_identity,
        )
        return {"answer": answer, "fallback": False, "chunks": policy.get("chunks") or []}

    def _handle_leave_request(self, *, question, channel_id, discord_user_id, conversation_history, identity=None):
        blocked = self._leave_disabled_reply(identity, question)
        if blocked:
            self.drafts.pop(str(channel_id), None)
            return blocked
        key = str(channel_id)
        draft = self.drafts.get(key) or {}

        locale = _sticky_locale(question, draft.get("locale"))
        draft["locale"] = locale

        if should_cancel_leave_form(question, draft, conversation_history):
            self.drafts.pop(key, None)
            cancel = pick_locale_text(
                locale,
                english="Cancelled. No leave request was sent to HR.",
                roman="Cancel ho gaya. HR ko koi leave request nahi gayi.",
                urdu="منسوخ ہو گیا۔ HR کو کوئی لیو درخواست نہیں گئی۔",
                mix="Cancel ho gaya. No leave request was sent to HR.",
            )
            return {"answer": cancel, "fallback": True, "chunks": [], "ui": "leave_cancelled"}

        if is_confirm_submit(question) and not draft.get("awaiting_confirm"):
            if not draft.get("awaiting_details"):
                ack = pick_locale_text(
                    locale,
                    english="Alright. Ask a policy question, or say clearly that you want to apply for leave.",
                    roman="Theek hai. Policy poochhein, ya clearly kaho ke aap leave apply karna chahte hain.",
                    urdu="ٹھیک ہے۔ پالیسی پوچھیں، یا صاف کہیں کہ آپ لیو اپلائی کرنا چاہتے ہیں۔",
                    mix="Theek hai. Ask a policy question, or say you want to apply for leave.",
                )
                return {"answer": ack, "fallback": True, "chunks": []}

        if is_new_leave_start(question) and not is_confirm_submit(question):
            form_open = bool(draft.get("awaiting_details") or draft.get("awaiting_confirm"))
            if not form_open:
                draft = {"locale": locale}

        if is_quota_or_status_question(question) and not is_explicit_leave_apply(question) and not draft.get("awaiting_details") and not draft.get("awaiting_confirm"):
            result = get_my_leave_balance(
                self.hr,
                discord_user_id,
                infer_leave_type(question),
                locale=locale,
                role_names=(identity or {}).get("memberRoleNames") or [],
            )
            return _leave_balance_result(result)

        blocked = self._reply_if_pending_leave(key, discord_user_id, locale)
        if blocked:
            return blocked

        # Leave details are form-only. Chat must not auto-fill type/dates/reason —
        # the user opens Fill form (and the leave-type dropdown) instead.
        applying = (
            is_explicit_leave_apply(question)
            or is_new_leave_start(question)
            or bool(draft.get("awaiting_details"))
            or bool(draft.get("awaiting_confirm"))
        )
        confirming = should_confirm_leave_form(question, draft, conversation_history) and draft.get("awaiting_confirm")

        if not applying and not confirming and not draft.get("awaiting_details"):
            self._remember(key, draft)
            result = get_my_leave_balance(
                self.hr,
                discord_user_id,
                infer_leave_type(question) or draft.get("leave_type"),
                locale=locale,
                role_names=(identity or {}).get("memberRoleNames") or [],
            )
            extra = pick_locale_text(
                locale,
                english=(
                    "\n\nI did not create an HR approval. If you want to apply, say "
                    "I want leave — then use Fill form on the card."
                ),
                roman=(
                    "\n\nMaine HR approval create nahi ki. Apply karna ho to "
                    "I want leave kaho, phir card par Fill form use karein."
                ),
                urdu=(
                    "\n\nمیں نے HR منظوری نہیں بنائی۔ درخواست کے لیے "
                    "I want leave کہیں، پھر کارڈ پر Fill form استعمال کریں۔"
                ),
                mix=(
                    "\n\nMaine HR approval create nahi ki. If you want to apply: "
                    "say I want leave, then use Fill form on the card."
                ),
            )
            return {
                "answer": result["text"] + extra,
                "fallback": False,
                "chunks": [],
            }

        ready = _leave_dates_ready(draft)
        can_submit = _leave_submit_ready(draft)

        if not ready or not can_submit:
            payload = _form_payload(draft, locale)
            self._remember(key, draft)
            return payload

        if not confirming:
            # Everything is filled in, but nothing goes to HR until they submit.
            payload = _confirm_payload(draft, locale)
            self._remember(key, draft)
            return payload

        try:
            created = prepare_leave_request(
                self.hr,
                discord_user_id=discord_user_id,
                ticket_channel_id=channel_id,
                leave_type_name=draft["leave_type"],
                start_date=draft["start_date"],
                end_date=draft.get("end_date") or draft["start_date"],
                reason=str(draft.get("reason") or "").strip(),
                locale=locale,
                half_day=draft.get("half_day") or "",
                role_names=(identity or {}).get("memberRoleNames") or [],
            )
        except AppError as error:
            if error.code != ErrorCodes.LEAVE_DATES_APPROVED:
                raise
            payload = _confirm_payload(draft, locale) if _leave_submit_ready(draft) else _form_payload(draft, locale)
            self._remember(key, draft)
            payload["answer"] = str(error)
            card = dict(payload.get("leaveCard") or {})
            card["hint"] = str(error)
            payload["leaveCard"] = card
            return payload
        self.drafts.pop(key, None)
        mention = _hr_mention(self.config)
        remaining = created.get("remaining")
        start = created.get("startDate")
        name = created.get("employeeName") or "The employee"
        days = int(created.get("daysRequested") or 1)
        leave_name = draft.get("leave_type") or created.get("leaveType") or "Leave"
        if str(leave_name).startswith("rec") and " " not in str(leave_name):
            leave_name = draft.get("leave_type") or "Leave"
        balance_text = ""
        balance_name = name if name != "The employee" else ""
        try:
            live = get_my_leave_balance(
                self.hr,
                discord_user_id,
                locale=locale,
                role_names=(identity or {}).get("memberRoleNames") or [],
            )
            balance_text = live["text"]
            balance_name = _leave_employee_name(live) or balance_name
        except AppError:
            balance_text = ""
        from app.hr.leave_status import PENDING_HR, PENDING_MANAGER

        waiting_hod = bool(created.get("needsHod")) or str(created.get("status") or "") == PENDING_MANAGER
        card_status = PENDING_MANAGER if waiting_hod else (created.get("status") or PENDING_HR)
        need_hr = pick_locale_text(
            locale,
            english="HOD approval required." if waiting_hod else "HR approval required.",
            roman="HOD approval chahiye." if waiting_hod else "HR approval chahiye.",
            urdu="HOD منظوری درکار ہے۔" if waiting_hod else "HR منظوری درکار ہے۔",
            mix="HOD approval chahiye." if waiting_hod else "HR approval chahiye / required.",
        )
        mention = "" if waiting_hod else _hr_mention(self.config)
        answer = f"{need_hr}\n{mention}".strip()
        return {
            "answer": answer,
            "fallback": False,
            "chunks": [],
            "ui": "leave_pending",
            "balanceText": balance_text,
            "employeeName": balance_name,
            "leaveCard": {
                "locale": locale,
                "leave_type": leave_name,
                "start_date": str(start or "")[:10],
                "end_date": str(created.get("endDate") or draft.get("end_date") or start or "")[:10],
                "days": days,
                "name": name,
                "remaining": remaining,
                "reason": str(draft.get("reason") or "").strip(),
                "status": card_status,
                "department": created.get("department") or "",
                "needsHod": waiting_hod,
            },
        }


ENTITLEMENT_WORDS = re.compile(
    r"annual leave|sick leave|casual leave|"
    r"leave entitle|entitled to \d|days? of (?:paid )?leave|paid leave|"
    r"leave quota|leave allowance|leaves? (?:are )?allowed|"
    r"\d+\s*days?\s*(?:of\s*)?(?:annual|sick|casual|paid)\b",
    re.I,
)


def _mentions_entitlement(chunks):
    """Do the retrieved passages actually cover how much leave is allowed?

    Without this the model answers a leave-allowance question out of whatever
    happened to score highest - attendance or holidays - and politely declines,
    which reads like the bot does not know its own company's entitlements.
    """
    for chunk in chunks or []:
        text = chunk.get("text") if isinstance(chunk, dict) else getattr(chunk, "text", "")
        if text and ENTITLEMENT_WORDS.search(str(text)):
            return True
    return False


def _merge_leave_draft(draft, parsed, _question=None):
    if parsed.get("leave_type"):
        draft["leave_type"] = parsed["leave_type"]
    if parsed.get("reason") and not str(draft.get("reason") or "").strip():
        draft["reason"] = str(parsed["reason"]).strip()
    days = parsed.get("days_count")
    if days:
        draft["days_count"] = days

    if parsed.get("explicit_range") and parsed.get("start_date") and parsed.get("end_date"):
        draft["start_date"] = parsed["start_date"]
        draft["end_date"] = parsed["end_date"]
        draft["days_count"] = (draft["end_date"] - draft["start_date"]).days + 1
        draft["range_complete"] = True
        draft["awaiting_end"] = False
        return

    awaiting_end = bool(draft.get("awaiting_end")) and bool(draft.get("start_date"))
    if awaiting_end and parsed.get("start_date") and not parsed.get("explicit_range"):
        draft["end_date"] = parsed["start_date"]
        if draft.get("start_date") and draft["end_date"] < draft["start_date"]:
            draft["end_date"] = draft["end_date"] + timedelta(days=7)
        draft["days_count"] = (draft["end_date"] - draft["start_date"]).days + 1
        draft["range_complete"] = True
        draft["awaiting_end"] = False
        return

    if parsed.get("start_date"):
        draft["start_date"] = parsed["start_date"]
        if parsed.get("end_date") and parsed["end_date"] != parsed["start_date"]:
            draft["end_date"] = parsed["end_date"]
            draft["range_complete"] = True
        elif draft.get("days_count"):
            draft["end_date"] = draft["start_date"] + timedelta(days=int(draft["days_count"]) - 1)
            draft["range_complete"] = True
        else:
            draft["days_count"] = draft.get("days_count") or 1
            draft["end_date"] = parsed.get("end_date") or parsed["start_date"]
            draft["range_complete"] = True

    if draft.get("start_date") and draft.get("days_count") and not draft.get("end_date"):
        draft["end_date"] = draft["start_date"] + timedelta(days=int(draft["days_count"]) - 1)
        draft["range_complete"] = True


def _leave_dates_ready(draft):
    if not draft.get("leave_type"):
        return False
    days = int(draft.get("days_count") or 0)
    if days > 1 and not draft.get("start_date") and not draft.get("range_complete"):
        return False
    if not draft.get("start_date"):
        return False
    if not draft.get("end_date"):
        if days > 1:
            draft["end_date"] = draft["start_date"] + timedelta(days=days - 1)
        else:
            draft["end_date"] = draft["start_date"]
            draft["days_count"] = 1
    return True


def _leave_draft_ready(draft):
    return _leave_dates_ready(draft)


def _leave_submit_ready(draft):
    return _leave_dates_ready(draft) and bool(str(draft.get("reason") or "").strip())


def _capture_reason_if_needed(draft, question, parsed):
    if (draft.get("reason") or "").strip():
        return
    if parsed.get("reason"):
        draft["reason"] = str(parsed["reason"]).strip()
        return
    if not _leave_dates_ready(draft):
        return
    if parsed.get("start_date") or parsed.get("explicit_range"):
        return
    if parsed.get("leave_type") and len(str(question or "").split()) <= 3:
        return
    text = str(question or "").strip()
    if not text or is_confirm_submit(text) or is_cancel_submit(text):
        return
    draft["reason"] = text


def _form_hint(draft, locale):
    if not draft.get("leave_type"):
        return pick_locale_text(
            locale,
            english="Select a leave type, then open Fill form for dates and reason.",
            roman="Leave type select karein, phir dates aur reason ke liye Fill form kholein.",
            urdu="لیو کی قسم منتخب کریں، پھر تاریخ اور وجہ کے لیے Fill form کھولیں۔",
            mix="Leave type select karein, then open Fill form for dates and reason.",
        )
    if not draft.get("start_date") or not str(draft.get("reason") or "").strip():
        return pick_locale_text(
            locale,
            english="Open Fill form to set From, To, and the reason for leave.",
            roman="From, To, aur reason set karne ke liye Fill form kholein.",
            urdu="From، To اور وجہ سیٹ کرنے کے لیے Fill form کھولیں۔",
            mix="Open Fill form to set From, To, and the reason for leave.",
        )
    return pick_locale_text(
        locale,
        english="Review the form, then submit.",
        roman="Form check karein, phir submit karein.",
        urdu="فارم چیک کریں، پھر جمع کریں۔",
        mix="Form check karein, then submit.",
    )


def _ask_leave_details(draft, locale):
    return _form_hint(draft, locale)


def _locale(question, *more):
    return detect_reply_language(" ".join(str(item or "") for item in (question,) + more))


def _sticky_locale(question, draft_locale):
    """Keep the language the member has been using.

    A bare "yes", "ok" or "no" carries no language signal, so detection falls
    back to English. When a draft is already running in Roman Urdu or Urdu,
    those short replies must not flip the card to English.
    """
    if draft_locale and (is_confirm_submit(question) or is_cancel_submit(question)):
        return draft_locale
    detected = detect_reply_language(question)
    if detected == "english" and draft_locale and len(str(question or "").split()) <= 2:
        return draft_locale
    return detected or draft_locale or "english"


def _leave_card(draft, locale, *, stage="form"):
    start = draft.get("start_date")
    end = draft.get("end_date")
    days = None
    if start and end:
        days = (end - start).days + 1
    return {
        "locale": locale,
        "leave_type": draft.get("leave_type") or "",
        "start_date": start.isoformat() if start else "",
        "end_date": end.isoformat() if end else "",
        "days": days,
        "half_day": draft.get("half_day") or "",
        "reason": str(draft.get("reason") or "").strip(),
        "attachments": list(draft.get("attachments") or []),
        "stage": stage,
        "hint": _form_hint(draft, locale),
    }


def _form_payload(draft, locale):
    draft["awaiting_details"] = True
    draft["awaiting_confirm"] = False
    return {
        "answer": _form_hint(draft, locale),
        "fallback": True,
        "chunks": [],
        "ui": "leave_form",
        "leaveCard": _leave_card(draft, locale, stage="form"),
    }


def _confirm_payload(draft, locale):
    draft["awaiting_confirm"] = True
    draft["awaiting_details"] = False
    return {
        "answer": _confirm_preview(draft, locale),
        "fallback": True,
        "chunks": [],
        "ui": "leave_confirm",
        "leaveCard": _leave_card(draft, locale, stage="confirm"),
    }


def _as_form_day(value):
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _iso_or_blank(value):
    day = _as_form_day(value)
    return day.isoformat() if day else ""


def _cancel_form_payload(draft, locale):
    rows = list(draft.get("approved") or [])
    if rows:
        hint = pick_locale_text(
            locale,
            english="Your approved leave is listed below. Choose one, add a reason, then submit.",
            roman="Neeche aapki approved leave hai. Ek choose karein, reason likhein, phir submit karein.",
            urdu="نیچے آپ کی منظور شدہ لیو ہے۔ ایک منتخب کریں، وجہ لکھیں، پھر جمع کریں۔",
            mix="Neeche aapki approved leave hai. Choose one, add a reason, then submit.",
        )
    else:
        hint = pick_locale_text(
            locale,
            english="You have no upcoming approved leave to cancel.",
            roman="Cancel karne ke liye koi upcoming approved leave nahi hai.",
            urdu="منسوخ کرنے کے لیے کوئی آنے والی منظور شدہ لیو نہیں ہے۔",
            mix="Cancel karne ke liye koi upcoming approved leave nahi hai.",
        )
    return {
        "answer": hint,
        "fallback": True,
        "chunks": [],
        "ui": "leave_cancel_form",
        "leaveCard": {
            "locale": locale,
            "stage": "cancel",
            "approved": rows,
            "start_date": _iso_or_blank(draft.get("start_date")),
            "end_date": _iso_or_blank(draft.get("end_date")),
            "reason": str(draft.get("reason") or "").strip(),
            "request_id": str(draft.get("request_id") or "").strip(),
            "hint": hint,
        },
    }


def _cancel_choice_id(item):
    return str((item or {}).get("id") or (item or {}).get("requestId") or "").strip()[:100]


def apply_cancel_leave_pick(agent, channel_id, choice):
    key = str(channel_id)
    draft = agent.drafts.get(key) or {}
    locale = draft.get("locale") or "english"
    wanted = str(choice or "").strip()
    picked = None
    for item in draft.get("approved") or []:
        if _cancel_choice_id(item) == wanted:
            picked = item
            break
    if not picked:
        return {
            "error": pick_locale_text(
                locale,
                english="Choose an approved leave from the list.",
                roman="List se approved leave choose karein.",
                urdu="فہرست سے منظور شدہ لیو منتخب کریں۔",
                mix="List se approved leave choose karein.",
            )
        }
    draft["awaiting_cancel"] = True
    draft["start_date"] = _as_form_day(picked.get("start_date"))
    draft["end_date"] = _as_form_day(picked.get("end_date")) or draft["start_date"]
    draft["request_id"] = _cancel_choice_id(picked)
    payload = _cancel_form_payload(draft, locale)
    agent._remember(key, draft)
    return payload


def apply_cancel_leave_form(agent, channel_id, *, from_text="", to_text="", reason, today=None):
    key = str(channel_id)
    draft = agent.drafts.get(key) or {}
    locale = draft.get("locale") or "english"
    today = today or date.today()
    start = end = None
    if str(from_text or "").strip() or str(to_text or "").strip():
        start, end = resolve_date_range(f"{from_text} to {to_text}".strip(), today=today)
        if not start:
            start = resolve_date_phrase(from_text, today=today)
            end = resolve_date_phrase(to_text, today=today) or start
        if not start or not end:
            return {
                "error": pick_locale_text(
                    locale,
                    english="Those dates could not be read. Choose an approved leave from the list.",
                    roman="Dates samajh nahi aayin. List se approved leave choose karein.",
                    urdu="تاریخ سمجھی نہیں گئی۔ فہرست سے منظور شدہ لیو منتخب کریں۔",
                    mix="Dates samajh nahi aayin. List se approved leave choose karein.",
                )
            }
        if end < start:
            end = start
        draft["start_date"] = start
        draft["end_date"] = end
    draft["awaiting_cancel"] = True
    draft["reason"] = str(reason or "").strip()
    payload = _cancel_form_payload(draft, locale)
    agent._remember(key, draft)
    return payload


def apply_leave_type(agent, channel_id, leave_type):
    key = str(channel_id)
    draft = agent.drafts.get(key) or {}
    if leave_type:
        draft["leave_type"] = leave_type
    locale = draft.get("locale") or "english"
    payload = _confirm_payload(draft, locale) if _leave_submit_ready(draft) else _form_payload(draft, locale)
    agent._remember(key, draft)
    return payload


def apply_leave_form(agent, channel_id, *, from_text, to_text, reason, half_day="", attachments=None, today=None):
    key = str(channel_id)
    draft = agent.drafts.get(key) or {}
    locale = draft.get("locale") or "english"
    today = today or date.today()
    start, end = resolve_date_range(f"{from_text} to {to_text}".strip(), today=today)
    if not start:
        start = resolve_date_phrase(from_text, today=today)
        end = resolve_date_phrase(to_text, today=today) or start
    if not start or not end:
        return {
            "error": pick_locale_text(
                locale,
                english="Those dates could not be read. Fill From and To separately.",
                roman="Dates samajh nahi aayin. From aur To alag bharain.",
                urdu="تاریخ سمجھی نہیں گئی۔ From اور To الگ بھریں۔",
                mix="Dates samajh nahi aayin. Fill From and To separately.",
            )
        }
    if end < start:
        end = start
    draft["start_date"] = start
    draft["end_date"] = end
    draft["days_count"] = (end - start).days + 1
    draft["range_complete"] = True
    draft["reason"] = str(reason or "").strip()
    if attachments is not None:
        from app.discord.attachments import format_reason_with_files

        draft["attachments"] = list(attachments)
        draft["reason"] = format_reason_with_files(draft["reason"], attachments)
    # A half day only applies to a single-day booking.
    draft["half_day"] = normalize_half_day(half_day) if start == end else ""
    if draft["half_day"]:
        draft["days_count"] = 0.5
    payload = _confirm_payload(draft, locale) if _leave_submit_ready(draft) else _form_payload(draft, locale)
    agent._remember(key, draft)
    return payload


def _confirm_preview(draft, locale):
    days = (draft["end_date"] - draft["start_date"]).days + 1
    confirm = pick_locale_text(
        locale,
        english=CONFIRM_LEAVE,
        roman=CONFIRM_LEAVE_ROMAN,
        urdu="HR کو تبھی بھیجوں گا جب آپ تصدیق کریں۔\n\nمنظوری کے لیے **ہاں**، منسوخ کے لیے **نہیں** لکھیں۔",
        mix="HR ko tabhi bhejunga jab aap confirm karein.\n\nReply **haan/yes** to submit, **nahi/no** to cancel.",
    )
    header = pick_locale_text(
        locale,
        english="Please verify this before I send it to HR.",
        roman="HR ko bhejne se pehle verify karo.",
        urdu="HR کو بھیجنے سے پہلے تصدیق کریں۔",
        mix="HR ko bhejne se pehle verify karo / please verify this.",
    )
    return (
        f"{header}\n\n"
        f"Type: {draft['leave_type']}\n"
        f"Dates: {draft['start_date'].isoformat()} to {draft['end_date'].isoformat()}\n"
        f"Days: {days}\n\n"
        f"{confirm}"
    )


def _leave_employee_name(snapshot):
    emp = (snapshot or {}).get("employee") or {}
    return str(emp.get("name") or "").strip()


def _leave_balance_result(snapshot):
    return {
        "answer": (snapshot or {}).get("text") or "",
        "fallback": False,
        "chunks": [],
        "ui": "leave_balance",
        "employeeName": _leave_employee_name(snapshot),
    }


def _hr_mention(config):
    role_id = str((config.get("hr") or {}).get("hrRoleId") or "").strip()
    if role_id:
        return f"<@&{role_id}>"
    return ""


def user_error_text(error, fallback):
    if isinstance(error, AppError) and error.expose:
        return str(error)
    return fallback


def format_agent_reply(result):
    return format_support_reply(result["answer"], result.get("chunks") or [], result.get("fallback"))
