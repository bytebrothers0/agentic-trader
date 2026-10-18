"""agentic/llm.py — the OpenAI-compatible vision client (spec phase 5).

Spec: docs/specs/2026-10-17-agentic-chart-agent-design.md, "The Agent Loop"
(Turn anatomy, Tool surface, System prompt contract, Output contract) and
"Economics and the leash".

``agentic`` is a **pure core**: it may import only the standard library and its
own modules. Network libraries are banned by ``tests/test_agentic/test_standalone``.
So the live model call is not made here. This module does two pure things:

* :func:`build_messages` assembles the OpenAI chat ``messages`` array from an
  :class:`~agentic.agent_loop.AgentRequest` — the system prompt, the briefing as
  JSON text, the rendered image as a data URI, and (when the request carries
  prior tool activity) an assistant ``tool_calls`` message followed by the
  matching ``tool`` result messages.
* :func:`parse_reply` reads the model's reply back into an
  :class:`~agentic.agent_loop.AgentReply`, tolerantly: a vision model will
  occasionally return imperfect JSON, so a malformed tool-argument string becomes
  ``{}`` (the tool layer reports the error to the model) rather than an exception.
  Only a reply with no usable message at all raises :class:`ResponseError`.

The one thing it does *not* do is talk to the network. :class:`VisionClient` takes
a :class:`Transport` — a plain callable, JSON in, JSON out — so a test (and phase
6's wiring) supplies the real HTTP call and everything else stays testable with
zero API spend. The only I/O here is reading the image file in
:func:`encode_image`.

Model choice and cost
---------------------
:data:`DEFAULT_MODEL` is ``gpt-4o-mini``: vision-capable, tool-calling-capable and
cheap, which matters because the agent is a watcher that runs unattended. It is
overridable per client. :data:`PRICES` is a small, configurable table of USD per
million tokens, kept in one place so a price change (or a model swap) is a
one-line edit; the numbers are **estimates** for cost *accounting* against the
leash, not billing truth — verify them against the provider before trusting a
spend cap.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from agentic.agent_loop import AgentReply, AgentRequest
from agentic.prompts import render_briefing_text
from agentic.tools import DEFAULT_TOOL_PARAMETERS, ToolCall, ToolResult

#: Vision-capable, tool-calling-capable and cheap. Overridable per client.
DEFAULT_MODEL = "gpt-4o-mini"

#: ``model -> (usd per 1M input tokens, usd per 1M output tokens)``.
#:
#: Configurable estimates; kept in one place so a price change is a one-line edit.
#: They exist for leash accounting, not invoicing — verify against the provider
#: before trusting a spend cap to be exact.
#:
#: ``qwen/qwen3.8-27b`` is the model the agentic layer inherits from the shared
#: ``/api/ai`` provider (Groq) by default; its published Groq price is $0.80/$4.00
#: per 1M tokens.
#:
#: ``deepseek-v4.1-flash-free`` is the model of the **local, keyless**
#: OpenAI-compatible endpoint (``LLM_PROVIDER=local``), which is free — so it is
#: priced at zero deliberately. This is the one *known* model that is free; the
#: "an unknown model is never free" rule below is unchanged, so if that endpoint
#: is ever pointed at a paid model, change this line (a free entry here would
#: under-count spend, the one direction the leash must not fail in).
PRICES: Dict[str, Tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "qwen/qwen3.8-27b": (0.80, 4.00),
    "deepseek-v4.1-flash-free": (0.0, 0.0),
}

#: What an unknown model is billed at: the default model's price.
#:
#: An unknown model is **never** priced at zero — that would silently disable the
#: spend leash, which is the one thing it must not do. It is instead billed at
#: :data:`DEFAULT_MODEL`'s (non-zero) rate, so the leash always keeps counting.
#: The caveat is direction: the default's price is a cheap stand-in, so a *pricier*
#: unknown model under-counts. The remedy is to add the model to :data:`PRICES`
#: (one line), which is why the table exists.
_FALLBACK_PRICE: Tuple[float, float] = PRICES[DEFAULT_MODEL]

#: Cap on a single completion. A vision turn's output is a handful of tool calls
#: or one structured object; 4096 is generous headroom without inviting a runaway.
DEFAULT_MAX_TOKENS = 4096

#: The one place the reply's token-key contract is spelled out. ``AgentReply.tokens``
#: is summed with ``.values()`` by the loop, so a subset of these keys is fine.
TOKEN_PROMPT = "prompt"
TOKEN_COMPLETION = "completion"

#: A fenced code block, with an optional ``json`` language tag. Non-greedy and
#: DOTALL so leading/trailing prose and a single-line fence all still match.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)

#: ``(abspath, mtime_ns, size) -> data URI``. A multi-round turn re-encodes the
#: same PNG on every round (the image changed only if a ``render`` tool ran), so
#: the memo turns N base64 passes into one. Cache keys on the file's identity, so
#: a rewritten file at the same path is re-read.
_IMAGE_CACHE: Dict[Tuple[str, int, int], str] = {}


class ResponseError(Exception):
    """A malformed or unusable model response (no usable message at all)."""


class Transport(Protocol):
    """The injected model transport: a JSON payload in, a JSON response out.

    Phase 6 supplies the real HTTP call; tests supply a canned dict. The client
    never imports a network library itself.
    """

    def __call__(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...


# --------------------------------------------------------------------------- #
# The image
# --------------------------------------------------------------------------- #

def encode_image(image_path: str) -> str:
    """Read an image file and return a ``data:<media>;base64,...`` URI.

    The only I/O the pure core performs. Raises a clear :class:`FileNotFoundError`
    when the file is missing rather than sending the model a broken URI. The media
    type is guessed from the extension; a file we cannot type at all falls back to
    ``image/png`` (the renderer only ever writes PNG).

    Memoised per ``(path, mtime, size)``: one turn encodes the same image once.
    """
    if not image_path:
        raise FileNotFoundError("encode_image: no image path given")
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"encode_image: image not found: {image_path!r}")

    stat = os.stat(image_path)
    key = (os.path.abspath(image_path), stat.st_mtime_ns, stat.st_size)
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached

    media_type = mimetypes.guess_type(image_path)[0] or "image/png"
    with open(image_path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    uri = f"data:{media_type};base64,{encoded}"
    _IMAGE_CACHE[key] = uri
    return uri


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #

def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """The USD cost of one call, from :data:`PRICES` (unknown model -> fallback)."""
    in_price, out_price = PRICES.get(str(model), _FALLBACK_PRICE)
    prompt = max(int(prompt_tokens or 0), 0)
    completion = max(int(completion_tokens or 0), 0)
    return (prompt / 1_000_000.0) * in_price + (completion / 1_000_000.0) * out_price


# --------------------------------------------------------------------------- #
# Parsing the reply
# --------------------------------------------------------------------------- #

def _strip_code_fence(text: str) -> str:
    """The first fenced block in ``text``, or ``text`` stripped if there is none."""
    stripped = text.strip()
    match = _FENCE_RE.search(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _json_candidates(text: str) -> List[str]:
    """Possible JSON objects inside ``text``, most-specific first.

    A model may wrap the object in a fence, prefix it with prose, suffix it with
    prose, or do all three — so we try the fenced body, the whole string, then the
    ``{...}`` slice.
    """
    stripped = text.strip()
    candidates: List[str] = []
    match = _FENCE_RE.search(stripped)
    if match:
        candidates.append(match.group(1).strip())
    candidates.append(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start:end + 1])
    return candidates


def _maybe_json_object(value: Any) -> Optional[Dict[str, Any]]:
    """``value`` as a JSON object, or ``None``. Strings may be fenced or prose-wrapped."""
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        return None
    for candidate in _json_candidates(value):
        if not candidate.startswith("{"):
            continue
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _coerce_arguments(arguments: Any) -> Dict[str, Any]:
    """Tool-call arguments as a dict. Malformed/unknown shapes become ``{}``.

    The model will sometimes emit ``""`` (no arguments), a dict already, or
    truncated JSON; the tool layer is what reports a bad request back to the
    model, so this must not raise.
    """
    if isinstance(arguments, dict):
        return dict(arguments)
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _parse_tool_calls(raw: Any) -> List[ToolCall]:
    """OpenAI ``message.tool_calls`` -> :class:`ToolCall` list, tolerantly."""
    calls: List[ToolCall] = []
    if not isinstance(raw, list):
        return calls
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function")
        if not isinstance(function, dict):
            function = entry  # some providers flatten name/arguments onto the call
        calls.append(
            ToolCall(
                name=str(function.get("name") or ""),
                arguments=_coerce_arguments(function.get("arguments")),
                call_id=str(entry.get("id") or ""),
            )
        )
    return calls


def _content_text(content: Any) -> str:
    """A text view of ``message.content`` when it is a string or a parts list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text")
        )
    return ""


