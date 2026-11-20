"""MCP server exposing `search_billing_documentation(query)` over the indexed billing guide.

    python server.py                              # stdio (the agent spawns it locally)
    python server.py --transport streamable-http  # HTTP service, endpoint /mcp (cloud deploy)

This service is separate from the REST API / API Gateway path: the agent talks to it with an
MCP client, never through the gateway.
"""
import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from indexer import load_or_build

BASE = Path(__file__).resolve().parent
DOC_PATH = Path(os.getenv("BILLING_DOC_PATH", BASE / "docs" / "Mobile_Provider_Billing_Guide.md"))
INDEX_PATH = Path(os.getenv("BILLING_INDEX_PATH", BASE / "index" / "billing_index.json"))

# stdout belongs to the MCP protocol on stdio, so log to stderr only.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("billing-mcp")

# Indexed ONCE at start-up (or loaded from disk if the document is unchanged).
INDEX = load_or_build(DOC_PATH, INDEX_PATH)
log.info("Index ready: %s, %d sections", INDEX.document, len(INDEX.chunks))

mcp = FastMCP(
    "billing-documentation",
    instructions=(
        "Search the Mobile Provider Billing Guide for pricing rules, billing cycles, payment, "
        "late-payment and dispute policy. It holds NO live subscriber data."
    ),
    host=os.getenv("MCP_HOST", "127.0.0.1"),
    port=int(os.getenv("MCP_PORT", "8000")),
)


@mcp.tool()
def search_billing_documentation(query: str, max_results: int = 3) -> dict[str, Any]:
    """Search the Mobile Provider Billing Guide (pricing, allowances, bill calculation, payments,
    late payments, disputes) and return the most relevant sections.

    Use this for POLICY and PRICING questions, e.g. "how much does extra internet cost" or
    "when is a bill due". It does NOT contain any subscriber's usage, bill totals or payments:
    use the billing REST API for those.

    Args:
        query: Short English keywords or a question, e.g. "extra internet charges".
        max_results: How many sections to return (1-10, default 3).

    Returns:
        {"document", "documentId", "query", "matches": [{"section", "heading", "text", "score"}]}
        Cite the `section` number when you answer.
    """
    if not query or not query.strip():
        raise ValueError("query must not be empty")
    max_results = max(1, min(int(max_results), 10))
    matches = INDEX.search(query, k=max_results)
    log.info("search %r -> %s", query, [m["section"] for m in matches])
    return {
        "document": INDEX.document,
        "documentId": INDEX.document_id,
        "query": query,
        "matches": matches,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    args = parser.parse_args()
    mcp.run(transport=args.transport)
