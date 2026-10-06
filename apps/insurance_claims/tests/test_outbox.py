import pytest
from agent.outbox import EmailSendError, FailingSender, Outbox, SentEmail


def email(session="s1", to="margaret@email.com", subject="Summary", body="Hello"):
    return SentEmail(session_id=session, to=to, subject=subject, body=body)


def test_the_outbox_collects_emails_in_order():
    outbox = Outbox()
    first, second = email(subject="one"), email(session="s2", subject="two")
    outbox.send(first)
    outbox.send(second)
    assert outbox.sent() == [first, second]


def test_emails_can_be_listed_per_session():
    outbox = Outbox()
    outbox.send(email(session="s1", subject="one"))
    outbox.send(email(session="s2", subject="two"))
    assert [e.subject for e in outbox.sent("s2")] == ["two"]
    assert outbox.sent("nobody") == []


def test_the_returned_list_is_a_copy():
    outbox = Outbox()
    outbox.send(email())
    outbox.sent().clear()
    assert len(outbox.sent()) == 1


def test_anything_shown_to_a_person_has_the_recipient_masked():
    view = email(body="the body").public_view()
    assert view == {
        "session_id": "s1",
        "to": "m***@email.com",
        "subject": "Summary",
        "body": "the body",
    }
    assert "margaret@email.com" not in str(view)


def test_a_sent_email_cannot_be_altered():
    with pytest.raises(AttributeError):
        email().to = "someone@else.com"


def test_the_failing_sender_fails_with_a_clear_error():
    with pytest.raises(EmailSendError, match="unavailable"):
        FailingSender().send(email())
