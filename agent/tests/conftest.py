"""Agent tests run the whole chain without cloud or a live LLM:

  scripted fake LLM -> BillingAgent -> real MCP server (stdio subprocess)
                                    -> billing REST API app in-process (httpx ASGI transport)
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "billing_api"))

from app import config as api_config  # noqa: E402

api_config.PBKDF2_ITERATIONS = 1000

from app import services  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Bill, Subscriber  # noqa: E402
from app.security import hash_password  # noqa: E402

from agent.backends import BillingGateway, PolicyDocs  # noqa: E402
from agent.llm import LLMResponse, ToolCall  # noqa: E402

MCP_SCRIPT = str(ROOT / "mcp_server" / "server.py")


class ScriptedLLM:
    """Returns pre-written responses in order and records everything it was sent."""

    name = "scripted-fake"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen: list[list] = []

    async def generate(self, system, messages, tools):
        self.seen.append(list(messages))
        if not self.responses:
            raise AssertionError("LLM called more times than scripted")
        return self.responses.pop(0)


def call(name, **args):
    return LLMResponse(text="", tool_calls=[ToolCall(name=name, args=args)])


def calls(*pairs):
    return LLMResponse(text="", tool_calls=[ToolCall(name=n, args=a) for n, a in pairs])


def say(text):
    return LLMResponse(text=text, tool_calls=[])


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    for no, pw in [("5551001", "ayse123"), ("5551002", "mehmet123")]:
        session.add(Subscriber(subscriber_no=no, name=no, role="subscriber",
                               password_hash=hash_password(pw)))
    session.commit()
    services.add_usage(session, "5551001", 2026, 10, "Phone", 135)       # 1,350 min
    services.add_usage(session, "5551001", 2026, 10, "Internet", 35_000)  # 35 GB
    services.calculate_bill(session, "5551001", 2026, 10)                 # $80
    services.add_usage(session, "5551002", 2026, 10, "Internet", 1)
    services.calculate_bill(session, "5551002", 2026, 10)                 # $50
    yield session
    session.close()


@pytest.fixture()
async def gateway(db):
    app = create_app(auto_create_tables=False)

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway")
    gw = BillingGateway("http://gateway", client=client)
    await gw.login("5551001", "ayse123")
    yield gw
    await gw.aclose()


@pytest.fixture()
async def docs():
    # The MCP client must be opened and closed in the same task (anyio cancel scopes),
    # so a small background task owns its whole lifetime.
    ready, stop, holder = asyncio.Event(), asyncio.Event(), {}

    async def owner():
        d = PolicyDocs(server_script=MCP_SCRIPT)
        await d.connect()
        holder["docs"] = d
        ready.set()
        await stop.wait()
        await d.aclose()

    task = asyncio.create_task(owner())
    await asyncio.wait_for(ready.wait(), timeout=60)
    yield holder["docs"]
    stop.set()
    await task


def bill_of(db, subscriber_no="5551001") -> Bill:
    db.expire_all()
    return services.find_bill(db, subscriber_no, 2026, 10)


def paid(db, subscriber_no="5551001") -> Decimal:
    return bill_of(db, subscriber_no).paid_amount
