"""Turn raw bank descriptions into display merchant names (FR-TXN-06). Rules can override."""
import re
from string import capwords

_PREFIX = re.compile(
    r"^(?:SQ ?\*|TST\* ?|PAYPAL ?\*|PP\*|POS DEBIT |POS |DEBIT CARD PURCHASE ?-? ?|CHECKCARD \d* ?"
    r"|ACH (?:DEBIT |CREDIT )?|PURCHASE AUTHORIZED ON \d{2}/\d{2} "
    r"|APLPAY |UEP\*|JMS\*|WF\* ?|CL \*|SP |EHS\* ?|YSI\*|KPAY\*)+",
    re.IGNORECASE,
)
_TRAILING = (
    re.compile(r"\s*\*\s+[A-Z]{2}$"),  # "LAWSON * JP": processor star + country code
    re.compile(r"\s+#?\d{3,}\b.*$"),  # store/reference numbers and anything after them
    re.compile(r"\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?\b.*$"),  # dates
    re.compile(r"\s+X{2,}\d+.*$", re.IGNORECASE),  # masked card numbers
)
_STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
    "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)


def clean(raw_description: str, raw_payee: str | None = None) -> str:
    text = (raw_payee or "").strip() or raw_description.strip()
    text = _PREFIX.sub("", text).strip()
    for pattern in _TRAILING:
        text = pattern.sub("", text)
    words = text.split()
    if len(words) >= 3 and words[-1].upper() in _STATES:
        # shortcut: drops a one-word city before the state; multi-word cities leave a fragment. Fix with a set_merchant rule.
        words = words[:-2]
    text = " ".join(words).strip(" -*#")
    return capwords(text) if text else raw_description.strip()
