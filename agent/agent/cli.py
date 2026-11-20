"""Command-line chat with tool trace.

    python -m agent.cli                       # asks for subscriber no + password
    python -m agent.cli --user 5551001        # asks only for the password
    python -m agent.cli --no-trace            # hide the tool trace

Every turn's trace is also appended to traces/session-<time>.jsonl (for the README evidence).
"""
import argparse
import asyncio
import getpass
import json
import sys
from datetime import datetime

from . import config
from .backends import BackendError, BillingGateway, PolicyDocs
from .core import BillingAgent
from .llm import GeminiLLM, compact_json

COLORS = {"llm": "\033[35m", "mcp": "\033[36m", "rest": "\033[33m", "guard": "\033[31m"}
RESET = "\033[0m"


def print_trace(reply, color: bool) -> None:
    print("  --- tool trace ---")
    for t in reply.trace:
        c, r = (COLORS.get(t.kind, ""), RESET) if color else ("", "")
        print(f"  {t.step}. {c}[{t.kind.upper()}]{r} {t.name}  ({t.ms} ms)")
        print(f"       in : {compact_json(t.input, 300)}")
        print(f"       out: {compact_json(t.output, 300)}")
    print("  ------------------")


async def main() -> int:
    ap = argparse.ArgumentParser(description="Mobile Provider Billing Assistant (CLI)")
    ap.add_argument("--user", help="subscriber number")
    ap.add_argument("--password", help="password (prompted if omitted)")
    ap.add_argument("--no-trace", action="store_true")
    args = ap.parse_args()

    gateway = BillingGateway(config.GATEWAY_URL)
    docs = PolicyDocs(config.MCP_SERVER_URL, config.MCP_SERVER_SCRIPT)
    try:
        llm = GeminiLLM(config.GEMINI_API_KEY, config.GEMINI_MODEL)
        user = args.user or input("Subscriber no: ").strip()
        password = args.password or getpass.getpass("Password: ")
        await gateway.login(user, password)
        tools = await docs.connect()
    except (BackendError, ValueError) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        await gateway.aclose()
        return 1

    agent = BillingAgent(llm, gateway, docs, config.MAX_TOOL_ROUNDS)
    config.TRACE_DIR.mkdir(parents=True, exist_ok=True)
    trace_file = config.TRACE_DIR / f"session-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    color = sys.stdout.isatty()

    print(f"Logged in as {user} via gateway {config.GATEWAY_URL}")
    print(f"MCP server ({docs.transport}) tools: {tools}")
    print(f"LLM: {llm.name}.  Type 'exit' to quit.\n")
    try:
        while True:
            try:
                question = input("You: ").strip()
            except EOFError:
                break
            if question.lower() in {"exit", "quit", "q", "çıkış"}:
                break
            if not question:
                continue
            try:
                reply = await agent.ask(question)
            except Exception as exc:  # e.g. LLM quota/model errors: report and keep the session
                print(f"[error] {type(exc).__name__}: {exc}\n")
                continue
            if not args.no_trace:
                print_trace(reply, color)
            print(f"Assistant: {reply.text}\n")
            with trace_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"),
                                    "question": question, "trace": reply.trace_dicts(),
                                    "answer": reply.text}, ensure_ascii=False, default=str) + "\n")
    finally:
        print(f"LLM usage this session: {agent.usage}  (trace log: {trace_file})")
        await docs.aclose()
        await gateway.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
