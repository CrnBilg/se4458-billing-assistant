"""Agent settings from environment variables (see .env.example)."""
import os
from pathlib import Path

try:  # optional: load agent/.env when python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# All REST traffic goes to the API Gateway, never straight to the billing service.
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8000").rstrip("/")

# MCP server: either an HTTP endpoint (deployed service) or a local script spawned over stdio.
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "")  # e.g. http://localhost:8001/mcp
MCP_SERVER_SCRIPT = os.getenv(
    "MCP_SERVER_SCRIPT",
    str(Path(__file__).resolve().parents[2] / "mcp_server" / "server.py"),
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Comma-separated fallback list; the first one that answers is used.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash,gemini-3.5-flash,gemini-3.1-flash-lite")

MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "6"))
TRACE_DIR = Path(os.getenv("AGENT_TRACE_DIR", Path(__file__).resolve().parent.parent / "traces"))
