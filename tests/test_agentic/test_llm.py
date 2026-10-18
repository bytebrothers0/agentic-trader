"""Tests for the vision client (spec phase 5 acceptance criteria).

Every model call runs over a **fake transport** — a plain callable returning
canned dicts — so there is no network anywhere and the whole suite spends nothing.
The scenarios mirror the spec's phase-5 acceptance: a boot turn produces a thesis,
a view change and at least one armed watch, driven end to end by
:class:`~agentic.llm.VisionClient` over a scripted transport.
"""
import base64
import json

import pytest
from pytest import approx

from _fixtures import FakeClock, FakeRenderer, FeedStub, at, bars_rows, level as _level
from agentic.agent_loop import AgentLoop, AgentRequest
from agentic.llm import (
    DEFAULT_MODEL,
    PRICES,
    ResponseError,
    VisionClient,
    build_messages,
    encode_image,
    estimate_cost,
    parse_reply,
    to_openai_tools,
)
from agentic.models import SubscriptionKind
from agentic.prompts import render_briefing_text
from agentic.store import ContextStore
from agentic.tools import ToolCall, ToolResult

#: A 1x1 transparent PNG — a real image, so ``encode_image`` round-trips bytes.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #

class FakeTransport:
    """A scripted transport: canned responses out, every payload recorded."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []

    def __call__(self, payload):
        self.payloads.append(payload)
        if self.responses:
            return self.responses.pop(0)
        return {"choices": [{"message": {"role": "assistant", "content": None}, "finish_reason": "stop"}]}


def _write_png(tmp_path, name="chart.png"):
    path = tmp_path / name
    path.write_bytes(PNG_1X1)
    return str(path)


def _png_uri(tmp_path):
    return "data:image/png;base64," + base64.b64encode(PNG_1X1).decode("ascii")


# --------------------------------------------------------------------------- #
# parse_reply
# --------------------------------------------------------------------------- #

def test_parse_reply_reads_tool_calls_with_json_string_arguments():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "set_view", "arguments": '{"bars": 120}'},
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {"name": "render", "arguments": ""},
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }

    reply = parse_reply(payload)

    assert [call.name for call in reply.tool_calls] == ["set_view", "render"]
    assert reply.tool_calls[0].arguments == {"bars": 120}
    assert reply.tool_calls[0].call_id == "call_1"
    assert reply.tool_calls[1].arguments == {}  # empty string -> no arguments
    assert reply.tokens == {"prompt": 100, "completion": 20}
    assert reply.finish_reason == "tool_calls"
    assert reply.output == {}


def test_parse_reply_coerces_malformed_tool_arguments_to_empty():
    payload = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"id": "a", "function": {"name": "add_watch", "arguments": "{not json"}},
                        {"id": "b", "function": {"name": "add_pin", "arguments": "[1, 2, 3]"}},
                    ]
                }
            }
        ]
    }

    reply = parse_reply(payload)

    assert [call.arguments for call in reply.tool_calls] == [{}, {}]


def test_parse_reply_accepts_arguments_that_are_already_a_dict():
    payload = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"id": "a", "function": {"name": "set_view", "arguments": {"bars": 200}}},
                    ]
                }
            }
        ]
    }

    reply = parse_reply(payload)

    assert reply.tool_calls[0].arguments == {"bars": 200}


def test_parse_reply_reads_a_fenced_json_content_output():
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '```json\n{"thesis": {"bias": "bullish"}, "reasoning": "up"}\n```',
                },
                "finish_reason": "stop",
            }
        ]
    }

    reply = parse_reply(payload)

    assert reply.tool_calls == []
    assert reply.output["thesis"]["bias"] == "bullish"
    assert reply.output["reasoning"] == "up"


@pytest.mark.parametrize(
    "content",
    [
        'Sure — here it is:\n```json\n{"thesis": {"bias": "bullish"}}\n```\nHope that helps.',
        '```json {"thesis": {"bias": "bullish"}}```',  # a single-line fence
        'Result follows: {"thesis": {"bias": "bullish"}} — done.',  # brace slice
    ],
)
def test_parse_reply_recovers_json_from_prose_and_single_line_fences(content):
    reply = parse_reply({"choices": [{"message": {"content": content}}]})
    assert reply.output["thesis"]["bias"] == "bullish"


def test_parse_reply_parses_content_output_alongside_tool_calls():
    # A model mid-turn may narrate the structured object in content *and* call
    # tools; the output must not be dropped just because tools are present.
    payload = {
        "choices": [
            {
                "message": {
                    "content": '{"thesis": {"bias": "bearish"}}',
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "render", "arguments": ""}},
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }

    reply = parse_reply(payload)

    assert [call.name for call in reply.tool_calls] == ["render"]
    assert reply.output["thesis"]["bias"] == "bearish"


def test_parse_reply_keeps_plain_content_as_text():
    payload = {"choices": [{"message": {"content": "no setup today"}}]}

    reply = parse_reply(payload)

    assert reply.text == "no setup today"
    assert reply.output == {}


def test_parse_reply_reads_the_parsed_and_output_fields():
    parsed = parse_reply({"choices": [{"message": {"parsed": {"thesis": {"bias": "bearish"}}}}]})
    assert parsed.output["thesis"]["bias"] == "bearish"

    top_level = parse_reply({"output": {"thesis": {"bias": "bullish"}}})
    assert top_level.output["thesis"]["bias"] == "bullish"


def test_parse_reply_lifts_input_output_token_names():
    payload = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"input_tokens": 7, "output_tokens": 3},
    }
    assert parse_reply(payload).tokens == {"prompt": 7, "completion": 3}


def test_parse_reply_tolerates_a_none_token_field():
    # A field that is present but None must fall through to its alias.
    payload = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": None, "input_tokens": 7, "completion_tokens": None, "output_tokens": 3},
    }
    assert parse_reply(payload).tokens == {"prompt": 7, "completion": 3}


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"error": "boom"}, {"choices": [{}]}])
def test_parse_reply_raises_when_there_is_no_usable_message(payload):
    with pytest.raises(ResponseError):
        parse_reply(payload)


# --------------------------------------------------------------------------- #
# encode_image
# --------------------------------------------------------------------------- #

def test_encode_image_round_trips_a_real_png(tmp_path):
    path = _write_png(tmp_path)
    uri = encode_image(path)

    # The whole URI, prefix included, is pinned.
    assert uri == _png_uri(tmp_path)
    prefix, _, encoded = uri.partition(",")
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded) == PNG_1X1


def test_encode_image_defaults_an_untypeable_file_to_png(tmp_path):
    # The renderer only writes PNG, so a file we cannot type is PNG, not an error.
    path = tmp_path / "chart"  # no extension -> mimetypes returns nothing
    path.write_bytes(PNG_1X1)
    assert encode_image(str(path)).startswith("data:image/png;base64,")


def test_encode_image_uses_the_guessed_mime_for_other_files(tmp_path):
    # An existing non-PNG file is encoded with its guessed type, not made PNG.
    path = tmp_path / "notes.txt"
    path.write_text("not an image", encoding="utf-8")
    assert encode_image(str(path)).startswith("data:text/plain;base64,")


def test_encode_image_is_memoised_for_an_unchanged_file(tmp_path):
    import agentic.llm as llm

    path = _write_png(tmp_path)
    first = encode_image(path)
    cached = dict(llm._IMAGE_CACHE)
    second = encode_image(path)
    assert first == second
    # re-encoding an unchanged file adds no new cache entry
    assert llm._IMAGE_CACHE == cached


def test_encode_image_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="image not found"):
        encode_image(str(tmp_path / "nope.png"))


# --------------------------------------------------------------------------- #
# estimate_cost
# --------------------------------------------------------------------------- #

def test_estimate_cost_known_and_unknown_models():
    # A pinned literal: gpt-4o-mini is $0.15 in / $0.60 out per 1M, so 1M/1M is $0.75.
    assert estimate_cost(DEFAULT_MODEL, 1_000_000, 1_000_000) == approx(0.75)
    assert estimate_cost(DEFAULT_MODEL, 1_000_000, 0) == approx(0.15)

    in_price, out_price = PRICES[DEFAULT_MODEL]
    assert estimate_cost(DEFAULT_MODEL, 1_000, 0) == approx(in_price / 1000.0)

    # An unknown model falls back to the default model's price (documented) — a
    # non-zero stand-in, so the spend leash keeps counting instead of silently
    # freezing at zero.
    assert estimate_cost("mystery-model", 1_000_000, 1_000_000) == approx(0.75)
    assert estimate_cost("mystery-model", 1_000_000, 0) > 0


def test_estimate_cost_prices_the_inherited_vision_model():
    """The live mode's inherited model (Groq qwen) must be priced, not fall back."""
    model = "qwen/qwen3.8-27b"
    assert model in PRICES
    in_price, out_price = PRICES[model]
    assert in_price > 0 and out_price > 0
    assert estimate_cost(model, 1_000_000, 1_000_000) == approx(in_price + out_price)
    # Priced above the fallback, so inheriting it cannot under-count spend.
    assert estimate_cost(model, 1_000_000, 1_000_000) > estimate_cost(DEFAULT_MODEL, 1_000_000, 1_000_000)


