"""LLM layer. The agent speaks a small provider-neutral message format; each provider adapter
translates it. Only the LLM decides which tools to call (real function calling, no keyword
routing). Tests plug in a scripted fake LLM, so they need no API key and no network."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_name: str = ""  # role == "tool"
    tool_result: Any = None  # role == "tool"
    raw: Any = None  # provider-native content (keeps e.g. Gemini thought signatures)


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    raw: Any = None
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema


class LLM(Protocol):
    name: str

    async def generate(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse: ...


class GeminiLLM:
    """Google Gemini via the google-genai SDK, with automatic function calling disabled:
    the model only *proposes* calls; the agent executes them and sends results back."""

    def __init__(self, api_key: str, model: str, max_retries: int = 2):
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set (see agent/.env.example).")
        from google import genai

        self._client = genai.Client(api_key=api_key)
        # "model-a,model-b": try in order; move to the next one when a model is overloaded
        # (429/5xx after retries) or retired (404). Free-tier models change often.
        self.models = [m.strip() for m in model.split(",") if m.strip()]
        if not self.models:
            raise ValueError("GEMINI_MODEL is empty.")
        self.model = self.models[0]
        self.max_retries = max_retries

    @property
    def name(self) -> str:
        return f"gemini:{self.model}"

    def _contents(self, messages: list[Message]):
        from google.genai import types

        contents = []
        for m in messages:
            if m.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m.text)]))
            elif m.role == "assistant":
                if m.raw is not None:
                    contents.append(m.raw)  # exact model turn, including thought signatures
                    continue
                parts = [types.Part(text=m.text)] if m.text else []
                parts += [
                    types.Part(function_call=types.FunctionCall(name=c.name, args=c.args, id=c.id))
                    for c in m.tool_calls
                ]
                contents.append(types.Content(role="model", parts=parts))
            elif m.role == "tool":
                part = types.Part.from_function_response(
                    name=m.tool_name, response={"result": m.tool_result}
                )
                # consecutive tool results of one round go into one user turn
                if contents and contents[-1].role == "user" and all(
                    p.function_response for p in contents[-1].parts
                ):
                    contents[-1].parts.append(part)
                else:
                    contents.append(types.Content(role="user", parts=[part]))
        return contents

    async def generate(self, system, messages, tools):
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters_json_schema=t.parameters,
                        )
                        for t in tools
                    ]
                )
            ],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        contents = self._contents(messages)
        resp, last_error = None, None
        for model in self.models:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = await self._client.aio.models.generate_content(
                        model=model, contents=contents, config=config
                    )
                    self.model = model
                    break
                except errors.APIError as exc:
                    last_error = exc
                    if exc.code == 404:  # model retired for this key -> next model
                        break
                    if exc.code in (429, 500, 503):  # busy / quota -> back off, then next model
                        if attempt < self.max_retries:
                            await asyncio.sleep(2 * (attempt + 1) ** 2)
                            continue
                        break
                    raise
            if resp is not None:
                break
        if resp is None:
            raise last_error

        candidate = resp.candidates[0] if resp.candidates else None
        raw = candidate.content if candidate else None
        text_parts, calls = [], []
        for part in (raw.parts if raw and raw.parts else []):
            if part.function_call:
                calls.append(
                    ToolCall(
                        name=part.function_call.name,
                        args=dict(part.function_call.args or {}),
                        id=part.function_call.id,
                    )
                )
            elif part.text and not part.thought:
                text_parts.append(part.text)
        usage = {}
        if resp.usage_metadata:
            usage = {
                "input_tokens": resp.usage_metadata.prompt_token_count or 0,
                "output_tokens": resp.usage_metadata.candidates_token_count or 0,
            }
        return LLMResponse(text="".join(text_parts).strip(), tool_calls=calls, raw=raw, usage=usage)


def compact_json(value: Any, limit: int = 400) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 3] + "..."
