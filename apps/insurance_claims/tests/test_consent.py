import pytest
from agent.consent import ConsentGateway, classify
from agent.fixtures import FixtureError
from agent.state import ConsentState


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("approved", ConsentState.APPROVED),
        (" Approved ", ConsentState.APPROVED),
        ("granted", ConsentState.APPROVED),
        ("denied", ConsentState.DENIED),
        ("declined", ConsentState.DENIED),
        ("pending", ConsentState.PENDING),
        ("something-unexpected", ConsentState.PENDING),
    ],
)
def test_status_classification_fails_closed(raw, expected):
    assert classify(raw) == expected


def test_default_scenario_approves_on_the_second_poll(store):
    outcome = ConsentGateway.from_store(store, "default", 5).run("P9")
    assert outcome.state == ConsentState.APPROVED
    assert outcome.trail == ["pending", "approved"]


def test_timeout_scenario_times_out_after_max_polls(store):
    outcome = ConsentGateway.from_store(store, "timeout", 5).run("P9")
    assert outcome.state == ConsentState.TIMED_OUT
    assert outcome.trail == ["pending"] * 5


def test_approval_that_arrives_after_the_poll_budget_is_too_late():
    sequence = ["pending", "pending", "approved"]
    assert ConsentGateway(sequence, "custom", 2).run("P9").state == ConsentState.TIMED_OUT
    assert ConsentGateway(sequence, "custom", 3).run("P9").state == ConsentState.APPROVED


def test_denial_is_terminal():
    outcome = ConsentGateway(["pending", "denied", "approved"], "custom", 5).run("P9")
    assert outcome.state == ConsentState.DENIED
    assert outcome.trail == ["pending", "denied"]


def test_empty_sequence_times_out():
    assert ConsentGateway([], "custom", 3).run("P9").state == ConsentState.TIMED_OUT


def test_each_request_starts_from_the_beginning(store):
    gateway = ConsentGateway.from_store(store, "default", 5)
    assert gateway.run("P9").trail == gateway.run("P9").trail


def test_unknown_scenario_fails_at_startup(store):
    with pytest.raises(FixtureError, match="unknown consent scenario"):
        ConsentGateway.from_store(store, "nope", 5)