def _usage_tokens(usage: Any) -> Dict[str, int]:
    """``usage`` -> ``{"prompt", "completion"}`` (either naming convention).

    ``or`` rather than ``.get(key, fallback)`` so a field that is *present but
    ``None``* falls through to its alias instead of poisoning the result.
    """
    if not isinstance(usage, dict):
        return {}
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens")
    completion = usage.get("completion_tokens") or usage.get("output_tokens")
    tokens: Dict[str, int] = {}
    if prompt is not None:
        tokens[TOKEN_PROMPT] = int(prompt)
    if completion is not None:
        tokens[TOKEN_COMPLETION] = int(completion)
    return tokens


def _extract_message(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """``(message, finish_reason)`` from an OpenAI response, or ``(None, "")``."""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        first = choices[0]
        finish_reason = str(first.get("finish_reason") or "")
        message = first.get("message")
        if isinstance(message, dict):
            return message, finish_reason
        # Some endpoints put the fields directly on the choice.
        if any(key in first for key in ("content", "tool_calls", "parsed", "output")):
            return first, finish_reason
    message = payload.get("message")
    if isinstance(message, dict):
        return message, str(payload.get("finish_reason") or "")
    return None, ""


def parse_reply(payload: Dict[str, Any]) -> AgentReply:
    """An LLM response -> :class:`AgentReply`, robustly.

    Accepts the OpenAI ``choices[0].message`` shape (``tool_calls`` with a
    JSON-string ``arguments``, ``content``, and optionally ``parsed``), a bare
    ``message``, or a top-level ``output``. Usage is lifted into ``tokens`` and
    ``finish_reason`` is carried on the reply. A malformed tool-argument string
    becomes ``{}``; only a response with no usable message raises
    :class:`ResponseError`.

    The structured output may arrive as ``parsed``, an ``output`` field, or JSON
    in ``content`` — and a model mid-turn may narrate a JSON object in ``content``
    *alongside* tool calls, so content is parsed regardless of ``tool_calls``.
    """
    if not isinstance(payload, dict):
        raise ResponseError("response is not an object")

    message, finish_reason = _extract_message(payload)
    top_output = _maybe_json_object(payload.get("output"))
    if message is None and top_output is None:
        raise ResponseError("response carries no usable message")

    message = message or {}
    content = message.get("content")
    text = _content_text(content)
    tool_calls = _parse_tool_calls(message.get("tool_calls"))

    output: Dict[str, Any] = {}
    parsed = _maybe_json_object(message.get("parsed"))
    if parsed is not None:
        output = parsed
    else:
        from_message = _maybe_json_object(message.get("output"))
        if from_message is not None:
            output = from_message
        elif top_output is not None:
            output = top_output
        else:
            from_content = _maybe_json_object(content)
            if from_content is not None:
                output = from_content

    return AgentReply(
        tool_calls=tool_calls,
        output=output,
        text=text,
        tokens=_usage_tokens(payload.get("usage")),
        finish_reason=finish_reason,
    )


# --------------------------------------------------------------------------- #
# Building the request
# --------------------------------------------------------------------------- #

def _call_id(call: ToolCall, index: int) -> str:
    return call.call_id or f"call_{index}"


def _arguments_text(arguments: Any) -> str:
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments or {}, ensure_ascii=False, default=str)


