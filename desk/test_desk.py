"""Tests for the deterministic core.

These cover the two places where a silent arithmetic error would be most
expensive and least visible: the Risk agent's position sizing and veto (it is
the only thing standing between a confident verdict and an oversized trade),
and snapshot()'s partial-bar correction (an intraday volume bug would read as
a real signal, not as an error).

No network. Every test builds its own price series, so `snapshot()` is
exercised through its injected-history path and never calls yfinance.

    .venv/bin/python -m pytest test_desk.py -q
"""

from __future__ import annotations

import datetime as _dt

import pandas as pd
import pytest

import agents
import data as datalib


CFG = {
    "risk_per_trade_pct": 1.0,
    "max_position_pct": 15.0,
    "max_positions": 6,
    "cash_floor_pct": 10.0,
    "stop_atr_mult": 2.0,
    "target_atr_mult": 3.0,
}


def brain(cash: float = 100_000.0, positions: dict | None = None) -> dict:
    return {"cash": cash, "positions": positions or {}}


# ------------------------------------------------------- Risk agent: sizing

def test_stop_and_target_come_from_atr_multiples():
    r = agents.risk_agent(CFG, brain(), equity=100_000, price=100.0, atr=5.0,
                          conviction=80, regime="risk-on")
    assert r["stop"] == 90.0     # 100 - 2 * 5
    assert r["target"] == 115.0  # 100 + 3 * 5


def test_size_is_capped_by_the_one_percent_risk_budget():
    # Risk budget $1,000; $10/share of risk (stop is 2*ATR below) -> 100 shares.
    # That is $10,000 = 10% of equity, so it binds before the 15% position cap.
    r = agents.risk_agent(CFG, brain(), equity=100_000, price=100.0, atr=5.0,
                          conviction=80, regime="risk-on")
    assert r["shares"] == 100
    assert r["veto"] is None


def test_position_cap_binds_when_it_is_tighter_than_the_risk_budget():
    # Tight stop (ATR 1 -> $2/share risk) would allow 500 shares by risk budget,
    # but 15% of $100k at $100 caps it at 150.
    r = agents.risk_agent(CFG, brain(), equity=100_000, price=100.0, atr=1.0,
                          conviction=80, regime="risk-on")
    assert r["shares"] == 150


def test_cash_floor_binds_and_reserves_ten_percent():
    # Only $12k cash against $100k equity; the 10% floor reserves $10k,
    # leaving $2k deployable -> 20 shares at $100.
    r = agents.risk_agent(CFG, brain(cash=12_000), equity=100_000, price=100.0,
                          atr=5.0, conviction=80, regime="risk-on")
    assert r["shares"] == 20


def test_missing_atr_falls_back_to_two_percent_of_price():
    # No ATR must never mean no stop. Fallback is 2% of price -> stop 4% below.
    r = agents.risk_agent(CFG, brain(), equity=100_000, price=100.0, atr=None,
                          conviction=80, regime="risk-on")
    assert r["stop"] == 96.0
    r_zero = agents.risk_agent(CFG, brain(), equity=100_000, price=100.0, atr=0,
                               conviction=80, regime="risk-on")
    assert r_zero["stop"] == 96.0


# --------------------------------------------------------- Risk agent: veto

def test_veto_at_max_open_positions():
    full = {t: {} for t in ("A", "B", "C", "D", "E", "F")}
    r = agents.risk_agent(CFG, brain(positions=full), equity=100_000, price=100.0,
                          atr=5.0, conviction=95, regime="risk-on")
    assert r["veto"] and "max open positions" in r["veto"]


def test_veto_when_no_room_inside_the_cash_floor():
    # Cash below the floor entirely: nothing is deployable.
    r = agents.risk_agent(CFG, brain(cash=5_000), equity=100_000, price=100.0,
                          atr=5.0, conviction=90, regime="risk-on")
    assert r["shares"] == 0
    assert r["veto"] and "risk limits" in r["veto"]


def test_risk_off_regime_vetoes_low_conviction_but_allows_high():
    low = agents.risk_agent(CFG, brain(), equity=100_000, price=100.0, atr=5.0,
                            conviction=64, regime="risk-off")
    assert low["veto"] and "risk-off" in low["veto"]

    high = agents.risk_agent(CFG, brain(), equity=100_000, price=100.0, atr=5.0,
                             conviction=65, regime="risk-off")
    assert high["veto"] is None  # 65 is the documented threshold, inclusive


def test_conviction_alone_never_overrides_a_structural_veto():
    """The LLM's enthusiasm must not be able to buy past the caps."""
    full = {t: {} for t in ("A", "B", "C", "D", "E", "F")}
    r = agents.risk_agent(CFG, brain(positions=full), equity=100_000, price=100.0,
                          atr=5.0, conviction=100, regime="risk-on")
    assert r["veto"] is not None


# ------------------------------------------- snapshot(): partial-bar handling

def frame(closes: list[float], volumes: list[float], last_date=None) -> pd.DataFrame:
    """A minimal OHLCV frame ending on `last_date` (default: today)."""
    n = len(closes)
    end = last_date or _dt.date.today()
    idx = pd.to_datetime([end - _dt.timedelta(days=n - 1 - i) for i in range(n)])
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": volumes,
        },
        index=idx,
    )


def test_snapshot_returns_none_on_short_history():
    assert datalib.snapshot("X", frame([100.0] * 30, [1e6] * 30)) is None


