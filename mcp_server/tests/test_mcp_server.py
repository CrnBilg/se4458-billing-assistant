"""Talks to the real MCP server over stdio with the official MCP client (no LLM, no cloud)."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent.parent / "server.py"


def run_with_session(tmp_path, coro_fn):
    env = dict(os.environ, BILLING_INDEX_PATH=str(tmp_path / "index.json"))
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)

    async def go():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await coro_fn(session)

    return asyncio.run(asyncio.wait_for(go(), timeout=60))


def payload(result):
    return result.structuredContent or json.loads(result.content[0].text)


def test_server_exposes_the_required_tool_with_a_schema(tmp_path):
    async def check(session):
        return (await session.list_tools()).tools

    tools = run_with_session(tmp_path, check)
    assert [t.name for t in tools] == ["search_billing_documentation"]
    schema = tools[0].inputSchema
    assert "query" in schema["properties"] and schema["required"] == ["query"]
    assert "POLICY" in tools[0].description  # tells the LLM when to use it


def test_search_returns_section_references(tmp_path):
    async def check(session):
        return await session.call_tool(
            "search_billing_documentation", {"query": "extra internet cost"}
        )

    result = run_with_session(tmp_path, check)
    assert not result.isError
    data = payload(result)
    assert data["document"] == "Mobile_Provider_Billing_Guide.md"
    assert data["documentId"] == "MOB-BILLING-2026-01"
    top = data["matches"]
    assert "3.2" in [m["section"] for m in top]
    match = next(m for m in top if m["section"] == "3.2")
    assert match["heading"] == "Additional internet blocks" and "$10" in match["text"]


def test_max_results_is_respected_and_clamped(tmp_path):
    async def check(session):
        one = await session.call_tool("search_billing_documentation",
                                      {"query": "internet", "max_results": 1})
        huge = await session.call_tool("search_billing_documentation",
                                       {"query": "internet", "max_results": 999})
        return payload(one), payload(huge)

    one, huge = run_with_session(tmp_path, check)
    assert len(one["matches"]) == 1
    assert 1 < len(huge["matches"]) <= 10


def test_empty_query_is_a_tool_error(tmp_path):
    async def check(session):
        return await session.call_tool("search_billing_documentation", {"query": "   "})

    assert run_with_session(tmp_path, check).isError


def test_unrelated_query_returns_no_matches_instead_of_guessing(tmp_path):
    async def check(session):
        return await session.call_tool("search_billing_documentation",
                                       {"query": "zzqx blorptang"})

    assert payload(run_with_session(tmp_path, check))["matches"] == []


def test_index_file_is_created_once_and_reused(tmp_path):
    async def ask(session):
        return await session.call_tool("search_billing_documentation", {"query": "due date"})

    run_with_session(tmp_path, ask)
    idx = tmp_path / "index.json"
    assert idx.exists()
    stamp = idx.stat().st_mtime_ns
    run_with_session(tmp_path, ask)  # second server start must not re-index
    assert idx.stat().st_mtime_ns == stamp
