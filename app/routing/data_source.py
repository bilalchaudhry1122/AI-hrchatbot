"""Where an answer is fetched from. Intent is chosen first; this map is the store.

MySQL (ticket owner Discord User ID only — never another employee):
  LEAVE_BALANCE  my/apni/meri leave, remaining, quota, “do I have”
  LEAVE_REQUEST  apply / chahiye / confirm (writes PENDING)

Pinecone handbook (company rules, not this person's live numbers):
  POLICY         policy, handbook, entitled, how many leaves are allowed/there, company allowance
  GENERAL        other knowledge questions

Both (one message that asks for rules AND this person's remaining days):
  MIXED

Discord only:
  HUMAN_HR       speak to HR, salary/appraisal, WFH approve (mention HR_ROLE_ID, not Staff)
  CLARIFY        ambiguous leave — ask, do not write the database
"""

PINECONE = "pinecone"
MYSQL = "mysql"
BOTH = "pinecone+mysql"
DISCORD = "discord"

SOURCE_BY_INTENT = {
    "LEAVE_BALANCE": MYSQL,
    "ATTENDANCE": PINECONE,
    "LEAVE_REQUEST": MYSQL,
    "POLICY": PINECONE,
    "GENERAL": PINECONE,
    "MIXED": BOTH,
    "HUMAN_HR": DISCORD,
    "CLARIFY": DISCORD,
}


def source_for_intent(intent):
    return SOURCE_BY_INTENT.get(intent, PINECONE)
