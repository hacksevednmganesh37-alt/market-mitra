"""Bite-size lessons attached to each decision, so a beginner learns the concept behind it."""

LESSONS = {
    "stop_loss": "Stop-loss: a price decided BEFORE buying where you exit if you're wrong. "
                 "It turns 'hope' into a plan and keeps one bad trade from wiping out many good ones.",
    "position_size": "Position sizing: never put everything in one idea. Capping each trade at a share of your "
                     "money means a single loss stays small.",
    "rsi": "RSI (Relative Strength Index, 0-100) measures how fast a price has moved. Above ~70 it's 'overbought' "
           "(often due a pause), below ~30 'oversold'. Buying after a huge run-up is chasing.",
    "trend": "Trend: when the price is above its 20-day and 50-day averages, buyers are in control. "
             "Trading with the trend is usually safer than fighting it.",
    "confidence": "Conviction: if the evidence is mixed, the best trade is often no trade. "
                  "Waiting costs nothing; a forced trade can cost a lot.",
    "cut_loss": "Cutting losses: selling at the stop-loss feels bad, but small planned losses are the price "
                "of staying in the game. Big unplanned ones end it.",
    "take_profit": "Booking profit: a target set in advance stops greed from turning a winner into a loser.",
    "news": "News vs price: good news is often already 'priced in'. Watch how the price reacts, not just the headline.",
    "diversify": "Diversification: too many open positions at once is hard to track and multiplies risk "
                 "when the whole market falls together.",
    "revenge": "Revenge trading: jumping straight back into a stock that just stopped you out is emotion, "
               "not analysis. A short cool-off keeps decisions calm.",
    "patience": "Patience: holding cash is a position too. Most of a good trader's time is spent waiting "
                "for a clear setup.",
    "sell_weak": "Exiting when the story changes: if the reasons you bought are gone, don't wait for the stop-loss.",
}


def for_decision(d: dict) -> str:
    """Pick the most relevant lesson for a decision made by the Trader / risk rules."""
    veto = (d.get("veto") or "").lower()
    reason = (d.get("reason") or "").lower()
    if veto:
        if "rsi" in veto:
            return LESSONS["rsi"]
        if "confidence" in veto:
            return LESSONS["confidence"]
        if "cool-off" in veto:
            return LESSONS["revenge"]
        if "open positions" in veto:
            return LESSONS["diversify"]
        return LESSONS["position_size"]
    if d.get("action") == "SELL":
        if "stop-loss" in reason:
            return LESSONS["cut_loss"]
        if "target" in reason:
            return LESSONS["take_profit"]
        return LESSONS["sell_weak"]
    if d.get("action") == "BUY":
        return LESSONS["stop_loss"] if d.get("status") == "approved" else LESSONS["position_size"]
    if "news" in reason:
        return LESSONS["news"]
    if "trend" in reason or "average" in reason:
        return LESSONS["trend"]
    return LESSONS["patience"]