def test_estimate_cost_prices_the_keyless_local_model():
    """The local keyless endpoint's model is a *known* free model, priced zero.

    Zero is deliberate here (the local provider is free); an *unknown* model still
    falls back to a non-zero rate, so this is the one exception, not a loophole.
    """
    model = "deepseek-v4.1-flash-free"
    assert model in PRICES
    assert PRICES[model] == (0.0, 0.0)
    assert estimate_cost(model, 1_000_000, 1_000_000) == approx(0.0)


# --------------------------------------------------------------------------- #
# build_messages
# --------------------------------------------------------------------------- #

def test_build_messages_system_and_user_with_a_data_uri_image(tmp_path):
    request = AgentRequest(
        system_prompt="you are an analyst",
        briefing={"trigger": "boot", "detail": "server start"},
        image_path=_write_png(tmp_path),
    )

    messages = build_messages(request)

    assert messages[0] == {"role": "system", "content": "you are an analyst"}
    assert messages[1]["role"] == "user"
    text, image = messages[1]["content"]
    assert text["type"] == "text"
    assert '"trigger": "boot"' in text["text"]
    assert image["type"] == "image_url"
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


def test_build_messages_uses_the_client_default_system_prompt():
    messages = build_messages(AgentRequest(briefing={}), system_prompt="default policy")
    assert messages[0] == {"role": "system", "content": "default policy"}


