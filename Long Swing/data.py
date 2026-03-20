"""
Long Swing — Data layer (EODHD primary, yfinance fallback).

Provides download_eodhd() as drop-in replacement for download_ohlcv().
"""
import os
import time
import requests
import pandas as pd
from datetime import datetime, timedelta

EODHD_API_KEY = os.environ.get("EODHD_API_KEY", "69b86cbae43f91.37277389")
EODHD_BASE_URL = "https://eodhd.com/api/eod"

# Yahoo ticker → EODHD ticker mapping
EXCHANGE_MAP = {
    ".DE": "XETRA",
    ".L": "LSE",
    ".T": "TSE",
    ".AX": "AU",
}
SAME_SUFFIX = {".PA", ".SW", ".ST", ".MI", ".AS", ".BR", ".MC", ".HE", ".CO", ".HK"}

# Special tickers
SPECIAL = {
    "BTC-USD": "BTC-USD.CC",
    "^VIX": "VIX.INDX",
}


def _yahoo_to_eodhd(ticker):
    """Convert Yahoo Finance ticker to EODHD format."""
    if ticker in SPECIAL:
        return SPECIAL[ticker]

    for suffix in sorted(EXCHANGE_MAP.keys(), key=len, reverse=True):
        if ticker.endswith(suffix):
            symbol = ticker[:-len(suffix)]
            return f"{symbol}.{EXCHANGE_MAP[suffix]}"

    for suffix in SAME_SUFFIX:
        if ticker.endswith(suffix):
            symbol = ticker[:-len(suffix)]
            return f"{symbol}.{suffix[1:]}"

    return f"{ticker}.US"


def download_eodhd(ticker, lookback_days):
    """
    Download daily OHLCV from EODHD.

    Returns DataFrame with DatetimeIndex (UTC) and Open/High/Low/Close/Volume,
    or None on failure.
    """
    eodhd_ticker = _yahoo_to_eodhd(ticker)

    end = datetime.now()
    start = end - timedelta(days=lookback_days + 30)

    url = f"{EODHD_BASE_URL}/{eodhd_ticker}"
    params = {
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "period": "d",
        "api_token": EODHD_API_KEY,
        "fmt": "json",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if not data or not isinstance(data, list):
            return None

        df = pd.DataFrame(data)
        if df.empty or len(df) < 50:
            return None

        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.set_index("date").sort_index()

        # Adjust OHLC using adjusted_close/close ratio
        if "adjusted_close" in df.columns and "close" in df.columns:
            ratio = df["adjusted_close"] / df["close"].replace(0, float("nan"))
            ratio = ratio.fillna(1.0)
            df["open"] = df["open"] * ratio
            df["high"] = df["high"] * ratio
            df["low"] = df["low"] * ratio
            df["close"] = df["adjusted_close"]

        df = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })
        cols = ["Open", "High", "Low", "Close", "Volume"]
        df = df[[c for c in cols if c in df.columns]]

        # Rate limiting: ~16 req/sec safe
        time.sleep(0.06)

        return df if len(df) >= 50 else None

    except Exception:
        return None
