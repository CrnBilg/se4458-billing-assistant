"""The agent orchestrator.

    user question -> LLM picks tools -> agent executes them (MCP and/or REST via gateway)
                  -> results go back to the LLM -> grounded answer citing guide sections

Safety rules enforced in CODE, not only in the prompt:
  * Tools never take a subscriber number. Every REST call is made for the logged-in user with
    their own JWT, so a number typed into the chat cannot reach someone else's data.
  * `pay_bill` never moves money. It only prepares a payment and returns CONFIRMATION_REQUIRED.
    The Pay Bill API is called only after the user's NEXT message is an explicit "yes"
    (checked by the agent itself, not by the LLM). Anything else cancels the payment.
  * One transaction ID is generated per prepared payment and reused on a retry, so a retry
    cannot create a duplicate payment.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .backends import BackendError, BillingGateway, PolicyDocs
from .llm import LLM, Message, ToolSpec, compact_json

CONFIRM_RE = re.compile(
    r"^\s*(yes|y|confirm|confirmed|i confirm|evet|onaylıyorum|onayliyorum|onayla)\s*[.!]*\s*$",
    re.IGNORECASE,
)

PERIOD_PROPS = {
    "month": {"type": "integer", "minimum": 1, "maximum": 12, "description": "Billing month 1-12."},
    "year": {"type": "integer", "minimum": 2000, "maximum": 2100, "description": "Billing year, e.g. 2026."},
}

TOOLS = [
    ToolSpec(
        name="search_billing_documentation",
        description=(
            "Search the Mobile Provider Billing Guide (MCP server) for POLICY and PRICING: free "
            "minutes, internet allowance and extra-block prices, bill formula, due dates, late "
            "payment, partial payments, disputes. Contains NO subscriber data. Returns sections "
            "with section numbers to cite."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Short English search keywords."}
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="query_bill",
        description=(
            "Live data for the logged-in subscriber: stored bill total, paid amount, remaining "
            "balance and status for one month (Billing REST API via the API Gateway)."
        ),
        parameters={"type": "object", "properties": PERIOD_PROPS, "required": ["month", "year"]},
    ),
    ToolSpec(
        name="query_bill_detailed",
        description=(
            "Live data for the logged-in subscriber: bill with phone minutes, internet MB/GB, "
            "charge breakdown, due date and a paged list of usage records. Use it to explain WHY "
            "a bill is what it is."
        ),
        parameters={
            "type": "object",
            "properties": {
                **PERIOD_PROPS,
                "page": {"type": "integer", "minimum": 1, "description": "Usage list page, default 1."},
            },
            "required": ["month", "year"],
        },
    ),
    ToolSpec(
        name="pay_bill",
        description=(
            "PREPARE a simulated payment for the logged-in subscriber. This does NOT pay: it "
            "returns CONFIRMATION_REQUIRED and the user must reply 'yes' before anything is "
            "charged. Use the exact amount the user asked for; for 'pay my bill' first look up "
            "the remaining balance with query_bill."
        ),
        parameters={
            "type": "object",
            "properties": {
                **PERIOD_PROPS,
                "amount": {"type": "number", "exclusiveMinimum": 0, "description": "Amount in USD."},
            },
            "required": ["month", "year", "amount"],
        },
    ),
]


def system_prompt(subscriber_no: str, today: date) -> str:
    return f"""You are the Billing Support Assistant of a mobile provider.
Today is {today.isoformat()}. The logged-in subscriber is {subscriber_no}; every billing tool acts
for this subscriber only. If the user asks about another subscriber number, say you can only
access their own account.

Choosing tools:
- Pricing, rules, due dates, disputes, late payment, partial payments -> search_billing_documentation.
- The user's own bill, balance, usage or status -> query_bill / query_bill_detailed.
- "Why is my bill higher / what am I charged for" -> query_bill_detailed AND
  search_billing_documentation, then explain the numbers with the rules.
- Paying -> pay_bill (it only prepares the payment). Then tell the user the subscriber, period and
  amount and ask them to reply "yes" to confirm. Never say a payment succeeded unless a Pay Bill
  API result says SUCCESS.
- A month without a year means the most recent such month on or before today.

Answering:
- Use only numbers returned by tools. Never invent usage, totals or prices. If a bill is not found,
  say it has not been calculated yet; do not present your own estimate as the bill.
- When you use the guide, cite sections like (Guide §3.2).
- Be brief. Reply in the user's language (Turkish or English)."""


@dataclass
class TraceEntry:
    step: int
    kind: str  # "llm" | "mcp" | "rest" | "guard"
    name: str
    input: Any
    output: Any
    ms: int


@dataclass
class PendingPayment:
    month: int
    year: int
    amount: float
    transaction_id: str


@dataclass
class AgentReply:
    text: str
    trace: list[TraceEntry] = field(default_factory=list)

    def trace_dicts(self) -> list[dict]:
        return [asdict(t) for t in self.trace]


