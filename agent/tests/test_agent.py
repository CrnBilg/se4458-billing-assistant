from datetime import date

from agent.backends import BackendError
from agent.core import CONFIRM_RE, TOOLS, BillingAgent
from tests.conftest import ScriptedLLM, call, calls, paid, say

TODAY = date(2026, 11, 20)


def make(llm, gateway, docs):
    return BillingAgent(llm, gateway, docs, today=TODAY)


def tool_results(llm, call_index):
    """Tool results the LLM received on its n-th call."""
    return {m.tool_name: m.tool_result for m in llm.seen[call_index] if m.role == "tool"}


# ---- the three required scenarios ----------------------------------------------------------
async def test_mcp_only_scenario(gateway, docs):
    llm = ScriptedLLM(
        call("search_billing_documentation", query="extra internet cost"),
        say("Each extra 10 GB block costs $10 (Guide §3.2)."),
    )
    reply = await make(llm, gateway, docs).ask("How much does extra internet cost?")

    assert [t.kind for t in reply.trace] == ["llm", "mcp", "llm"]
    result = tool_results(llm, 1)["search_billing_documentation"]
    assert "3.2" in [m["section"] for m in result["matches"]]
    assert result["documentId"] == "MOB-BILLING-2026-01"
    assert "§3.2" in reply.text


async def test_rest_only_scenario(gateway, docs):
    llm = ScriptedLLM(call("query_bill", month=10, year=2026), say("Your October bill is $80."))
    reply = await make(llm, gateway, docs).ask("What is my October bill?")

    assert [t.kind for t in reply.trace] == ["llm", "rest", "llm"]
    bill = tool_results(llm, 1)["query_bill"]
    assert bill["billTotal"] == 80.0 and bill["status"] == "UNPAID"


async def test_combined_mcp_and_rest_scenario(gateway, docs):
    llm = ScriptedLLM(
        calls(("query_bill_detailed", {"month": 10, "year": 2026}),
              ("search_billing_documentation", {"query": "additional internet blocks"})),
        say("You used 35 GB; 2 extra blocks -> $70 internet (Guide §3.2)."),
    )
    reply = await make(llm, gateway, docs).ask("Why is my October bill higher?")

    assert [t.kind for t in reply.trace] == ["llm", "rest", "mcp", "llm"]
    seen = tool_results(llm, 1)
    assert seen["query_bill_detailed"]["internet"]["gb"] == 35.0
    assert seen["query_bill_detailed"]["internet"]["charge"] == 70.0
    assert "3.2" in [m["section"] for m in seen["search_billing_documentation"]["matches"]]


# ---- payment confirmation --------------------------------------------------------------------
async def test_payment_is_not_made_until_user_says_yes(db, gateway, docs):
    llm = ScriptedLLM(
        call("pay_bill", month=10, year=2026, amount=30),
        say("Pay $30.00 for 10/2026 from 5551001? Reply 'yes' to confirm."),
        say("Payment successful. Remaining balance: $50."),
    )
    agent = make(llm, gateway, docs)

    first = await agent.ask("Pay 30 dollars of my October bill")
    assert tool_results(llm, 1)["pay_bill"]["status"] == "CONFIRMATION_REQUIRED"
    assert paid(db) == 0, "nothing may be charged before confirmation"
    assert "rest" not in [t.kind for t in first.trace]

    second = await agent.ask("yes")
    assert [t.name for t in second.trace][:2] == ["payment_confirmed", "pay_bill (Pay Bill API)"]
    api_result = second.trace[1].output
    assert api_result["status"] == "SUCCESS" and api_result["remainingBalance"] == 50.0
    assert paid(db) == 30
    assert "SUCCESS" in llm.seen[2][-1].text  # API result is handed to the LLM for the answer


async def test_any_other_reply_cancels_the_payment(db, gateway, docs):
    llm = ScriptedLLM(
        call("pay_bill", month=10, year=2026, amount=30),
        say("Reply 'yes' to confirm."),
        say("OK, the payment was cancelled."),
    )
    agent = make(llm, gateway, docs)
    await agent.ask("Pay 30 of my October bill")
    reply = await agent.ask("hmm, maybe later")

    assert paid(db) == 0 and agent.pending is None
    assert reply.trace[0].name == "payment_cancelled"
    assert "CANCELLED" in llm.seen[2][-1].text


