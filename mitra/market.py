"""Market data + technical indicators (prices from Yahoo Finance via yfinance)."""
import math
import time

import pandas as pd

MARKETS = {
    "IN": {
        "name": "Indian stocks (NSE)",
        "currency": "₹",
        "benchmark": "^NSEI",
        "benchmark_name": "Nifty 50",
        "fractional": False,
        "watchlist": ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
                      "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "AXISBANK.NS"],
    },
    "US": {
        "name": "US stocks",
        "currency": "$",
        "benchmark": "^GSPC",
        "benchmark_name": "S&P 500",
        "fractional": False,
        "watchlist": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM"],
    },
    "CRYPTO": {
        "name": "Crypto",
        "currency": "$",
        "benchmark": "BTC-USD",
        "benchmark_name": "Bitcoin",
        "fractional": True,
        "watchlist": ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "ADA-USD"],
    },
}

_cache: dict[str, tuple[float, pd.DataFrame]] = {}
CACHE_SECONDS = 300


def history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    """Daily OHLCV for one ticker (cached for a few minutes)."""
    hit = _cache.get(ticker)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    import yfinance as yf  # imported here so the rest of the code can be tested without it

    df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
    df = df.dropna(subset=["Close"])
    if df.empty:
        raise ValueError(f"No price data for {ticker}")
    _cache[ticker] = (time.time(), df)
    return df


def last_price(ticker: str) -> float:
    return float(history(ticker)["Close"].iloc[-1])


def rsi(close: pd.Series, n: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] else math.inf
    return float(100 - 100 / (1 + rs))


def atr(df: pd.DataFrame, n: int = 14) -> float:
    prev = df["Close"].shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


def pct(a: float, b: float) -> float:
    return round((a / b - 1) * 100, 2) if b else 0.0


def technicals(ticker: str, df: pd.DataFrame | None = None) -> dict:
    """Indicators + a rule-based technical score from -100 (very bearish) to +100 (very bullish).

    Pass `df` (history cut at some past day) to compute what the indicators looked like back then."""
    df = history(ticker) if df is None else df
    close = df["Close"]
    price = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else sma20
    r = rsi(close)
    vol20 = float(close.pct_change().rolling(20).std().iloc[-1] * 100)
    chg1 = pct(price, float(close.iloc[-2])) if len(close) > 1 else 0.0
    chg5 = pct(price, float(close.iloc[-6])) if len(close) > 5 else 0.0
    chg20 = pct(price, float(close.iloc[-21])) if len(close) > 20 else 0.0
    hi20, lo20 = float(close.tail(20).max()), float(close.tail(20).min())
    vol_ratio = float(df["Volume"].tail(5).mean() / df["Volume"].tail(50).mean()) if df["Volume"].tail(50).mean() else 1.0

    score, notes = 0.0, []
    if price > sma20 > sma50:
        score += 35; notes.append("uptrend (price > 20-day > 50-day average)")
    elif price < sma20 < sma50:
        score -= 35; notes.append("downtrend (price < 20-day < 50-day average)")
    elif price > sma50:
        score += 10; notes.append("above 50-day average")
    else:
        score -= 10; notes.append("below 50-day average")
    if r < 30:
        score += 20; notes.append(f"oversold (RSI {r:.0f})")
    elif r > 70:
        score -= 20; notes.append(f"overbought (RSI {r:.0f})")
    else:
        notes.append(f"RSI {r:.0f} (neutral)")
    score += max(-25, min(25, chg20 * 1.5))
    if chg20:
        notes.append(f"{chg20:+.1f}% in 20 days")
    if price >= hi20 * 0.99 and vol_ratio > 1.2:
        score += 10; notes.append("breaking out on higher volume")
    score = max(-100, min(100, score))

    return {
        "ticker": ticker, "price": round(price, 4), "change_1d": chg1, "change_5d": chg5, "change_20d": chg20,
        "sma20": round(sma20, 4), "sma50": round(sma50, 4), "rsi": round(r, 1), "atr": round(atr(df), 4),
        "volatility": round(vol20, 2), "high_20d": round(hi20, 4), "low_20d": round(lo20, 4),
        "volume_ratio": round(vol_ratio, 2), "tech_score": round(score), "tech_notes": notes,
        "spark": [round(float(x), 4) for x in close.tail(30)],
    }
