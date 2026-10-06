"""Deterministic pre-pass over a customer message.

Cheap, predictable extraction that does not depend on the LLM: emails, phone numbers, dates of
birth, ID last-fours, policy numbers, and which kind of ID the caller named. Values are
validated by the same normalizers the verifier uses. It also converts spoken forms ("four four
seven two", "margaret at email dot com") so voice-style input works.

Names and everything semantic are left to the LLM. Where both have an opinion about an
identity value, this pre-pass wins, and LLM-only values must be grounded in the message text.
Spoken dates are the LLM's job; they are checked separately in `understanding.py`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .normalize import normalize_dob, normalize_email, normalize_id_last4, normalize_phone

IdKind = Literal["ssn", "national_id", "unspecified"]

_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
_WORD_ALT = "|".join(_DIGIT_WORDS)
# Two or more digit words in a row ("four four seven two"); a lone "one" is left alone.
_SPOKEN_DIGITS = re.compile(rf"\b(?:{_WORD_ALT})(?:[\s,\-]+(?:{_WORD_ALT}))+\b", re.IGNORECASE)

_DOT = re.compile(r"\s+dot\s+", re.IGNORECASE)
_LABEL = r"[A-Za-z0-9][A-Za-z0-9_\-]*"
_SPOKEN_EMAIL = re.compile(
    rf"\b({_LABEL}(?:(?:\.|\s+dot\s+){_LABEL})*)\s+at\s+({_LABEL}(?:\s+dot\s+{_LABEL})+)",
    re.IGNORECASE,
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(
    r"(?<!\d)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"
)

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_DATE_PATTERNS = (
    re.compile(r"(?<!\d)\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?!\d)"),
    re.compile(r"(?<!\d)\d{1,2}[-/.]\d{1,2}[-/.]\d{4}(?!\d)"),
    re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(
        rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH}\.?,?\s+\d{{4}}\b", re.IGNORECASE
    ),
)
_DOB_CUE = re.compile(
    r"\bdob\b|d\.o\.b|date of birth|birth\s*date|birthday|\bborn\b", re.IGNORECASE
)

_ID_CUE = (
    r"(?:\bssn\b|social(?:\s+security)?(?:\s+number)?"
    r"|national\s*id(?:entity|entification)?(?:\s+number)?|\bnid\b"
    r"|last\s*(?:4|four)(?:\s+digits)?|(?:id|number)\s+(?:ends?|ending)\s+(?:in|with))"
)
_ID_VALUE = re.compile(
    rf"{_ID_CUE}(?P<gap>[^\d]{{0,40}}?)(?<!\d)(?P<digits>\d{{4}})(?!\d)", re.IGNORECASE
)
_LOOSE_ID_CUE = re.compile(_ID_CUE + r"|\bid\b|identification|\bsecurity\b", re.IGNORECASE)
_NOT_ID_GAP = re.compile(
    r"\b(?:phone|cell|mobile|policy|claim|zip|date|dob|birth)\b", re.IGNORECASE
)
_BARE_ID = re.compile(r"(?:(?:it'?s|its|it is|that'?s|that is)\s+)?(\d{4})[.!]?")

_SSN_WORDS = re.compile(r"\bssn\b|social\s+security|\bsocial\b", re.IGNORECASE)
_NATIONAL_WORDS = re.compile(r"national\s*(?:id|identity|identification)|\bnid\b", re.IGNORECASE)


@dataclass(frozen=True)
class Prepass:
    dob: str | None = None  # ISO date
    phone: str | None = None  # 10+ digits
    email: str | None = None  # lowercase
    id_last4: str | None = None
    policy_number: str | None = None
    id_kind_hint: IdKind | None = None  # named in the text; None if no ID type was mentioned


def spoken_to_written(text: str) -> str:
    """Turn 'four four seven two' into '4472' and 'a at b dot com' into 'a@b.com'."""

    def email(match: re.Match[str]) -> str:
        return f"{_DOT.sub('.', match.group(1))}@{_DOT.sub('.', match.group(2))}"

    def digits(match: re.Match[str]) -> str:
        words = re.findall(r"[A-Za-z]+", match.group(0))
        return "".join(_DIGIT_WORDS[word.lower()] for word in words)

    return _SPOKEN_DIGITS.sub(digits, _SPOKEN_EMAIL.sub(email, text))


def has_loose_id_cue(text: str) -> bool:
    """True if the text mentions an ID, SSN, national ID or 'last four'."""
    return _LOOSE_ID_CUE.search(text) is not None


def id_kind_from_text(text: str) -> IdKind | None:
    ssn = _SSN_WORDS.search(text) is not None
    national = _NATIONAL_WORDS.search(text) is not None
    if ssn and national:
        return "unspecified"
    if ssn:
        return "ssn"
    if national:
        return "national_id"
    return None


def _find_email(text: str) -> str | None:
    for match in _EMAIL.finditer(text):
        value = normalize_email(match.group(0))
        if value:
            return value
    return None


def _find_phone(text: str) -> str | None:
    for match in _PHONE.finditer(text):
        value = normalize_phone(match.group(0))
        if value:
            return value
    return None


def _find_dob(text: str, expected: Sequence[str]) -> str | None:
    """A date counts as the DOB only with a cue ("DOB is", "born") just before it, or when
    the agent just asked for the DOB and there is exactly one date. A claim date must not be
    mistaken for a birth date."""
    candidates: list[tuple[int, str]] = []
    for pattern in _DATE_PATTERNS:
        for match in pattern.finditer(text):
            iso = normalize_dob(match.group(0))
            if iso:
                candidates.append((match.start(), iso))
    candidates.sort()
    for start, iso in candidates:
        if _DOB_CUE.search(text[max(0, start - 30) : start]):
            return iso
    if "dob" in expected and len(candidates) == 1:
        return candidates[0][1]
    return None


def _find_id(text: str, expected: Sequence[str]) -> str | None:
    for match in _ID_VALUE.finditer(text):
        if _NOT_ID_GAP.search(match.group("gap")):
            continue  # e.g. "the last four of my phone number is ..."
        value = normalize_id_last4(match.group("digits"))
        if value:
            return value
    if "id_last4" in expected:
        bare = _BARE_ID.fullmatch(text.strip().lower())
        if bare:
            return normalize_id_last4(bare.group(1))
    return None


def _find_policy(text: str, prefixes: Sequence[str]) -> str | None:
    for prefix in prefixes:
        match = re.search(rf"\b{re.escape(prefix)}[-\s#:]?(\d{{3,10}})\b", text, re.IGNORECASE)
        if match:
            return f"{prefix.upper()}-{match.group(1)}"
    return None


def prepass(
    text: str, *, expected_fields: Sequence[str] = (), policy_prefixes: Sequence[str] = ()
) -> Prepass:
    written = spoken_to_written(text)
    return Prepass(
        dob=_find_dob(written, expected_fields),
        phone=_find_phone(written),
        email=_find_email(written),
        id_last4=_find_id(written, expected_fields),
        policy_number=_find_policy(written, policy_prefixes),
        id_kind_hint=id_kind_from_text(written),
    )


REDACTED = "[redacted]"


def redact(text: str, policy_prefixes: Sequence[str] = ()) -> str:
    """Blank out identity values (emails, phones, dates, ID last-fours, policy numbers) so a
    message can be shown to the model without them. Spoken digits are converted first, so
    they are caught too. Everything else, including claim numbers, is left as written."""
    out = spoken_to_written(text)
    out = _EMAIL.sub(REDACTED, out)
    out = _PHONE.sub(REDACTED, out)
    for pattern in _DATE_PATTERNS:
        out = pattern.sub(REDACTED, out)

    def blank_digits(match: re.Match[str]) -> str:
        whole = match.group(0)
        start = match.start("digits") - match.start()
        end = match.end("digits") - match.start()
        return whole[:start] + REDACTED + whole[end:]

    out = _ID_VALUE.sub(blank_digits, out)
    for prefix in policy_prefixes:
        policy_pattern = rf"\b{re.escape(prefix)}[-\s#:]?\d{{3,10}}\b"
        out = re.sub(policy_pattern, REDACTED, out, flags=re.IGNORECASE)
    return out
