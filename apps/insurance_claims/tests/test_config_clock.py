from datetime import date

import pytest
from agent.clock import FixedClock, SystemClock, clock_from_settings, deadline_facts
from agent.config import ConfigError, Settings


def test_fixed_clock_returns_its_value():
    assert FixedClock(date(2026, 3, 5)).today() == date(2026, 3, 5)


def test_system_clock_returns_real_today():
    assert SystemClock().today() == date.today()


def test_clock_from_settings_uses_as_of_date_when_provided():
    clock = clock_from_settings(Settings(as_of_date=date(2026, 3, 5)))
    assert isinstance(clock, FixedClock)
    assert clock.today() == date(2026, 3, 5)


def test_clock_from_settings_falls_back_to_system_date():
    assert isinstance(clock_from_settings(Settings()), SystemClock)


def test_deadline_before():
    facts = deadline_facts(date(2026, 3, 18), FixedClock(date(2026, 3, 5)))
    assert facts.deadline_passed is False
    assert facts.days_until_appeal_deadline == 13
    assert facts.days_past_deadline is None


def test_deadline_day_itself_is_not_passed():
    facts = deadline_facts(date(2026, 3, 18), FixedClock(date(2026, 3, 18)))
    assert facts.deadline_passed is False
    assert facts.days_until_appeal_deadline == 0


def test_deadline_after():
    facts = deadline_facts(date(2026, 3, 18), FixedClock(date(2026, 3, 19)))
    assert facts.deadline_passed is True
    assert facts.days_until_appeal_deadline is None
    assert facts.days_past_deadline == 1


def test_no_deadline_gives_no_facts():
    assert deadline_facts(None, FixedClock(date(2026, 3, 5))) is None


def test_settings_defaults_are_safe():
    s = Settings()
    assert s.enable_debug_inspector is False
    assert s.as_of_date is None
    assert s.min_factors == 3
    assert s.fixtures_dir.name == "fixtures"
    assert s.llm_configured is False


def test_from_env_overrides_and_parses():
    s = Settings.from_env(
        {
            "LLM_API_KEY": "abc",
            "AS_OF_DATE": "2026-03-05",
            "ENABLE_DEBUG_INSPECTOR": "TRUE",
            "CONSENT_SCENARIO": "timeout",
            "MAX_OOS_STRIKES": "4",
        }
    )
    assert s.llm_configured is True
    assert s.as_of_date == date(2026, 3, 5)
    assert s.enable_debug_inspector is True
    assert s.consent_scenario == "timeout"
    assert s.max_oos_strikes == 4


def test_blank_env_values_mean_unset():
    s = Settings.from_env({"LLM_API_KEY": "", "AS_OF_DATE": "  ", "LLM_MODEL": ""})
    assert s.llm_api_key is None
    assert s.as_of_date is None
    assert s.llm_model == Settings().llm_model


def test_invalid_date_is_a_clear_error():
    with pytest.raises(ConfigError, match="AS_OF_DATE"):
        Settings.from_env({"AS_OF_DATE": "05/03/2026"})


def test_invalid_bool_and_int_are_clear_errors():
    with pytest.raises(ConfigError, match="ENABLE_DEBUG_INSPECTOR"):
        Settings.from_env({"ENABLE_DEBUG_INSPECTOR": "maybe"})
    with pytest.raises(ConfigError, match="MAX_CASE_LOOPS"):
        Settings.from_env({"MAX_CASE_LOOPS": "lots"})


def test_config_cannot_weaken_the_three_factor_gate():
    with pytest.raises(ValueError):
        Settings.from_env({"MIN_FACTORS": "2"})
