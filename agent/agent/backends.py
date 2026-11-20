"""The two separate paths the agent uses to reach backend services:

  * BillingGateway -> API Gateway -> Billing REST API -> PostgreSQL   (live records, payments)
  * PolicyDocs     -> MCP client  -> MCP server -> indexed guide      (policy text)
"""
from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack
from typing import Any

import httpx


class BackendError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def as_dict(self) -> dict[str, Any]:
        return {"error": {"status": self.status, "code": self.code, "message": self.message}}


class BillingGateway:
    """Calls the billing REST API through the API Gateway with the logged-in user's JWT."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self.base_url = base_url
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=20.0)
        self.token: str | None = None
        self.subscriber_no: str | None = None

    async def login(self, subscriber_no: str, password: str) -> None:
        data = await self._request(
            "POST",
            "/api/v1/auth/token",
            json={"subscriberNo": subscriber_no, "password": password},
            auth=False,
        )
        self.token, self.subscriber_no = data["accessToken"], subscriber_no

    async def _request(self, method: str, path: str, auth: bool = True, **kwargs) -> dict:
        headers = {}
        if auth:
            if not self.token:
                raise BackendError(401, "NOT_LOGGED_IN", "Log in first.")
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            resp = await self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise BackendError(503, "GATEWAY_UNREACHABLE", str(exc)) from exc
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = {}
        if resp.status_code >= 400:
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):  # billing API error format
                raise BackendError(resp.status_code, err.get("code", "ERROR"), err.get("message", ""))
            # gateway's own errors look like {"message": "..."}
            message = body.get("message", resp.text) if isinstance(body, dict) else resp.text
            raise BackendError(resp.status_code, "GATEWAY_ERROR", str(message))
        return body

    # ---- operations used by the agent (always for the logged-in subscriber) ----------
    async def query_bill(self, year: int, month: int) -> dict:
        return await self._request(
            "GET", f"/api/v1/bills/{self.subscriber_no}/{year}/{month}", auth=False
        )

    async def query_bill_detailed(self, year: int, month: int, page: int = 1, page_size: int = 10) -> dict:
        return await self._request(
            "GET",
            f"/api/v1/bills/{self.subscriber_no}/{year}/{month}/detailed",
            params={"page": page, "pageSize": page_size},
        )

    async def pay_bill(self, year: int, month: int, amount: float, transaction_id: str) -> dict:
        return await self._request(
            "POST",
            "/api/v1/payments",
            json={
                "subscriberNo": self.subscriber_no,
                "year": year,
                "month": month,
                "amount": amount,
                "transactionId": transaction_id,
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()


class PolicyDocs:
    """MCP client for the billing-documentation MCP server (stdio or streamable HTTP)."""

    def __init__(self, server_url: str = "", server_script: str = ""):
        self.server_url, self.server_script = server_url, server_script
        self._stack = AsyncExitStack()
        self._session = None
        self.transport = ""

    async def connect(self) -> list[str]:
        from mcp import ClientSession

        if self.server_url:
            from mcp.client.streamable_http import streamablehttp_client

            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(self.server_url)
            )
            self.transport = f"streamable-http {self.server_url}"
        else:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(command=sys.executable, args=[self.server_script])
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self.transport = "stdio"
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        tools = await self._session.list_tools()
        return [t.name for t in tools.tools]

    async def search(self, query: str, max_results: int = 3) -> dict:
        result = await self._session.call_tool(
            "search_billing_documentation", {"query": query, "max_results": max_results}
        )
        if result.isError:
            text = result.content[0].text if result.content else "MCP tool error"
            raise BackendError(400, "MCP_TOOL_ERROR", text)
        return result.structuredContent or json.loads(result.content[0].text)

    async def aclose(self) -> None:
        await self._stack.aclose()
