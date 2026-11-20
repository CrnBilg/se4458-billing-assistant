"""Offline checks of the Gemini adapter (no network call is made)."""
import pytest

from agent.core import TOOLS
from agent.llm import GeminiLLM, Message, ToolCall


def test_requires_an_api_key():
    with pytest.raises(ValueError):
        GeminiLLM("", "gemini-2.5-flash")


def test_history_is_translated_to_gemini_contents():
    llm = GeminiLLM("test-key-not-used", "gemini-2.5-flash")
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
