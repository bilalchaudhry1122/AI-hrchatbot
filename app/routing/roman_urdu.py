import re

ROMAN_URDU_HINT = re.compile(
    r"\b("
    r"kya|kia|hai|hain|meri|mera|mere|meray|merey|mujhe|mujhy|mujhai|mughe|apni|apki|aap|kitna|kitni|kitne|"
    r"paas|batao|btao|"
    r"chahiye|chahye|chahiyay|chutti|chuttian|chuttyan|kal|aaj|parson|"
    r"baqi|baqaya|bachi|bacha|salana|saalana|bimar|bimari|"
    r"han|haan|ji|theek|nahi|nahin|nahee|darkhwast|apply karo|apply karna|"
    r"bhai|yaar|plz|plzz|"
    # Words that appear in almost every Roman Urdu sentence. Without these,
    # "main kaun hoon" and "ghar se kaam kar sakta hoon" contained no
    # recognised token at all and were answered in English.
    r"hoon|hun|houn|ho?on|"
    r"sakta|sakti|sakte|sakoon|"
    r"karta|karti|karte|karna|karni|karun|karoon|"
    r"kaun|kaunsa|kaunsi|kaunse|kab|kahan|kahaan|kyun|kyu|kyon|"
    r"kaise|kaisay|kaisi|kese|kesay|kesi|"
    r"milta|milti|milte|milega|milegi|"
    r"lena|leni|lene|dena|deni|dene|"
    r"hoga|hogi|honge|hota|hoti|hote|"
    r"raha|rahi|rahe|rahega|rahegi|"
    r"wapas|wapis|zarurat|zaroori|zaruri|"
    r"abhi|phir|dobara|dubara|"
    r"yeh|woh|humein|hamein|tumhe|tumhein|"
    r"waqt|subah|shaam|mahina|mahine|hafta|hafte|"
    r"tankhwah|tankhah|naukri|nokri|daftar|hazri|mulazim|izafa|"
    r"bataye|bataen|batao|btao|bataiye|poochh|poochhna|pata|"
    r"acha|achha|bilkul|shukriya|shukria"
    r")\b",
    re.I,
)

_NORMALIZE = (
    (re.compile(r"\bmujhai\b|\bmujhey\b|\bmujhy\b|\bmjhe\b|\bmujhko\b|\bmughe\b|\bmughey\b", re.I), "mujhe"),
    (re.compile(r"\bmeray\b|\bmerey\b|\bmray\b|\bmerae\b", re.I), "mere"),
    (re.compile(r"\bmere (pass|pas)\b", re.I), "mere paas"),
    (re.compile(r"\bmeri (pass|pas)\b", re.I), "meri paas"),
    (re.compile(r"\bnhi\b|\bnahe\b|\bnhii\b|\bnahee\b", re.I), "nahi"),
    (re.compile(r"\bkrna\b|\bkrne\b|\bkarnae\b", re.I), "karna"),
    (re.compile(r"\bkrdo\b", re.I), "kar do"),
    (re.compile(r"\bchahiyay\b|\bchahiyein\b|\bchahiey\b|\bchahie\b|\bchaiye\b|\bchahye\b|\bchahiyae\b", re.I), "chahiye"),
    (re.compile(r"\bchuttiyan\b|\bchuttian\b|\bchuttyan\b|\bchuti\b|\bchutty\b", re.I), "chutti"),
    (re.compile(r"\bleaves\b|\bleav\b|\bleavee\b", re.I), "leave"),
    (re.compile(r"\bsaalana\b|\bsalana\b", re.I), "annual"),
    (re.compile(r"\banual\b", re.I), "annual"),
    (re.compile(r"\bbimari\b|\bbemar\b", re.I), "bimar"),
)


def normalize_leave_text(text):
    raw = str(text or "")
    for pattern, repl in _NORMALIZE:
        raw = pattern.sub(repl, raw)
    return raw


def is_roman_urdu(text):
    blob = str(text or "")
    return bool(ROMAN_URDU_HINT.search(blob) or ROMAN_URDU_HINT.search(normalize_leave_text(blob)))


def prefer_roman(question, *more):
    blob = " ".join(str(item or "") for item in (question,) + more)
    return is_roman_urdu(blob)
