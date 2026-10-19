"""
backtest/replay.py — run one agent turn against a frozen instant, then score it.

Two halves:

1. **Replay.** Build the *production* runtime — ``AgentService`` with the real
   ``Feed``, the real ``Renderer`` and the real ``VisionClient`` — but inside
   :func:`backtest.historical.frozen_server`, so every indicator the agent reads
   comes from the frozen history. A ``boot`` turn (or a human ``request``) is then
   run exactly as it would be live, and its store is read back.
2. **Score.** Walk the price action *after* the decision bar and ask what the
   thesis and any proposals would have done: target hit, stop hit, or still open.

Nothing here places an order; the agent remains propose-only.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd

from backtest.historical import FrozenLoader, build_feed, frozen_server

#: Signals that a proposal is long/short, in the vocabulary the model uses.
_LONG = {"bullish", "long", "buy"}
_SHORT = {"bearish", "short", "sell"}


# --------------------------------------------------------------------------- #
# Connection
# --------------------------------------------------------------------------- #

def resolve_live_connection() -> Dict[str, str]:
    """The shared provider the agent would inherit live (``LLM_PROVIDER``).

    Imports ``ai_agent.config`` for its side effect of loading ``.env``, then calls
    the same resolver the server uses, so a backtest talks to exactly the endpoint
    a live turn would.
    """
    import ai_agent.config as cfg  # noqa: F401 — loads .env

    provider, base, model, key_env = cfg.resolve_provider()
    return {"provider": str(provider), "api_base": str(base), "model": str(model), "api_key_env": str(key_env)}


def proxy_health(api_base: str, *, timeout_s: float = 5.0) -> Optional[Dict[str, Any]]:
    """``GET <origin>/health`` for a localhost endpoint, or ``None`` if not local.

    Cheap pre-flight for the local opencode-proxy: a live turn against a dead proxy
    fails deep inside the loop, so we check the door first.
    """
    base = str(api_base or "").rstrip("/")
    if "/" not in base.split("://", 1)[-1]:
        return None
    origin = base.split("/v1", 1)[0].rstrip("/")
    host = origin.split("://", 1)[-1]
    if not (host.startswith("localhost") or host.startswith("127.0.0.1") or host.startswith("[::1]")):
        return None
    try:
        with urllib.request.urlopen(f"{origin}/health", timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Replay
# --------------------------------------------------------------------------- #

@dataclass
class ReplayResult:
    """Everything one replayed turn produced."""

    ok: bool = False
    reason: str = ""
    trigger: str = ""
    turns: int = 0
    tool_calls: int = 0
    renders: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    thesis: Dict[str, Any] = field(default_factory=dict)
    proposals: List[Dict[str, Any]] = field(default_factory=list)
    subscriptions: List[Dict[str, Any]] = field(default_factory=list)
    view: Dict[str, Any] = field(default_factory=dict)
    image_path: str = ""
    render_id: str = ""
    output: Dict[str, Any] = field(default_factory=dict)
    #: The first render of the turn (the chart the agent actually saw first).
    first_render_path: str = ""
    #: The view the store held *before* the turn ran (the seeded config view).
    initial_view: Dict[str, Any] = field(default_factory=dict)
    #: Every model call the turn made, in order: the raw text and what it asked for.
    model_calls: List[Dict[str, Any]] = field(default_factory=list)
    #: Every tool the turn executed, in order (from the persisted turn record).
    tool_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RecordingClient:
    """Wrap any :class:`AgentClient` and remember every reply it returned.

    The loop discards the assistant's raw text, which is exactly what a backtest
    needs to read when the structured output comes back thin. This wraps the real
    ``VisionClient`` (or the mock) — it changes nothing about the turn — and keeps
    a compact record of each call: the text, the tool calls it asked for, the
    provider's ``finish_reason``, and its token split.
    """

    def __init__(self, inner: Any, *, text_limit: int = 6000):
        self._inner = inner
        self._text_limit = int(text_limit)
        self.calls: List[Dict[str, Any]] = []

    def complete(self, request: Any):
        reply = self._inner.complete(request)
        text = str(getattr(reply, "text", "") or "")
        calls = list(getattr(reply, "tool_calls", []) or [])
        briefing = getattr(request, "briefing", None) or {}
        tools = list(getattr(request, "tools", []) or [])
        self.calls.append(
            {
                "index": len(self.calls) + 1,
                "trigger": str(getattr(request, "trigger", "") or ""),
                "text": text[: self._text_limit],
                "text_chars": len(text),
                "truncated": len(text) > self._text_limit,
                "finish_reason": str(getattr(reply, "finish_reason", "") or ""),
                "tool_calls": [str(getattr(c, "name", "") or "") for c in calls],
                "has_output": bool(getattr(reply, "output", None)),
                "output_keys": sorted((getattr(reply, "output", {}) or {}).keys()),
                "tokens": dict(getattr(reply, "tokens", {}) or {}),
                # request shape (cheap; enough to reason about the runaway)
                "has_image": bool(getattr(request, "image_path", "")),
                "tools_offered": len(tools),
                "system_prompt_chars": len(str(getattr(request, "system_prompt", "") or "")),
                "briefing_keys": sorted(briefing.keys()) if isinstance(briefing, dict) else [],
            }
        )
        return reply


def build_service(
    *,
    symbol: str,
    model: str,
    api_base: str,
    api_key_env: str,
    timeframe: str = "M15",
    bars: int = 300,
    max_tokens: int = 2000,
    temperature: float = 0.0,
    mode: str = "live",
    workdir: Optional[str] = None,
    timeout_s: float = 300.0,
    render_width: int = 896,
    render_height: int = 504,
):
    """An ``AgentService`` wired to the (already-frozen) server, in its own dirs.

    ``feed`` is the *default* ``Feed`` — which reads ``server.get_indicators`` and
    so the frozen loader, provided this is called inside
    :func:`backtest.historical.frozen_server`. State and renders go to ``workdir``
    so a backtest can never touch production state.
    """
    from agent_service import AgentConfig, AgentService, build_client
    from agentic.renderer import Renderer

    work = workdir or tempfile.mkdtemp(prefix="crt_backtest_")
    state_dir = os.path.join(work, "state")
    out_dir = os.path.join(work, "renders")
    os.makedirs(state_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    config = AgentConfig(
        symbol=symbol,
        timeframe=timeframe,
        bars=int(bars),
        mode=mode,
        model=model,
        api_base=api_base,
        api_key_env=api_key_env,
        max_tokens=int(max_tokens),
        temperature=float(temperature),
        poll_s=3600.0,  # the watchdog thread must never fire during a replay
        http_timeout_s=float(timeout_s),
        state_dir=state_dir,
        out_dir=out_dir,
    )
    recorder = RecordingClient(build_client(config))
    service = AgentService(
        config,
        renderer=Renderer(width=render_width, height=render_height, out_dir=out_dir),
        client=recorder,
    )
    return service, work, recorder


def run_replay(
    loader: FrozenLoader,
    *,
    symbol: str,
    model: str,
    api_base: str,
    api_key_env: str,
    timeframe: str = "M15",
    bars: int = 300,
    max_tokens: int = 2000,
    mode: str = "live",
    message: str = "",
    families: Sequence[str] = (),
    workdir: Optional[str] = None,
    timeout_s: float = 300.0,
) -> ReplayResult:
    """Freeze, boot the agent, and read its store back.

    A ``message`` runs a human ``request`` turn instead of the boot turn — useful
    to point the agent at the chart ("read the live chart and propose") rather
    than let it open the session itself. ``families`` narrows the seeded view
    before the turn runs (empty = the store's own default: every family).
    """
    with frozen_server(loader):
        service, work, recorder = build_service(
            symbol=symbol,
            model=model,
            api_base=api_base,
            api_key_env=api_key_env,
            timeframe=timeframe,
            bars=bars,
            max_tokens=max_tokens,
            mode=mode,
            workdir=workdir,
            timeout_s=timeout_s,
        )
        try:
            service.enable()
            if families:
                # Narrow the perception *before* the boot render, so the first
                # chart the agent sees is the one under test.
                service.store.set_view(families=[str(f) for f in families])
            initial_view = service.store.data.view.to_dict()
            if message:
                outcome = service.run_now(message)
            else:
                outcome = service.boot()
            store = service.store
            data = store.data
            last_turn = data.turns[-1] if data.turns else None
            result = ReplayResult(
                ok=bool(outcome and outcome.ok),
                reason=str(outcome.reason) if outcome else "no outcome",
                trigger=str(outcome.trigger) if outcome else "",
                turns=len(data.turns),
                tool_calls=int(outcome.tool_calls) if outcome else 0,
                renders=int(outcome.renders) if outcome else 0,
                tokens=int(data.turns[-1].tokens) if data.turns else 0,
                cost_usd=float(data.turns[-1].cost_usd) if data.turns else 0.0,
                thesis=data.thesis.to_dict(),
                proposals=[p.to_dict() for p in data.proposals],
                initial_view=initial_view,
                model_calls=list(recorder.calls),
                tool_log=_tool_log(last_turn),
                subscriptions=[
                    {
                        "id": s.id,
                        "kind": s.kind.value if s.kind else "",
                        "condition": s.condition,
                        "params": dict(s.params or {}),
                        "reason": s.reason,
                        "state": s.state.value if s.state else "",
                    }
                    for s in store.open_subscriptions()
                ],
                view=data.view.to_dict(),
                image_path=str(outcome.image_path) if outcome else "",
                render_id=str((outcome.manifest or {}).get("render_id", "")) if outcome else "",
                output=dict(outcome.output) if outcome else {},
                first_render_path=_first_render(work),
            )
        finally:
            service.stop()
    return result


def _first_render(workdir: str) -> str:
    """The oldest PNG under ``workdir/renders`` — the agent's first render."""
    renders = os.path.join(workdir, "renders")
    try:
        pngs = sorted(
            (os.path.join(renders, n) for n in os.listdir(renders) if n.endswith(".png")),
            key=os.path.getmtime,
        )
    except OSError:
        return ""
    return pngs[0] if pngs else ""


def _tool_log(turn: Any) -> List[Dict[str, Any]]:
    """Flatten a turn record's tool calls into a small, readable list.

    ``TurnRecord.tool_calls`` is a list of plain dicts (``{"call":…, "result":…}``),
    but this tolerates object shapes too so it never depends on the serde form.
    """
    if turn is None:
        return []
    log: List[Dict[str, Any]] = []
    for entry in getattr(turn, "tool_calls", None) or []:
        if isinstance(entry, dict):
            call = entry.get("call") or {}
            result = entry.get("result") or {}
        else:
            call = getattr(entry, "call", None) or {}
            result = getattr(entry, "result", None) or {}
        if isinstance(call, dict):
            name = call.get("name", "")
            arguments = call.get("arguments") or {}
        else:
            name = getattr(call, "name", "")
            arguments = getattr(call, "arguments", {}) or {}
        if isinstance(result, dict):
            ok = bool(result.get("ok", False))
            error = str(result.get("error", "") or "")
        else:
            ok = bool(getattr(result, "ok", False))
            error = str(getattr(result, "error", "") or "")
        log.append(
            {
                "name": str(name),
                "arguments": arguments if isinstance(arguments, dict) else {"value": arguments},
                "ok": ok,
                "error": error[:300],
            }
        )
    return log


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

@dataclass
class TradeSim:
    """What a proposed plan would have done, walked bar by bar."""

    outcome: str = "invalid"          # tp | sl | ambiguous | open | unfilled | invalid
    bars_to_event: Optional[int] = None
    r_multiple: Optional[float] = None
    mfe: float = 0.0                  # max favourable excursion, price units
    mae: float = 0.0                  # max adverse excursion, price units
    reason: str = ""
    #: Unrealised R at the end of the window for a still-open trade. The window
    #: simply ran out before either level was reached; ``None`` would read as
    #: "unmeasurable" when the position's state is perfectly knowable.
    r_mark: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def simulate(bars_after: pd.DataFrame, bias: str, entry, sl, tp) -> TradeSim:
    """Walk forward from the decision bar and report which level was reached first.

    The entry is treated as a **pending order**, not an instant fill: a bar only
    counts once its range actually touches the entry price (``low <= entry <=
    high`` — the generic pending-order fill, direction-agnostic). Excursions and
    stop/target checks are measured from the fill bar onward; a plan whose entry
    was never touched within the window reports ``unfilled`` rather than
    inventing an excursion for a position that never existed.

    Conservative on the ambiguity that only a lower timeframe could resolve: when
    a single bar contains *both* the stop and the target (fill bar included), the
    stop is taken. ``open`` means the fill happened but neither level was reached
    before the history ended — ``r_mark`` then carries the unrealised R at the
    window's last close.
    """
    side = str(bias or "").lower().strip()
    long = side in _LONG
    short = side in _SHORT
    if not long and not short:
        return TradeSim(outcome="invalid", reason=f"non-directional bias {bias!r}")
    if entry is None or sl is None or tp is None:
        return TradeSim(outcome="invalid", reason="entry/sl/tp incomplete")
    entry, sl, tp = float(entry), float(sl), float(tp)
    if not (min(sl, tp) <= entry <= max(sl, tp)):
        return TradeSim(outcome="invalid", reason="entry is not between sl and tp")
    risk = (entry - sl) if long else (sl - entry)
    reward = (tp - entry) if long else (entry - tp)
    if risk <= 0 or reward <= 0:
        return TradeSim(outcome="invalid", reason="risk or reward is not positive")

    mfe = mae = 0.0
    last_close: Optional[float] = None
    filled = False
    for offset, (_, bar) in enumerate(bars_after.iterrows(), start=1):
        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
        last_close = close
        if not filled:
            if min(low, high) <= entry <= max(low, high):
                filled = True
                #--------------------------------------------------------------#
                # The fill bar: the entry traded somewhere inside the bar's
                # range, so its own stop/target extremes are treated as the
                # same unknowable in-bar order as any other bar.
                #--------------------------------------------------------------#
                hit_sl = (low <= sl) if long else (high >= sl)
                hit_tp = (high >= tp) if long else (low <= tp)
                if hit_sl and hit_tp:
                    return TradeSim("ambiguous", offset, -1.0, mfe, mae,
                                    "fill, stop and target inside one bar; stop taken")
                if hit_sl:
                    return TradeSim("sl", offset, -1.0, mfe, mae,
                                    "filled and stopped inside one bar")
                if hit_tp:
                    return TradeSim("tp", offset, round(reward / risk, 2), mfe, mae,
                                    "filled and reached target inside one bar")
            continue
        mfe = max(mfe, (high - entry) if long else (entry - low))
        mae = max(mae, (entry - low) if long else (high - entry))
        hit_sl = (low <= sl) if long else (high >= sl)
        hit_tp = (high >= tp) if long else (low <= tp)
        if hit_sl and hit_tp:
            return TradeSim("ambiguous", offset, -1.0, mfe, mae,
                            "stop and target inside one bar; stop taken")
        if hit_sl:
            return TradeSim("sl", offset, -1.0, mfe, mae, "stop reached")
        if hit_tp:
            return TradeSim("tp", offset, round(reward / risk, 2), mfe, mae, "target reached")
    if not filled:
        return TradeSim("unfilled", None, None, 0.0, 0.0,
                        f"entry never touched within {len(bars_after)} bars")
    r_mark = None if last_close is None else round(((last_close - entry) if long else (entry - last_close)) / risk, 2)
    return TradeSim("open", None, None, round(mfe, 3), round(mae, 3),
                    "neither level reached yet", r_mark=r_mark)


@dataclass
class Verdict:
    """The agent's read scored against what price actually did."""

    crt_direction: str = ""
    crt_target_reached: bool = False
    crt_bars_to_target: Optional[int] = None
    thesis_bias: str = ""
    thesis_aligned: Optional[bool] = None
    thesis_confidence: float = 0.0
    proposals: List[Dict[str, Any]] = field(default_factory=list)
    aligned_proposals: int = 0
    trade: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def score(
    candidate,
    thesis: Dict[str, Any],
    proposals: Sequence[Dict[str, Any]],
    scan_frame: pd.DataFrame,
) -> Verdict:
    """Score one replay against the CRT it was pointed at.

    ``scan_frame`` is the full (untruncated) frame for the scan timeframe, so the
    forward window is the *real* future — the piece the frozen perception never saw.
    """
    direction = str(candidate.direction or "")
    forward = scan_frame.iloc[int(candidate.manipulation_index) + 1 :]

    verdict = Verdict(
        crt_direction=direction,
        crt_target_reached=candidate.state == "distributed",
        crt_bars_to_target=candidate.bars_to_target,
        thesis_bias=str(thesis.get("bias") or ""),
        thesis_confidence=float(thesis.get("confidence") or 0.0),
    )
    want = _LONG if direction in _LONG else _SHORT
    verdict.thesis_aligned = (
        (str(verdict.thesis_bias).lower() in want) if verdict.thesis_bias else None
    )

    scored: List[Dict[str, Any]] = []
    for proposal in proposals or []:
        bias = str(proposal.get("bias") or "")
        sim = simulate(forward, bias, proposal.get("entry"), proposal.get("sl"), proposal.get("tp"))
        row = {
            "bias": bias,
            "setup": proposal.get("setup", ""),
            "entry": proposal.get("entry"),
            "sl": proposal.get("sl"),
            "tp": proposal.get("tp"),
            "confidence": proposal.get("confidence"),
            "reason": proposal.get("reason", ""),
            "aligned": (str(bias).lower() in want) if bias else None,
            "sim": sim.to_dict(),
        }
        scored.append(row)
        if row["aligned"]:
            verdict.aligned_proposals += 1
    verdict.proposals = scored
    # The headline trade: the first proposal, or the first aligned one when there is one.
    pool = [r for r in scored if r["aligned"]] or scored
    if pool:
        verdict.trade = pool[0]
    return verdict


def pace(seconds: float, reason: str = "") -> None:
    """Sleep between live turns. Rate-limit safety for the free/edge tiers."""
    seconds = float(seconds or 0.0)
    if seconds <= 0:
        return
    if reason:
        print(f"  pacing {seconds:.0f}s ({reason})…", flush=True)
    time.sleep(seconds)


def diagnose(replay: Dict[str, Any]) -> Dict[str, Any]:
    """Read the recorded call trace and name what the turn actually did.

    A backtest's value is in this summary as much as in the P&L: a turn that
    burned its round budget on ``set_view``, or finished on ``length`` because a
    reasoning model ran away, reads very differently from one that named a bias.
    """
    calls = list(replay.get("model_calls") or [])
    prompts = [int((c.get("tokens") or {}).get("prompt") or 0) for c in calls]
    completion = [int((c.get("tokens") or {}).get("completion") or 0) for c in calls]
    ran_away = [c for c in calls if c.get("finish_reason") == "length"]
    closing = [c for c in calls if not c.get("tools_offered")]
    bias = str((replay.get("thesis") or {}).get("bias") or "")
    proposals = list(replay.get("proposals") or [])
    output = replay.get("output") or {}
    emitted = list(output.get("proposals") or [])
    apply_errors = [str(e) for e in (output.get("apply_errors") or [])]
    return {
        "model_calls": len(calls),
        "ran_away_calls": len(ran_away),
        "closing_call_used": bool(closing),
        "closing_call_finished": bool(closing) and closing[-1].get("finish_reason") == "stop",
        "max_prompt_tokens": max(prompts) if prompts else 0,
        "completion_tokens": sum(completion),
        "tool_calls": len(replay.get("tool_log") or []),
        "directional": bias not in ("", "none"),
        "proposed": bool(proposals),
        "proposals_emitted": len(emitted),
        "proposals_applied": len(proposals),
        "apply_errors": apply_errors,
        "bias": bias,
        "truncated_rounds": "truncated" in str(replay.get("reason") or ""),
    }
