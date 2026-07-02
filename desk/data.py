"""Market data layer for the Quorum desk.

Every number the agents reason over comes from here — computed from real
price/volume series, never guessed. Source: Yahoo Finance via yfinance
(free, no API key). All functions fail soft: on any provider hiccup they
return None/empty so the desk degrades instead of corrupting a brief.
"""

from __future__ import annotations

import datetime as _dt

import pandas as pd
import yfinance as yf


# ---------------------------------------------------------------- indicators

def _rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return round(float((100 - 100 / (1 + rs)).iloc[-1]), 1)


def _atr(hist: pd.DataFrame, period: int = 14) -> float | None:
    if len(hist) < period + 1:
        return None
    hl = hist["High"] - hist["Low"]
    hc = (hist["High"] - hist["Close"].shift()).abs()
    lc = (hist["Low"] - hist["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return round(float(tr.ewm(alpha=1 / period, min_periods=period).mean().iloc[-1]), 2)


# ------------------------------------------------------------------ fetching

def history(ticker: str, period: str = "2y", min_rows: int = 60) -> pd.DataFrame | None:
    try:
        hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        hist = hist.dropna(subset=["Close"])
        return hist if len(hist) >= min_rows else None
    except Exception:
        return None


def batch_history(tickers: list[str], period: str = "2y",
                  min_rows: int = 60) -> dict[str, pd.DataFrame]:
    """One request for the whole universe (Scout's scan)."""
    out: dict[str, pd.DataFrame] = {}
    if not tickers:
        return out
    try:
        raw = yf.download(tickers, period=period, group_by="ticker",
                          auto_adjust=True, progress=False, threads=True)
    except Exception:
        return out
    for t in tickers:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(subset=["Close"])
            if len(df) >= min_rows:
                out[t] = df
        except Exception:
            continue
    return out


def snapshot(ticker: str, hist: pd.DataFrame | None = None) -> dict | None:
    """Computed technical picture for one ticker. Pure math over the series."""
    if hist is None:
        hist = history(ticker)
    if hist is None or len(hist) < 60:
        return None
    close = hist["Close"]
    vol = hist["Volume"]
    price = float(close.iloc[-1])

    def sma(n):
        return round(float(close.rolling(n).mean().iloc[-1]), 2) if len(close) >= n else None

    # Intraday, the last bar's volume is partial and would read falsely low —
    # score the last *completed* session instead. (Price fields stay live.)
    vol_last = float(vol.iloc[-1])
    vol_avg20 = float(vol.rolling(20).mean().iloc[-2]) if len(vol) >= 21 else None
    now = pd.Timestamp.now(tz=hist.index.tz) if hist.index.tz else pd.Timestamp.now()
    if (len(vol) >= 22 and hist.index[-1].date() == now.date()
            and now.time() < _dt.time(16, 0)):
        vol_last = float(vol.iloc[-2])
        vol_avg20 = float(vol.rolling(20).mean().iloc[-3])
    high20_prior = float(close.rolling(20).max().iloc[-2]) if len(close) >= 21 else None
    lookback = min(252, len(close))
    high52 = float(close.rolling(lookback).max().iloc[-1])

    return {
        "price": round(price, 2),
        "change_1d_pct": round(float(close.iloc[-1] / close.iloc[-2] - 1) * 100, 2),
        "sma20": sma(20),
        "sma50": sma(50),
        "sma200": sma(200),
        "rsi14": _rsi(close),
        "atr14": _atr(hist),
        "volume_ratio_20d": round(vol_last / vol_avg20, 2) if vol_avg20 else None,
        "breakout_20d": bool(high20_prior and price > high20_prior),
        "pct_from_52w_high": round((price / high52 - 1) * 100, 1),
    }


def fundamentals(ticker: str) -> dict:
    """Small, verified subset of Yahoo fundamentals. Missing keys stay absent."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return {}
    keep = ("trailingPE", "forwardPE", "revenueGrowth", "profitMargins",
            "returnOnEquity", "marketCap", "sector")
    return {k: info[k] for k in keep if info.get(k) is not None}


def headlines(ticker: str, limit: int = 5) -> list[str]:
    try:
        items = yf.Ticker(ticker).news or []
    except Exception:
        return []
    titles = []
    for it in items:
        # yfinance moved the payload under "content" in newer versions
        title = (it.get("content") or {}).get("title") or it.get("title")
        if title:
            titles.append(str(title).strip())
        if len(titles) >= limit:
            break
    return titles


def days_to_earnings(ticker: str) -> int | None:
    try:
        cal = yf.Ticker(ticker).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if not dates:
            return None
        today = _dt.date.today()
        future = [d for d in dates if isinstance(d, _dt.date) and d >= today]
        return (min(future) - today).days if future else None
    except Exception:
        return None


def macro_data() -> dict:
    """Market regime inputs: SPY trend + VIX level."""
    out: dict = {}
    spy = history("SPY", period="1y")
    if spy is not None:
        close = spy["Close"]
        out["spy"] = round(float(close.iloc[-1]), 2)
        out["spy_sma50"] = round(float(close.rolling(50).mean().iloc[-1]), 2)
        out["spy_sma200"] = round(float(close.rolling(200).mean().iloc[-1]), 2) if len(close) >= 200 else None
    try:
        vix = yf.Ticker("^VIX").history(period="5d")
        if len(vix):
            out["vix"] = round(float(vix["Close"].iloc[-1]), 1)
    except Exception:
        pass
    return out


def spy_price() -> float | None:
    spy = history("SPY", period="1mo", min_rows=1)
    return round(float(spy["Close"].iloc[-1]), 2) if spy is not None else None


def last_prices(tickers: list[str]) -> dict[str, float]:
    hists = batch_history(tickers, period="1mo", min_rows=1)
    return {t: round(float(df["Close"].iloc[-1]), 2) for t, df in hists.items()}