async def test_llm_cannot_skip_confirmation_by_calling_pay_twice(db, gateway, docs):
    llm = ScriptedLLM(
        call("pay_bill", month=10, year=2026, amount=30),
        call("pay_bill", month=10, year=2026, amount=30),
        say("Please confirm."),
    )
    await make(llm, gateway, docs).ask("pay 30")
    assert paid(db) == 0


async def test_turkish_confirmation_is_accepted():
    for word in ["yes", "Yes.", "evet", "Evet!", "onaylıyorum", "confirm"]:
        assert CONFIRM_RE.match(word), word
    for word in ["yes but only 10", "no", "evet mi?", "maybe", ""]:
        assert not CONFIRM_RE.match(word), word


async def test_overpayment_error_from_api_reaches_the_llm(db, gateway, docs):
    llm = ScriptedLLM(
        call("pay_bill", month=10, year=2026, amount=500),
        say("Confirm $500?"),
        say("The payment was NOT made: the amount exceeds your balance."),
    )
    agent = make(llm, gateway, docs)
    await agent.ask("pay 500")
    reply = await agent.ask("evet")
    assert reply.trace[1].output["error"]["code"] == "AMOUNT_EXCEEDS_BALANCE"
    assert paid(db) == 0


async def test_retry_after_network_failure_reuses_the_transaction_id(db, gateway, docs):
    real_pay, seen_ids = gateway.pay_bill, []

    async def flaky(year, month, amount, tx):
        seen_ids.append(tx)
        if len(seen_ids) == 1:
            raise BackendError(503, "GATEWAY_UNREACHABLE", "timeout")
        return await real_pay(year, month, amount, tx)

    gateway.pay_bill = flaky
    llm = ScriptedLLM(call("pay_bill", month=10, year=2026, amount=10), say("Confirm?"), say("Done."))
    agent = make(llm, gateway, docs)
    await agent.ask("pay 10")
    await agent.ask("yes")
    assert len(seen_ids) == 2 and seen_ids[0] == seen_ids[1]
    assert paid(db) == 10


# ---- identity / authorization ----------------------------------------------------------------
async def test_subscriber_number_in_prompt_cannot_reach_other_accounts(db, gateway, docs):
    """Even if the LLM is tricked into passing another number, tools ignore it."""
    llm = ScriptedLLM(call("query_bill", month=10, year=2026, subscriberNo="5551002"),
                      say("I can only show your own bill."))
    await make(llm, gateway, docs).ask("Show the bill of subscriber 5551002")
    assert tool_results(llm, 1)["query_bill"]["subscriberNo"] == "5551001"


async def test_no_tool_accepts_a_subscriber_number():
    for tool in TOOLS:
        props = tool.parameters["properties"]
        assert not any("subscriber" in p.lower() for p in props), tool.name


# ---- robustness ------------------------------------------------------------------------------
async def test_bill_not_calculated_error_is_given_to_the_llm(gateway, docs):
    llm = ScriptedLLM(call("query_bill", month=1, year=2026),
                      say("Your January bill has not been calculated yet."))
    await make(llm, gateway, docs).ask("January bill?")
    assert tool_results(llm, 1)["query_bill"]["error"]["code"] == "BILL_NOT_FOUND"


async def test_unknown_tool_and_bad_arguments_do_not_crash(gateway, docs):
    llm = ScriptedLLM(
        calls(("delete_account", {}), ("query_bill", {"month": 13, "year": 2026})),
        say("Sorry."),
    )
    await make(llm, gateway, docs).ask("?")
    seen = tool_results(llm, 1)
    assert seen["delete_account"]["error"]["code"] == "UNKNOWN_TOOL"
    assert seen["query_bill"]["error"]["code"] == "BAD_ARGUMENTS"


async def test_tool_loop_is_bounded(gateway, docs):
    llm = ScriptedLLM(*[call("query_bill", month=10, year=2026)] * 6)
    agent = BillingAgent(llm, gateway, docs, max_tool_rounds=6, today=TODAY)
    reply = await agent.ask("loop")
    assert "could not finish" in reply.text