def test_build_messages_without_an_image_has_no_image_part():
    messages = build_messages(AgentRequest(system_prompt="sys", briefing={}))
    parts = messages[-1]["content"]
    assert [part["type"] for part in parts] == ["text"]


def test_build_messages_reconstructs_prior_tool_activity_in_order():
    request = AgentRequest(
        system_prompt="sys",
        briefing={"trigger": "fire"},
        tool_calls_made=[
            ToolCall(call_id="c1", name="set_view", arguments={"bars": 120}),
            ToolCall(call_id="c2", name="level_lookup", arguments={"family": "fvg"}),
        ],
        tool_results=[
            ToolResult(call_id="c1", name="set_view", ok=True, result={"bars": 120}),
            ToolResult(call_id="c2", name="level_lookup", ok=True, result={"matches": []}),
        ],
    )

    messages = build_messages(request)

    assert [m["role"] for m in messages] == ["system", "assistant", "tool", "tool", "user"]
    assistant = messages[1]
    assert [c["id"] for c in assistant["tool_calls"]] == ["c1", "c2"]
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"bars": 120}
    assert [m["tool_call_id"] for m in messages[2:4]] == ["c1", "c2"]
    assert json.loads(messages[2]["content"])["ok"] is True


# --------------------------------------------------------------------------- #
# The payload and the client
# --------------------------------------------------------------------------- #

def test_payload_wraps_tools_and_requests_auto_tool_choice():
    request = AgentRequest(
        system_prompt="sys",
        briefing={},
        tools=[{"name": "set_view", "description": "change the view", "parameters": {"type": "object"}}],
    )
    client = VisionClient(FakeTransport([]), model=DEFAULT_MODEL)

    payload = client.build_payload(request)

    assert payload["model"] == DEFAULT_MODEL
    assert payload["temperature"] == 0.0
    assert payload["tool_choice"] == "auto"
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "set_view",
                "description": "change the view",
                "parameters": {"type": "object"},
            },
        }
    ]
    # With tools present, tool-calling and the prompt carry the contract, so no
    # forced response_format is sent.
    assert "response_format" not in payload


