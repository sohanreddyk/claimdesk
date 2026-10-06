import pytest
from agent.prepass import id_kind_from_text, prepass, spoken_to_written

MARGARET_MSG = (
    "I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my "
    "denied healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472."
)


def test_margaret_message_pre_pass():
    result = prepass(MARGARET_MSG, policy_prefixes=("POL",))
    assert result.dob == "1985-03-15"
    assert result.id_last4 == "4472"
    assert result.policy_number == "POL-9921"
    assert result.id_kind_hint == "ssn"
    assert result.phone is None and result.email is None


# ---- spoken forms ---------------------------------------------------------------------


def test_spoken_digit_runs_become_digits_but_lone_words_do_not():
    assert spoken_to_written("four four seven two") == "4472"
    assert spoken_to_written("it is four-four-seven-two") == "it is 4472"
    assert spoken_to_written("I have one more question and two claims") == (
        "I have one more question and two claims"
    )


def test_spoken_email_is_converted():
    assert spoken_to_written("my email is margaret at email dot com") == (
        "my email is margaret@email.com"
    )
    assert spoken_to_written("margaret dot chen at mail dot example dot com") == (
        "margaret.chen@mail.example.com"
    )


# ---- ID last four -----------------------------------------------------------------------


@pytest.mark.parametrize("text", ["4472", "it's 4472", "It's 4472.", "four four seven two"])
def test_bare_answer_is_an_id_only_when_the_agent_just_asked_for_it(text):
    assert prepass(text, expected_fields=("id_last4",)).id_last4 == "4472"
    assert prepass(text).id_last4 is None


def test_last_four_of_a_phone_number_is_not_an_id():
    assert prepass("the last four of my phone number is 2836").id_last4 is None


def test_last_four_of_an_ssn_is_an_id():
    assert prepass("the last four of my SSN are 4472").id_last4 == "4472"
    assert prepass("my national ID ends in 6688").id_last4 == "6688"


def test_a_full_ssn_is_never_taken():
    assert prepass("my ssn is 123-45-6789").id_last4 is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("my SSN", "ssn"),
        ("social security", "ssn"),
        ("my national ID", "national_id"),
        ("SSN or national ID", "unspecified"),
        ("hello there", None),
    ],
)
def test_id_kind_comes_from_keywords(text, expected):
    assert id_kind_from_text(text) == expected


# ---- phone, email, DOB, policy -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "my number is (650) 521-2836",
        "call +16505212836",
        "it's 650.521.2836",
        "1-650-521-2836",
        "six five zero five two one two eight three six",
    ],
)
def test_phone_formats(text):
    assert prepass(text).phone == "6505212836"


def test_dates_and_short_digit_runs_are_not_phones():
    assert prepass("born 1985-03-15, policy 9921").phone is None


def test_dob_and_phone_together():
    result = prepass("I was born 1985-03-15 and my number is (650) 521-2836")
    assert result.dob == "1985-03-15"
    assert result.phone == "6505212836"


def test_a_claim_date_is_not_a_dob():
    assert prepass("my claim from 2026-01-12 was denied").dob is None


def test_a_lone_date_is_a_dob_when_the_agent_just_asked_for_it():
    assert prepass("2026-01-12", expected_fields=("dob",)).dob == "2026-01-12"
    assert prepass("2026-01-12").dob is None


@pytest.mark.parametrize(
    "text",
    [
        "my date of birth is March 15, 1985",
        "DOB: 03/15/1985",
        "I was born on the 15th of March 1985",
    ],
)
def test_dob_formats_with_a_cue(text):
    assert prepass(text).dob == "1985-03-15"


def test_emails_plain_and_spoken():
    assert prepass("it is Margaret@Email.com.").email == "margaret@email.com"
    assert prepass("my email is margaret at email dot com").email == "margaret@email.com"
    assert prepass("no address here").email is None


def test_policy_numbers_use_known_prefixes_only():
    assert prepass("pol 9921", policy_prefixes=("POL",)).policy_number == "POL-9921"
    assert prepass("claim CL-2048", policy_prefixes=("POL",)).policy_number is None
    assert prepass("POL-9921").policy_number is None  # no prefixes known
