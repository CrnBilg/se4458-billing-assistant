"""Three distinct retrieval queries (assignment: 'demonstrate three distinct retrieval queries').

Runs them through a REAL MCP client against the MCP server over stdio, so the output is exactly
what the agent receives.

    python demo_queries.py
"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parent / "server.py"
QUERIES = [
    "How much does extra internet cost?",
    "What is the due date of a monthly bill?",
    "How can I dispute a charge?",
]


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("MCP tools:", [t.name for t in tools.tools], "\n")
            for query in QUERIES:
                result = await session.call_tool(
                    "search_billing_documentation", {"query": query, "max_results": 2}
                )
                data = result.structuredContent or json.loads(result.content[0].text)
                print(f"QUERY: {query}")
                for m in data["matches"]:
                    snippet = " ".join(m["text"].split())[:110]
                    print(f"  section {m['section']:<4} score {m['score']:<6} {m['heading']}: {snippet}...")
                print()


if __name__ == "__main__":
    asyncio.run(main())