class BillingAgent:
    def __init__(self, llm: LLM, gateway: BillingGateway, docs: PolicyDocs,
                 max_tool_rounds: int = 6, today: date | None = None):
        self.llm, self.gateway, self.docs = llm, gateway, docs
        self.max_tool_rounds = max_tool_rounds
        self.today = today or date.today()
        self.history: list[Message] = []
        self.pending: PendingPayment | None = None
        self._trace: list[TraceEntry] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "llm_calls": 0}

    # ---- public --------------------------------------------------------------------------
    async def ask(self, user_text: str) -> AgentReply:
        self._trace = []
        if self.pending is not None:
            pending, self.pending = self.pending, None
            if CONFIRM_RE.match(user_text):
                return await self._execute_confirmed_payment(user_text, pending)
            self._log("guard", "payment_cancelled", {"user_reply": user_text}, asdict(pending))
            user_text = (
                f"{user_text}\n\n[Agent note: the prepared payment of ${pending.amount:.2f} for "
                f"{pending.month:02d}/{pending.year} was CANCELLED because the user did not reply "
                "with an explicit confirmation. Mention this briefly.]"
            )
        self.history.append(Message(role="user", text=user_text))
        return await self._run()

    # ---- the tool-calling loop -----------------------------------------------------------
    async def _run(self) -> AgentReply:
        system = system_prompt(self.gateway.subscriber_no or "unknown", self.today)
        for _ in range(self.max_tool_rounds):
            started = time.perf_counter()
            resp = await self.llm.generate(system, self.history, TOOLS)
            self.usage["llm_calls"] += 1
            for k in ("input_tokens", "output_tokens"):
                self.usage[k] += resp.usage.get(k, 0)
            self._log(
                "llm",
                self.llm.name,
                {"messages": len(self.history)},
                {"tool_calls": [{"name": c.name, "args": c.args} for c in resp.tool_calls],
                 "text": resp.text},
                started,
            )
            self.history.append(
                Message(role="assistant", text=resp.text, tool_calls=resp.tool_calls, raw=resp.raw)
            )
            if not resp.tool_calls:
                return AgentReply(resp.text or "(no answer)", self._trace)
            for call in resp.tool_calls:
                result = await self._execute(call.name, call.args)
                self.history.append(Message(role="tool", tool_name=call.name, tool_result=result))
        text = "Sorry, I could not finish this request. Please rephrase it."
        self.history.append(Message(role="assistant", text=text))
        return AgentReply(text, self._trace)

    async def _execute(self, name: str, args: dict) -> dict:
        started = time.perf_counter()
        kind = "mcp" if name == "search_billing_documentation" else "rest"
        try:
            if name == "search_billing_documentation":
                result = await self.docs.search(str(args.get("query", "")).strip())
            elif name == "query_bill":
                result = await self.gateway.query_bill(*self._period(args))
            elif name == "query_bill_detailed":
                year, month = self._period(args)
                result = await self.gateway.query_bill_detailed(year, month, int(args.get("page", 1)))
            elif name == "pay_bill":
                kind = "guard"
                result = self._prepare_payment(args)
            else:
                result = {"error": {"code": "UNKNOWN_TOOL", "message": f"No tool named {name}."}}
        except BackendError as exc:
            result = exc.as_dict()
        except (TypeError, ValueError, KeyError) as exc:
            result = {"error": {"code": "BAD_ARGUMENTS", "message": str(exc)}}
        self._log(kind, name, args, result, started)
        return result

    # ---- payments ------------------------------------------------------------------------
    def _prepare_payment(self, args: dict) -> dict:
        year, month = self._period(args)
        try:
            amount = Decimal(str(args["amount"])).quantize(Decimal("0.01"))
        except (InvalidOperation, KeyError) as exc:
            raise ValueError("amount must be a number") from exc
        if amount <= 0:
            raise ValueError("amount must be greater than 0")
        self.pending = PendingPayment(month, year, float(amount), f"AGT-{uuid.uuid4().hex[:16]}")
        return {
            "status": "CONFIRMATION_REQUIRED",
            "paymentExecuted": False,
            "subscriberNo": self.gateway.subscriber_no,
            "period": f"{month:02d}/{year}",
            "amount": float(amount),
            "instruction": "Show these details and ask the user to reply 'yes' to confirm. "
            "Any other reply cancels the payment.",
        }

    async def _execute_confirmed_payment(self, user_text: str, p: PendingPayment) -> AgentReply:
        self._log("guard", "payment_confirmed", {"user_reply": user_text}, asdict(p))
        started = time.perf_counter()
        args = {"month": p.month, "year": p.year, "amount": p.amount, "transactionId": p.transaction_id}
        result = None
        for attempt in range(2):  # same transaction ID on retry -> no duplicate payment
            try:
                result = await self.gateway.pay_bill(p.year, p.month, p.amount, p.transaction_id)
                break
            except BackendError as exc:
                result = exc.as_dict()
                if exc.code != "GATEWAY_UNREACHABLE" or attempt == 1:
                    break
        self._log("rest", "pay_bill (Pay Bill API)", args, result, started)
        self.history.append(
            Message(
                role="user",
                text=f"{user_text}\n\n[Agent note: the user explicitly confirmed. The Pay Bill API "
                f"was called and returned: {compact_json(result, 1000)}. Report this result "
                "accurately; if it is an error, say the payment was NOT made.]",
            )
        )
        return await self._run()

    # ---- helpers -------------------------------------------------------------------------
    @staticmethod
    def _period(args: dict) -> tuple[int, int]:
        year, month = int(args["year"]), int(args["month"])
        if not 1 <= month <= 12:
            raise ValueError("month must be 1-12")
        return year, month

    def _log(self, kind, name, inp, out, started: float | None = None) -> None:
        ms = int((time.perf_counter() - started) * 1000) if started else 0
        self._trace.append(TraceEntry(len(self._trace) + 1, kind, name, inp, out, ms))
