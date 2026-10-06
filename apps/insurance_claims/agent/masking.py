"""PII masking for logs, audit events and the evaluator inspector.

An ID last-four is fully masked: four digits is the entire secret, so showing any of it
would reveal it.
"""

from __future__ import annotations

import re


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def mask_id_last4(value: str) -> str:
    return "****"


def mask_dob(value: str) -> str:
    return "****-**-**"


def mask_phone(value: str) -> str:
    digits = _digits(value)
    return f"***-***-{digits[-4:]}" if len(digits) >= 4 else "***-***-****"


def mask_email(value: str) -> str:
    local, sep, domain = value.partition("@")
    if not sep or not local:
        return "***"
    return f"{local[0]}***@{domain}"


def mask_name(value: str) -> str:
    tokens = [t for t in value.split() if t]
    return " ".join(f"{t[0]}***" for t in tokens) if tokens else "***"


def mask_policy(value: str) -> str:
    return re.sub(r"\d", "*", value)


_KIND_BY_KEY = {
    "full_name": mask_name,
    "rep_name": mask_name,
    "name": mask_name,
    "dob": mask_dob,
    "phone": mask_phone,
    "email": mask_email,
    "alt_email": mask_email,
    "email_address": mask_email,
    "id_last4": mask_id_last4,
    "ssn": mask_id_last4,
    "ssn_last4": mask_id_last4,
    "policy_number": mask_policy,
}

PII_KEYS = frozenset(_KIND_BY_KEY)


def mask_value(key: str, value: str) -> str:
    """Mask `value` according to what `key` holds; unknown keys are fully masked."""
    return _KIND_BY_KEY.get(key, lambda _v: "***")(value)