def _pair_calls_with_results(
    calls: Sequence[ToolCall], results: Sequence[ToolResult]
) -> List[Tuple[ToolCall, Optional[ToolResult]]]:
    """Pair each call with its result, in order.

    ``run_turn`` appends both lists in lockstep (same order, matching ``call_id``),
    so index pairing is the contract; a call with no recorded result pairs with
    ``None``.
    """
    pairs = list(zip(calls, results))
    pairs.extend((call, None) for call in calls[len(results):])
    return pairs


def _tool_activity_messages(
    calls: Sequence[ToolCall], results: Sequence[ToolResult]
) -> List[Dict[str, Any]]:
    """One assistant ``tool_calls`` message, then the matching ``tool`` results.

    This is what lets a real client reconstruct the assistant -> tool exchange
    even though the store, not a transcript, is the memory: ``run_turn`` hands the
    calls it executed and the results it fed back. All rounds of a turn are
    flattened into a single assistant message with every call, followed by one
    ``tool`` message per call — every ``tool_call_id`` is answered, which is the
    invariant OpenAI enforces.
    """
    if not calls:
        return []
    ids = [_call_id(call, index) for index, call in enumerate(calls)]
    messages: List[Dict[str, Any]] = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": _arguments_text(call.arguments)},
                }
                for call_id, call in zip(ids, calls)
            ],
        }
    ]
    for (call, result), call_id in zip(_pair_calls_with_results(calls, results), ids):
        payload = (
            result.to_dict()
            if result is not None
            else {"ok": False, "error": "no result was recorded for this call"}
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": call.name,
                "content": json.dumps(payload, ensure_ascii=False, default=str),
            }
        )
    return messages


