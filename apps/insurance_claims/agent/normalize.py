"""Pure normalizers for the five verification factors.

Matching is exact after normalization. There is deliberately no fuzzy matching: the sample
data contains two phone numbers one digit apart, and fuzziness would weaken the gate.
A normalizer returns None when a value is not a usable instance of that factor, for example
a phone number with fewer than 10 digits. Unusable values count as "not provided", never as
a wrong guess.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from dateutil import parser as date_parser

_TITLES = frozenset({"mr", "mrs", "ms", "miss", "dr", "prof"})
_SENTINEL_A = datetime(2000, 1, 1)
_SENTINEL_B = datetime(2001, 2, 2)
_FOUR_DIGIT_YEAR = re.compile(r"(?<!\d)\d{4}(?!\d)")
_EMAIL = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


def _strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def fold(text: str) -> str:
    """Casefold and strip diacritics, for comparing what a caller wrote against names."""
    return _strip_marks(text).casefold()


def name_tokens(value: str) -> list[str]:
    text = _strip_marks(value).casefold()
    if "," in text:  # "Chen, Margaret" -> "margaret chen"
        last, _, first = text.partition(",")
        text = f"{first} {last}"
    text = text.replace("'", "").replace("\u2019", "")
    text = re.sub(r"[^\w\s]", " ", text).replace("_", " ")
    tokens: list[str] = []
    for token in text.split():
        if token in _TITLES:
            continue
        if len(token) == 1 and token.isascii():  # middle initials
            continue
        tokens.append(token)
    return tokens


def name_key(value: str) -> str | None:
    """Order-insensitive key. At least two name tokens are required (a full name)."""
    tokens = name_tokens(value)
    if len(tokens) < 2:
        return None
    return " ".join(sorted(tokens))


def normalize_dob(value: str) -> str | None:
    """Return an ISO date, or None. An explicit 4-digit year and a full date are required.
    Ambiguous numeric dates such as 03/04/1985 are read as US month/day."""
    text = value.strip()
    if not text or not _FOUR_DIGIT_YEAR.search(text):
        return None
    try:
        first = date_parser.parse(text, default=_SENTINEL_A, dayfirst=False)
        second = date_parser.parse(text, default=_SENTINEL_B, dayfirst=False)
    except (ValueError, OverflowError):
        return None
    if first != second:  # a component was missing and filled in from the default
        return None
    if first.year < 1900:
        return None
    return first.date().isoformat()


def normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) >= 10 else None


def normalize_email(value: str) -> str | None:
    text = value.strip().strip("<>").lower()
    if text.startswith("mailto:"):
        text = text[len("mailto:") :]
    return text if _EMAIL.match(text) else None


def normalize_id_last4(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    return digits if len(digits) == 4 else None


_NORMALIZERS = {
    "full_name": name_key,
    "dob": normalize_dob,
    "phone": normalize_phone,
    "email": normalize_email,
    "id_last4": normalize_id_last4,
}


def normalize_factor(factor: str, value: str) -> str | None:
    """Canonical comparable form of a factor value, or None if it is not usable."""
    return _NORMALIZERS[factor](value)
