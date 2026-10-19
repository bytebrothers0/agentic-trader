"""
backtest — offline, point-in-time replay of the agentic CRT chart agent.

Nothing here is imported by the production runtime. The package exists so a
historical window can be served to the *unmodified* indicator stack and the
*unmodified* agent loop, and the result inspected afterwards.

Modules
-------
``historical``
    Load MT5 history once, then freeze it at an instant ``T`` and serve it to
    ``server.get_indicators`` / ``server.get_candles`` through the loader seam, so
    every detector and every render is exactly what it would have been live — with
    no look-ahead past ``T``.
``crt_scan``
    Find *classic* 3-candle CRT setups in a historical frame and score how well
    they resolved, in tradeable terms.
``replay``
    Run one agent turn against a frozen instant and evaluate what the agent said
    against the price action that followed.
``run_crt_backtest``
    The CLI that ties it together and writes a report.
"""
from __future__ import annotations

__all__ = ["historical", "crt_scan", "replay", "run_crt_backtest"]