def build_messages(
    request: AgentRequest,
    *,
    system_prompt: str = "",
) -> List[Dict[str, Any]]:
    """An :class:`AgentRequest` -> the OpenAI ``messages`` array.

    ``request.system_prompt`` wins; ``system_prompt`` is the client's default for a
    request that carries none. The user message holds the briefing as JSON text
    (via :func:`agentic.prompts.render_briefing_text`) and, when
    ``request.image_path`` is set, the image as a data URI. When the request
    carries prior tool activity, the assistant ``tool_calls`` message and the
    matching ``tool`` result messages are inserted before it, in order.
    """
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": request.system_prompt or system_prompt}
    ]
    messages.extend(
        _tool_activity_messages(
            list(request.tool_calls_made or []), list(request.tool_results or [])
        )
    )

    user_content: List[Dict[str, Any]] = [
        {"type": "text", "text": render_briefing_text(request.briefing)}
    ]
    if request.image_path:
        user_content.append(
            {"type": "image_url", "image_url": {"url": encode_image(request.image_path)}}
        )
    messages.append({"role": "user", "content": user_content})
    return messages


def to_openai_tools(tools: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``[{"name", "description", "parameters"}]`` -> OpenAI ``tools`` entries.

    The registry already produces the ``function`` object's fields; this only
    wraps them, using the same default ``parameters`` shape the registry does
    (:data:`agentic.tools.DEFAULT_TOOL_PARAMETERS`). An entry already in OpenAI's
    ``{"type": "function", ...}`` form is passed through untouched.
    """
    converted: List[Dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            converted.append(tool)
            continue
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": str(tool.get("name", "")),
                    "description": str(tool.get("description", "")),
                    "parameters": tool.get("parameters") or DEFAULT_TOOL_PARAMETERS,
                },
            }
        )
    return converted


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #

class VisionClient:
    """An :class:`~agentic.agent_loop.AgentClient` over an injected transport.

    Deterministic by default (``temperature=0.0``): the agent is a watcher, and a
    reproducible turn is worth more than variance. The transport is the only
    impure edge; :meth:`complete` builds the payload, calls it, parses the reply
    and prices it. A transport exception is not caught here — the loop hardens
    against it and refuses (or bills) the turn rather than crashing.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        model: str = DEFAULT_MODEL,
        system_prompt: str = "",
        temperature: float = 0.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        response_format: Optional[Dict[str, Any]] = None,
    ):
        self.transport = transport
        self.model = str(model)
        self.system_prompt = system_prompt
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self._response_format = response_format

    def build_payload(self, request: AgentRequest) -> Dict[str, Any]:
        """The chat-completions request body for one turn.

        Note on ``response_format``: ``run_turn`` always passes the tool surface,
        so in production the ``json_object`` default below **never fires** — the
        final structured output is carried by the system prompt (strict JSON) and
        tool-calling, not by a forced format. The branch exists for tool-less
        callers, and a caller that knows its endpoint accepts both can force one
        with ``VisionClient(response_format=...)``.
        """
        payload: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": build_messages(request, system_prompt=self.system_prompt),
        }
        tools = to_openai_tools(request.tools)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        response_format = self._response_format
        if response_format is None and not tools:
            # Tool-less callers only: ask for a JSON object so a one-shot
            # structured-output call needs no prompt coaxing.
            response_format = {"type": "json_object"}
        if response_format:
            payload["response_format"] = response_format
        return payload

    def complete(self, request: AgentRequest) -> AgentReply:
        """One model call: build the payload, transport it, parse and price it."""
        payload = self.build_payload(request)
        response = self.transport(payload)
        reply = parse_reply(response)
        reply.cost_usd = estimate_cost(
            self.model,
            reply.tokens.get(TOKEN_PROMPT, 0),
            reply.tokens.get(TOKEN_COMPLETION, 0),
        )
        return reply
