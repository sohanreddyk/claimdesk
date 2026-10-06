import json
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
from agent.llm.openai_client import OpenAIClient, is_reasoning_model
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


# ---- OpenAI adapter (against a fake SDK client) --------------------------------------------


class FakeCompletions:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class RateLimitError(Exception):
    pass


def openai_with(completions: FakeCompletions, **options) -> OpenAIClient:
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAIClient("test-key", client=sdk, **options)


def function_call(name, arguments):
    return SimpleNamespace(
        type="function", function=SimpleNamespace(name=name, arguments=arguments)
    )


def completion(content=None, tool_calls=None, finish_reason="stop"):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def structured_completion(payload):
    return completion(tool_calls=[function_call("record_result", json.dumps(payload))])


async def test_openai_structured_uses_a_forced_function_call_and_validates_the_result():
    reply = structured_completion({"full_name": "Margaret Chen", "severity": 2})
    completions = FakeCompletions(reply)
    result = await openai_with(completions).structured(
        model="gpt-4.1-mini", system="sys", user="hello", schema=LLMExtraction
    )
    assert result.full_name == "Margaret Chen" and result.severity == 2

    request = completions.calls[0]
    assert request["model"] == "gpt-4.1-mini"
    assert request["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hello"},
    ]
    assert request["tool_choice"] == {"type": "function", "function": {"name": "record_result"}}
    function = request["tools"][0]["function"]
    assert function["name"] == "record_result"
    assert "full_name" in function["parameters"]["properties"]
    # The newer parameter name, and nothing the reasoning models would reject.
    assert request["max_completion_tokens"] == 1024
    assert "max_tokens" not in request and "temperature" not in request
    assert "reasoning_effort" not in request


async def test_openai_structured_without_a_function_call_is_bad_output():
    with pytest.raises(LLMBadOutput, match="no structured result"):
        await openai_with(FakeCompletions(completion(content="sorry"))).structured(
            model="m", system="s", user="u", schema=LLMExtraction
        )


async def test_openai_structured_ignores_a_call_to_some_other_function():
    other = completion(tool_calls=[function_call("something_else", "{}")])
    with pytest.raises(LLMBadOutput, match="no structured result"):
        await openai_with(FakeCompletions(other)).structured(
            model="m", system="s", user="u", schema=LLMExtraction
        )


async def test_openai_structured_with_arguments_that_are_not_json_is_bad_output():
    bad = completion(tool_calls=[function_call("record_result", "{not json")])
    with pytest.raises(LLMBadOutput, match="not valid JSON"):
        await openai_with(FakeCompletions(bad)).structured(
            model="m", system="s", user="u", schema=LLMExtraction
        )


async def test_openai_structured_that_fails_validation_is_bad_output():
    with pytest.raises(LLMBadOutput, match="failed validation"):
        await openai_with(FakeCompletions(structured_completion({"severity": 9}))).structured(
            model="m", system="s", user="u", schema=LLMExtraction
        )


async def test_openai_response_with_no_choices_is_bad_output():
    empty = SimpleNamespace(choices=[])
    with pytest.raises(LLMBadOutput, match="no choices"):
        await openai_with(FakeCompletions(empty)).generate(model="m", system="s", user="u")


async def test_openai_generate_returns_the_trimmed_text():
    client = openai_with(FakeCompletions(completion(content="  Hello there.  ")))
    assert await client.generate(model="m", system="s", user="u") == "Hello there."


async def test_openai_generate_with_no_text_is_bad_output():
    with pytest.raises(LLMBadOutput, match="no text"):
        await openai_with(FakeCompletions(completion(content=None))).generate(
            model="m", system="s", user="u"
        )


