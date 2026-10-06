"""Runtime configuration: pure parsing of environment variables, no I/O or side effects."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from pydantic import BaseModel, field_validator

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

_STR_FIELDS = {
    "LLM_PROVIDER": "llm_provider",
    "LLM_API_KEY": "llm_api_key",
    "LLM_MODEL": "llm_model",
    "LLM_MODEL_FAST": "llm_model_fast",
    "CONSENT_SCENARIO": "consent_scenario",
}

_INT_FIELDS = {
    "MIN_FACTORS": "min_factors",
    "MAX_MISMATCHES": "max_mismatches",
    "MAX_VERIFICATION_REFUSALS": "max_verification_refusals",
    "MAX_OOS_STRIKES": "max_oos_strikes",
    "MAX_FRUSTRATION_STREAK": "max_frustration_streak",
    "MAX_CONSENT_POLLS": "max_consent_polls",
    "MAX_CASE_LOOPS": "max_case_loops",
}


class ConfigError(ValueError):
    """Raised when an environment variable has an unusable value."""


class Settings(BaseModel):
    # LLM
    llm_provider: str = "anthropic"
    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-5-5"
    llm_model_fast: str = "claude-haiku-4-5-20251001"

    # Data
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR

    # Clock: optional fixed "today" for deterministic tests/demos; real date when None.
    as_of_date: date | None = None

    # Evaluator/development tooling. Off unless explicitly enabled.
    enable_debug_inspector: bool = False
    consent_scenario: str = "default"

    # SOP thresholds (live in config, never in prompts)
    min_factors: int = 3
    max_mismatches: int = 3
    max_verification_refusals: int = 2
    max_oos_strikes: int = 2
    max_frustration_streak: int = 3
    max_consent_polls: int = 5
    max_case_loops: int = 3

    @field_validator("min_factors")
    @classmethod
    def _min_factors_floor(cls, value: int) -> int:
        # The SOP requires at least three PII factors; config must not weaken the gate.
        if value < 3:
            raise ValueError("min_factors must be >= 3 (SOP requires at least three PII factors)")
        return value

    @field_validator(
        "max_mismatches",
        "max_verification_refusals",
        "max_oos_strikes",
        "max_frustration_streak",
        "max_consent_polls",
        "max_case_loops",
    )
    @classmethod
    def _positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("thresholds must be >= 1")
        return value

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env

        def get(name: str) -> str | None:
            raw = source.get(name)
            if raw is None:
                return None
            raw = raw.strip()
            return raw or None  # blank values (e.g. "LLM_API_KEY=") mean "unset"

        values: dict[str, object] = {}

        for env_name, field in _STR_FIELDS.items():
            value = get(env_name)
            if value is not None:
                values[field] = value

        fixtures = get("FIXTURES_DIR")
        if fixtures is not None:
            values["fixtures_dir"] = Path(fixtures).expanduser()

        as_of = get("AS_OF_DATE")
        if as_of is not None:
            try:
                values["as_of_date"] = date.fromisoformat(as_of)
            except ValueError as exc:
                raise ConfigError(f"AS_OF_DATE must be YYYY-MM-DD, got {as_of!r}") from exc

        inspector = get("ENABLE_DEBUG_INSPECTOR")
        if inspector is not None:
            lowered = inspector.lower()
            if lowered in _TRUE:
                values["enable_debug_inspector"] = True
            elif lowered in _FALSE:
                values["enable_debug_inspector"] = False
            else:
                raise ConfigError(f"ENABLE_DEBUG_INSPECTOR must be true/false, got {inspector!r}")

        for env_name, field in _INT_FIELDS.items():
            value = get(env_name)
            if value is not None:
                try:
                    values[field] = int(value)
                except ValueError as exc:
                    raise ConfigError(f"{env_name} must be an integer, got {value!r}") from exc

        return cls(**values)