def test_payload_asks_for_a_json_object_when_there_are_no_tools():
    client = VisionClient(FakeTransport([]))
    payload = client.build_payload(AgentRequest(system_prompt="sys", briefing={}))
    assert payload["response_format"] == {"type": "json_object"}
    assert "tools" not in payload


def test_to_openai_tools_passes_through_already_wrapped_entries():
    wrapped = {"type": "function", "function": {"name": "render"}}
    assert to_openai_tools([wrapped]) == [wrapped]


def test_to_openai_tools_uses_the_shared_default_parameters():
    from agentic.tools import DEFAULT_TOOL_PARAMETERS

    converted = to_openai_tools([{"name": "render", "description": "re-render"}])
    assert converted[0]["function"]["parameters"] == DEFAULT_TOOL_PARAMETERS


def test_complete_prices_the_reply_from_usage():
    transport = FakeTransport(
        [
            {
                "choices": [{"message": {"content": '{"thesis": {"bias": "neutral"}}'}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            }
        ]
    )
    client = VisionClient(transport)

    reply = client.complete(AgentRequest(system_prompt="sys", briefing={}))

    assert reply.output["thesis"]["bias"] == "neutral"
    # A pinned literal: 1000/1M*0.15 + 500/1M*0.60 = 0.00045.
    assert reply.cost_usd == approx(0.00045)
    assert reply.cost_usd == approx(estimate_cost(DEFAULT_MODEL, 1000, 500))
    assert transport.payloads[0]["messages"][0]["role"] == "system"


# --------------------------------------------------------------------------- #
# Phase-5 acceptance: a real boot turn, end to end, over a fake transport
# --------------------------------------------------------------------------- #

def _store(tmp_path, clock):
    store = ContextStore("XAUUSDm", state_dir=str(tmp_path / "state"), clock=clock)
    store.set_view(timeframe="M15", bars=300)
    store.set_enabled(True)
    return store


def _feed():
    stub = FeedStub(price=4155.0, atr=5.0)
    stub.set_levels(
        [
            _level(
                "fvg",
                type="FVG (BULLISH)",
                price=4160.0,
                time=1760000000,
                end_kind="active",
                box_top=4162.0,
                box_bottom=4158.0,
                desc="FVG bullish",
            )
        ],
        timeframe="M15",
    )
    stub.set_candles(bars_rows(), timeframe="M15")
    return stub.build()


def _boot_responses():
    """Round 1: set_view + add_watch. Round 2: the final structured output."""
    tool_round = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "set_view",
                                "arguments": '{"timeframe": "H1", "bars": 150}',
                            },
                        },
                        {
                            "id": "call_2",
                            "type": "function",
                            "function": {
                                "name": "add_watch",
                                "arguments": json.dumps(
                                    {
                                        "condition": "level_forms",
                                        "params": {"family": "fvg"},
                                        "ttl_hours": 4.0,
                                        "reason": "wait for the LTF fvg",
                                    }
                                ),
                            },
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    final_round = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "thesis": {
                                "bias": "bullish",
                                "storyline": "sweep then continuation",
                                "invalidation": "below 4100",
                                "confidence": 0.6,
                            },
                            "proposals": [],
                            "subscriptions_added": [],
                            "subscriptions_released": [],
                            "notes": [{"text": "armed waiting for the M15 fvg"}],
                            "reasoning": "bullish continuation to the fvg",
                        }
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 80, "completion_tokens": 30},
    }
    return [tool_round, final_round]


