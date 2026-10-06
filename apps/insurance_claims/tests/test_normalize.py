import pytest
from agent.normalize import (
    name_key,
    normalize_dob,
    normalize_email,
    normalize_factor,
    normalize_id_last4,
    normalize_phone,
)


def test_name_key_ignores_case_order_punctuation_titles_and_initials():
    expected = name_key("Margaret Chen")
    assert expected is not None
    for variant in (
        "margaret chen",
        "MARGARET   CHEN",
        "Chen, Margaret",
        "Margaret A. Chen",
        "Ms. Margaret Chen",
    ):
        assert name_key(variant) == expected


def test_name_key_folds_diacritics_and_apostrophes():
    assert name_key("José Pérez") == name_key("Jose Perez")
    assert name_key("Sean O'Brien") == name_key("Sean OBrien")


def test_name_key_requires_a_full_name():
    assert name_key("Margaret") is None
    assert name_key("") is None
    assert name_key("Mr.") is None


def test_name_key_handles_non_latin_names():
    assert name_key("李 雅") is not None


def test_different_names_have_different_keys():
    assert name_key("Margaret Chen") != name_key("David Chen")
    assert name_key("Ya Wen Li") != name_key("Yaven Li")  # alias handled by the fixture, not fuzz


@pytest.mark.parametrize(
    "text",
    [
        "1985-03-15",
        "1985/03/15",
        "03/15/1985",
        "March 15, 1985",
        "15 March 1985",
        "Mar 15th 1985",
    ],
)
def test_dob_formats_normalize_to_iso(text):
    assert normalize_dob(text) == "1985-03-15"


def test_ambiguous_numeric_dob_reads_as_us_month_day():
    assert normalize_dob("03/04/1985") == "1985-03-04"


@pytest.mark.parametrize("text", ["", "banana", "1985-13-45", "March 1985", "03/15/85", "1985"])
def test_unusable_dob_is_none(text):
    assert normalize_dob(text) is None


@pytest.mark.parametrize(
    "text", ["+16505212836", "(650) 521-2836", "650.521.2836", "1-650-521-2836", "6505212836"]
)
def test_phone_formats_normalize_to_ten_digits(text):
    assert normalize_phone(text) == "6505212836"


@pytest.mark.parametrize("text", ["2836", "650 521", "", "call me"])
def test_partial_phone_is_not_usable(text):
    assert normalize_phone(text) is None


def test_near_identical_phones_stay_different():
    assert normalize_phone("+16505212836") != normalize_phone("+16505212830")


def test_email_normalization():
    assert normalize_email(" Margaret@Email.com ") == "margaret@email.com"
    assert normalize_email("mailto:a@b.co") == "a@b.co"
    assert normalize_email("<a@b.co>") == "a@b.co"
    assert normalize_email("not an email") is None
    assert normalize_email("a@b") is None


def test_id_last4_must_be_exactly_four_digits():
    assert normalize_id_last4("4472") == "4472"
    assert normalize_id_last4("4-4-7-2") == "4472"
    assert normalize_id_last4("447") is None
    assert normalize_id_last4("123-45-6789") is None  # a full SSN is not a last-four


def test_normalize_factor_dispatch():
    assert normalize_factor("dob", "March 15, 1985") == "1985-03-15"
    assert normalize_factor("phone", "(650) 521-2836") == "6505212836"
    assert normalize_factor("id_last4", "abc") is None