async def test_openai_generate_that_ran_out_of_tokens_says_so():
    cut_off = completion(content="", finish_reason="length")
    with pytest.raises(LLMBadOutput, match="token limit"):
        await openai_with(FakeCompletions(cut_off)).generate(model="m", system="s", user="u")


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-5.5", True),
        ("gpt-5.4-mini", True),
        ("GPT-5.5", True),
        ("o3", True),
        ("o4-mini", True),
        ("gpt-4.1", False),
        ("gpt-4o", False),
        ("claude-sonnet-5-5", False),
    ],
)
def test_reasoning_models_are_recognised_by_name(model, expected):
    assert is_reasoning_model(model) is expected


async def test_reasoning_models_get_headroom_for_hidden_reasoning_tokens():
    # The smoke script asks for only 20 tokens; a reasoning model could spend all of them
    # thinking and return nothing.
    completions = FakeCompletions(completion(content="OK"))
    client = openai_with(completions)
    await client.generate(model="gpt-5.4-mini", system="s", user="u", max_tokens=20)
    await client.generate(model="gpt-4.1", system="s", user="u", max_tokens=20)
    assert [c["max_completion_tokens"] for c in completions.calls] == [20 + 2048, 20]


async def test_reasoning_effort_is_sent_only_when_set_and_only_to_reasoning_models():
    completions = FakeCompletions(completion(content="OK"))
    await openai_with(completions, reasoning_effort="low").generate(
        model="gpt-5.4-mini", system="s", user="u"
    )
    await openai_with(completions, reasoning_effort="low").generate(
        model="gpt-4.1", system="s", user="u"
    )
    await openai_with(completions).generate(model="gpt-5.4-mini", system="s", user="u")
    assert [c.get("reasoning_effort") for c in completions.calls] == ["low", None, None]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (APITimeoutError("slow"), LLMTimeout),
        (AuthenticationError("bad key"), LLMAuthError),
        (ConnectionError("down"), LLMUnavailable),
    ],
)
async def test_openai_sdk_errors_are_mapped_to_llm_errors(error, expected):
    with pytest.raises(expected):
        await openai_with(FakeCompletions(error=error)).generate(model="m", system="s", user="u")


async def test_a_quota_problem_keeps_the_providers_explanation_visible():
    error = RateLimitError("Error code: 429 - insufficient_quota: add credits to your account")
    with pytest.raises(LLMUnavailable, match="insufficient_quota"):
        await openai_with(FakeCompletions(error=error)).generate(model="m", system="s", user="u")


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


def openai_settings(**overrides) -> Settings:
    values = {
        "llm_api_key": "k",
        "llm_provider": "openai",
        "llm_model": "gpt-5.4-mini",
        "llm_model_fast": "gpt-5.4-mini",
        **overrides,
    }
    return Settings(**values)


def test_factory_returns_the_openai_client_for_the_openai_provider():
    assert isinstance(build_llm(openai_settings()), OpenAIClient)
    assert isinstance(build_llm(openai_settings(llm_provider="OpenAI")), OpenAIClient)


def test_factory_passes_the_reasoning_effort_to_the_openai_client():
    client = build_llm(openai_settings(llm_reasoning_effort="low"))
    assert client._reasoning_effort == "low"


async def test_openai_provider_with_the_default_claude_model_names_says_what_to_change():
    client = build_llm(Settings(llm_api_key="k", llm_provider="openai"))  # models left as Claude
    assert isinstance(client, NotConfiguredClient)
    with pytest.raises(LLMNotConfigured, match="OpenAI models"):
        await client.generate(model="m", system="s", user="u")


async def test_anthropic_provider_with_openai_model_names_says_what_to_change():
    client = build_llm(Settings(llm_api_key="k", llm_model="gpt-5.5"))
    assert isinstance(client, NotConfiguredClient)
    with pytest.raises(LLMNotConfigured, match="Claude models"):
        await client.generate(model="m", system="s", user="u")


async def test_an_unknown_provider_lists_the_supported_ones():
    client = build_llm(Settings(llm_api_key="k", llm_provider="other"))
    with pytest.raises(LLMNotConfigured, match="use 'anthropic' or 'openai'"):
        await client.generate(model="m", system="s", user="u")


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