def test_phase_5_boot_turn_over_a_fake_transport(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    transport = FakeTransport(_boot_responses())
    client = VisionClient(transport, model=DEFAULT_MODEL)
    loop = AgentLoop(
        store, _feed(), FakeRenderer(out_dir=str(tmp_path / "renders"), clock=clock), client, clock=clock
    )

    outcome = loop.boot()

    # the turn ran and was logged once
    assert outcome.ok is True, outcome.reason
    assert outcome.trigger == "boot"
    assert len(store.data.turns) == 1
    record = store.data.turns[0]
    assert [entry["call"]["name"] for entry in record.tool_calls] == ["set_view", "add_watch"]

    # a thesis, a changed view, and at least one armed watch
    assert store.data.thesis.bias == "bullish"
    assert store.data.thesis.invalidation == "below 4100"
    assert store.data.view.timeframe == "H1"
    assert store.data.view.bars == 150
    watches = store.open_subscriptions(SubscriptionKind.WATCH)
    assert len(watches) >= 1
    assert watches[0].condition == "level_forms"

    # usage priced across both rounds
    assert record.tokens == 230
    assert record.cost_usd == approx(
        estimate_cost(DEFAULT_MODEL, 100, 20) + estimate_cost(DEFAULT_MODEL, 80, 30)
    )

    # the second call carried the first round's tool activity, rebuilt in order
    assert len(transport.payloads) == 2
    assert [m["role"] for m in transport.payloads[1]["messages"]] == [
        "system",
        "assistant",
        "tool",
        "tool",
        "user",
    ]


def test_client_error_refuses_the_turn_without_recording_it(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)

    def boom(payload):
        raise RuntimeError("kaboom")

    loop = AgentLoop(
        store,
        _feed(),
        FakeRenderer(out_dir=str(tmp_path / "renders"), clock=clock),
        VisionClient(boom),
        clock=clock,
    )

    outcome = loop.run_turn(trigger="request", detail="human asked")

    assert outcome.ok is False
    assert outcome.reason.startswith("client_error:")
    assert "RuntimeError" in outcome.reason and "kaboom" in outcome.reason
    assert store.data.turns == []
    assert not store.exists()  # the store was never saved


def test_a_malformed_response_is_labelled_bad_response(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    # An empty object is a transport *success* with no usable message.
    loop = AgentLoop(
        store,
        _feed(),
        FakeRenderer(out_dir=str(tmp_path / "renders"), clock=clock),
        VisionClient(FakeTransport([{}])),
        clock=clock,
    )

    outcome = loop.run_turn(trigger="request")

    assert outcome.ok is False
    assert outcome.reason.startswith("bad_response: ResponseError:")
    assert store.data.turns == []


def test_a_long_error_message_is_capped_in_the_reason(tmp_path):
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)

    def boom(payload):
        raise RuntimeError("x" * 500)

    loop = AgentLoop(
        store,
        _feed(),
        FakeRenderer(out_dir=str(tmp_path / "renders"), clock=clock),
        VisionClient(boom),
        clock=clock,
    )

    reason = loop.run_turn(trigger="request").reason

    assert reason.startswith("client_error: RuntimeError:")
    assert len(reason) < 260  # type + a ~200-char capped message


def test_partial_spend_is_recorded_and_billed(tmp_path):
    """A later round fails after an earlier one cost money: bill it, don't lose it."""
    clock = FakeClock(at(6, 0))
    store = _store(tmp_path, clock)
    first_round = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "c1", "function": {"name": "add_note", "arguments": '{"text": "hi"}'}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }

    class FlakyTransport:
        def __init__(self):
            self.calls = 0

        def __call__(self, payload):
            self.calls += 1
            if self.calls == 1:
                return first_round
            raise RuntimeError("boom on the second call")

    loop = AgentLoop(
        store,
        _feed(),
        FakeRenderer(out_dir=str(tmp_path / "renders"), clock=clock),
        VisionClient(FlakyTransport()),
        clock=clock,
    )

    outcome = loop.run_turn(trigger="request")

    assert outcome.ok is False
    assert outcome.reason.startswith("client_error: RuntimeError: boom")
    assert outcome.output["partial"] is True
    assert outcome.tool_calls == 1  # the add_note that did run is logged

    # the turn *was* recorded and the spend billed, so the leash counts it
    assert len(store.data.turns) == 1
    record = store.data.turns[0]
    assert record.tokens == 120
    assert record.cost_usd == approx(0.000027)  # 100/1M*0.15 + 20/1M*0.60
    assert record.output["partial"] is True
    assert record.output["error"].startswith("client_error:")
    assert store.exists()
    assert store.data.budget.turns_today == 1
    assert store.data.budget.spend_usd_today == approx(0.000027)


# --------------------------------------------------------------------------- #
# render_briefing_text (the wire layer's text view)
# --------------------------------------------------------------------------- #

def test_render_briefing_text_is_json_with_a_header():
    text = render_briefing_text({"trigger": "boot", "detail": "server start", "thesis": {"bias": "none"}})
    assert text.startswith("Turn briefing — trigger: boot (server start)")
    body = json.loads(text.split("\n", 1)[1])
    assert body["thesis"]["bias"] == "none"
