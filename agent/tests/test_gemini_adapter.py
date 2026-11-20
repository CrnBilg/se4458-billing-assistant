"""Offline checks of the Gemini adapter (no network call is made)."""
import pytest

from agent.core import TOOLS
from agent.llm import GeminiLLM, Message, ToolCall


def test_requires_an_api_key():
    with pytest.raises(ValueError):
        GeminiLLM("", "gemini-3.8-flash")


def test_history_is_translated_to_gemini_contents():
    llm = GeminiLLM("test-key-not-used", "gemini-3.8-flash")
    contents = llm._contents([
        Message(role="user", text="Why is my bill higher?"),
        Message(role="assistant", tool_calls=[
            ToolCall("query_bill_detailed", {"month": 10, "year": 2026}),
            ToolCall("search_billing_documentation", {"query": "extra internet"}),
        ]),
        Message(role="tool", tool_name="query_bill_detailed", tool_result={"billTotal": 80}),
        Message(role="tool", tool_name="search_billing_documentation", tool_result={"matches": []}),
    ])
    assert [c.role for c in contents] == ["user", "model", "user"]
    assert [p.function_call.name for p in contents[1].parts] == [
        "query_bill_detailed", "search_billing_documentation"]
    # both results of one round are sent back together, in order
    assert [p.function_response.name for p in contents[2].parts] == [
        "query_bill_detailed", "search_billing_documentation"]
    assert contents[2].parts[0].function_response.response == {"result": {"billTotal": 80}}


def test_tool_schemas_are_valid_function_declarations():
    from google.genai import types

    for t in TOOLS:
        decl = types.FunctionDeclaration(name=t.name, description=t.description,
                                         parameters_json_schema=t.parameters)
        assert decl.name == t.name


async def test_falls_back_to_next_model_when_busy_or_retired(monkeypatch):
    from google.genai import errors, types

    llm = GeminiLLM("test-key-not-used", "busy-model,retired-model,good-model", max_retries=1)
    tried = []

    async def fake_generate(model, contents, config):
        tried.append(model)
        if model == "busy-model":
            raise errors.ServerError(503, {"error": {"code": 503, "message": "high demand"}})
        if model == "retired-model":
            raise errors.ClientError(404, {"error": {"code": 404, "message": "not available"}})
        return types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(role="model", parts=[types.Part(text="ok")]))])

    async def no_sleep(_):
        return None

    monkeypatch.setattr(llm._client.aio.models, "generate_content", fake_generate)
    monkeypatch.setattr("agent.llm.asyncio.sleep", no_sleep)
    resp = await llm.generate("sys", [Message(role="user", text="hi")], TOOLS)
    assert resp.text == "ok"
    assert tried == ["busy-model", "busy-model", "retired-model", "good-model"]
    assert llm.name == "gemini:good-model"


async def test_other_api_errors_are_not_retried(monkeypatch):
    from google.genai import errors

    llm = GeminiLLM("test-key-not-used", "a,b")
    tried = []

    async def fake_generate(model, contents, config):
        tried.append(model)
        raise errors.ClientError(400, {"error": {"code": 400, "message": "bad request"}})

    monkeypatch.setattr(llm._client.aio.models, "generate_content", fake_generate)
    with pytest.raises(errors.ClientError):
        await llm.generate("sys", [Message(role="user", text="hi")], TOOLS)
    assert tried == ["a"]