def test_intraday_partial_bar_is_excluded_from_the_volume_ratio(monkeypatch):
    """The last bar is partial before the close — scoring it would read as a
    fake volume collapse. The desk must score the last *completed* session."""
    closes = [100.0] * 80
    volumes = [1_000_000.0] * 79 + [50_000.0]  # today, only partly filled

    monkeypatch.setattr(datalib.pd.Timestamp, "now",
                        classmethod(lambda cls, tz=None: pd.Timestamp(
                            f"{_dt.date.today()} 11:00:00", tz=tz)))

    snap = datalib.snapshot("X", frame(closes, volumes))
    # Scored against yesterday's full 1M bar, not today's partial 50k.
    assert snap["volume_ratio_20d"] == pytest.approx(1.0, abs=0.01)


def test_after_the_close_the_last_bar_is_scored_normally(monkeypatch):
    closes = [100.0] * 80
    volumes = [1_000_000.0] * 79 + [2_000_000.0]  # a real completed surge

    monkeypatch.setattr(datalib.pd.Timestamp, "now",
                        classmethod(lambda cls, tz=None: pd.Timestamp(
                            f"{_dt.date.today()} 18:00:00", tz=tz)))

    snap = datalib.snapshot("X", frame(closes, volumes))
    assert snap["volume_ratio_20d"] == pytest.approx(2.0, abs=0.01)


def test_stale_last_bar_is_scored_even_during_market_hours(monkeypatch):
    """A frame ending yesterday has no partial bar, whatever the clock says."""
    closes = [100.0] * 80
    volumes = [1_000_000.0] * 79 + [2_000_000.0]
    yesterday = _dt.date.today() - _dt.timedelta(days=1)

    monkeypatch.setattr(datalib.pd.Timestamp, "now",
                        classmethod(lambda cls, tz=None: pd.Timestamp(
                            f"{_dt.date.today()} 11:00:00", tz=tz)))

    snap = datalib.snapshot("X", frame(closes, volumes, last_date=yesterday))
    assert snap["volume_ratio_20d"] == pytest.approx(2.0, abs=0.01)


# ------------------------------------------------- snapshot(): the indicators

def test_breakout_flag_needs_a_close_above_the_prior_twenty_day_high():
    flat = datalib.snapshot("X", frame([100.0] * 80, [1e6] * 80))
    assert flat["breakout_20d"] is False

    breaking = datalib.snapshot("X", frame([100.0] * 79 + [120.0], [1e6] * 80))
    assert breaking["breakout_20d"] is True


def test_moving_averages_and_distance_from_the_52w_high():
    snap = datalib.snapshot("X", frame([100.0] * 80, [1e6] * 80))
    assert snap["sma20"] == 100.0
    assert snap["sma50"] == 100.0
    assert snap["sma200"] is None          # only 80 rows of history
    assert snap["pct_from_52w_high"] == 0.0


def test_rsi_is_bounded_and_reads_extremes_correctly():
    rising = datalib.snapshot("X", frame([100.0 + i for i in range(80)], [1e6] * 80))
    falling = datalib.snapshot("X", frame([200.0 - i for i in range(80)], [1e6] * 80))
    assert 0 <= rising["rsi14"] <= 100 and rising["rsi14"] > 90
    assert 0 <= falling["rsi14"] <= 100 and falling["rsi14"] < 10


# ------------------------------------------------- deterministic Strategist

def packet(mode: str, signals: dict, triggers=()) -> dict:
    return {
        "mode": mode,
        "analysts": {n: {"signal": s, "note": f"{n} note"} for n, s in signals.items()},
        "sentinel_triggers": list(triggers),
    }


def test_vote_verdict_labels_itself_as_having_skipped_the_llm():
    """Degradation must announce itself — a silent fallback is the bug."""
    out = agents._vote_verdict(packet("opening", {"technical": "bull"}))
    assert out["source"] == "vote"
    assert "no LLM consulted" in out["summary"]


def test_vote_verdict_respects_the_conviction_threshold_for_opening():
    bullish = agents._vote_verdict(
        packet("opening", {"a": "bull", "b": "bull", "c": "bull"}))
    assert bullish["verdict"] == "BUY" and bullish["conviction"] >= 60

    bearish = agents._vote_verdict(
        packet("opening", {"a": "bear", "b": "bear", "c": "bear"}))
    assert bearish["verdict"] == "PASS"


def test_vote_verdict_stays_inside_the_allowed_verdicts_per_mode():
    opening = agents._vote_verdict(packet("opening", {"a": "neutral"}))
    assert opening["verdict"] in {"BUY", "PASS"}

    update = agents._vote_verdict(packet("update", {"a": "neutral"}))
    assert update["verdict"] in {"HOLD", "TRIM", "EXIT"}


def test_a_sentinel_exit_trigger_forces_an_exit_verdict():
    out = agents._vote_verdict(
        packet("update", {"a": "bull", "b": "bull"}, triggers=[{"level": "exit"}]))
    assert out["verdict"] == "EXIT"  # the trigger overrides bullish analysts


def test_conviction_is_always_clamped_to_the_documented_range():
    for signals in ({f"a{i}": "bull" for i in range(20)},
                    {f"a{i}": "bear" for i in range(20)}):
        assert 5 <= agents._vote_verdict(packet("opening", signals))["conviction"] <= 95
