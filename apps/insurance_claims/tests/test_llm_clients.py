from types import SimpleNamespace

import pytest
from agent.config import Settings
from agent.llm.anthropic_client import AnthropicClient
from agent.llm.client import (
    LLMAuthError,
    LLMBadOutput,
    LLMNotConfigured,
    LLMTimeout,
    LLMUnavailable,
    NotConfiguredClient,
)
from agent.llm.factory import build_llm
from agent.llm.fake import ScriptedLLM
from agent.understanding import LLMExtraction


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def anthropic_with(messages: FakeMessages) -> AnthropicClient:
    return AnthropicClient("test-key", client=SimpleNamespace(messages=messages))


def tool_response(payload):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="x", input=payload)])


def text_response(*texts):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=t) for t in texts])


# ---- Anthropic adapter (against a fake SDK client) -----------------------------------------


async def test_structured_uses_a_forced_tool_call_and_validates_the_result():
    messages = FakeMessages(tool_response({"full_name": "Margaret Chen", "severity": 2}))
    result = await anthropic_with(messages).structured(
        model="m", system="sys", user="hello", schema=LLMExtraction
    )
    assert result.full_name == "Margaret Chen" and result.severity == 2

    request = messages.calls[0]
    assert request["model"] == "m" and request["system"] == "sys"
    assert request["messages"] == [{"role": "user", "content": "hello"}]
    assert request["tool_choice"] == {"type": "tool", "name": request["tools"][0]["name"]}
    assert "full_name" in request["tools"][0]["input_schema"]["properties"]


async def test_structured_without_a_tool_block_is_bad_output():
    with pytest.raises(LLMBadOutput):
        await anthropic_with(FakeMessages(text_response("sorry"))).structured(
            model="m", system="s", user="u", schema=LLMExtraction
        )


async def test_structured_that_fails_validation_is_bad_output():
    with pytest.raises(LLMBadOutput):
        await anthropic_with(FakeMessages(tool_response({"severity": 9}))).structured(
            model="m", system="s", user="u", schema=LLMExtraction
        )


async def test_generate_joins_text_blocks():
    client = anthropic_with(FakeMessages(text_response("Hello ", "there.")))
    assert await client.generate(model="m", system="s", user="u") == "Hello there."


async def test_generate_with_no_text_is_bad_output():
    with pytest.raises(LLMBadOutput):
        await anthropic_with(FakeMessages(text_response("  "))).generate(
            model="m", system="s", user="u"
        )


class APITimeoutError(Exception):
    pass


class AuthenticationError(Exception):
    pass


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (APITimeoutError("slow"), LLMTimeout),
        (AuthenticationError("bad key"), LLMAuthError),
        (ConnectionError("down"), LLMUnavailable),
    ],
)
async def test_sdk_errors_are_mapped_to_llm_errors(error, expected):
    with pytest.raises(expected):
        await anthropic_with(FakeMessages(error=error)).generate(model="m", system="s", user="u")


# ---- no key, factory, scripted fake --------------------------------------------------------


async def test_not_configured_client_raises_a_clear_error():
    client = NotConfiguredClient()
    with pytest.raises(LLMNotConfigured, match="LLM_API_KEY"):
        await client.generate(model="m", system="s", user="u")
    with pytest.raises(LLMNotConfigured):
        await client.structured(model="m", system="s", user="u", schema=LLMExtraction)


def test_factory_without_a_key_returns_the_stand_in():
    assert isinstance(build_llm(Settings()), NotConfiguredClient)


def test_factory_with_an_unsupported_provider_returns_the_stand_in():
    client = build_llm(Settings(llm_api_key="k", llm_provider="other"))
    assert isinstance(client, NotConfiguredClient)


def test_factory_with_a_key_returns_the_anthropic_client():
    assert isinstance(build_llm(Settings(llm_api_key="k")), AnthropicClient)


async def test_scripted_llm_returns_queued_items_and_records_calls():
    llm = ScriptedLLM()
    llm.queue_structured({"full_name": "Ma Tian"}, LLMTimeout("slow"))
    llm.queue_text("hello")

    first = await llm.structured(model="m", system="S", user="U", schema=LLMExtraction)
    assert first.full_name == "Ma Tian"
    with pytest.raises(LLMTimeout):
        await llm.structured(model="m", system="S", user="U", schema=LLMExtraction)
    assert await llm.generate(model="m", system="S", user="U") == "hello"

    assert [c.kind for c in llm.calls] == ["structured", "structured", "generate"]
    assert llm.prompts[0] == "S\nU"
    with pytest.raises(LLMUnavailable):  # nothing queued any more
        await llm.generate(model="m", system="S", user="U")
