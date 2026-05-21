## GOOGL Derivatives Strategy Report: May 21, 2026

### 1. Best Collar Combinations
The following combinations optimize the trade-off between downside protection and capital outlay. Note that long-dated collars require significant debit due to the high premium on long-dated calls.

| Expiry | Put Strike | Call Strike | Net Cost | Scenario |
| :--- | :--- | :--- | :--- | :--- |
| 2026-06-05 | $300 | $485 | $0.02 Credit | **Income/Neutral:** Minimal cost; protects against a ~22% drawdown while capturing upside to $485. |
| 2026-09-18 | $300 | $495 | $1.88 Debit | **Moderate Protection:** Hedging a mid-term correction; allows for significant growth with a defined floor. |
| 2027-01-15 | $300 | $495 | $6.42 Debit | **Long-Term Hedge:** High-conviction protection for a 12-month horizon; expensive but secures the floor. |

### 2. OI Hot Spots
*   **Put Concentration (The Floor):** Massive Open Interest is concentrated at the **$280 and $300 strikes** for the Sept 2026 and Jan 2027 expiries (e.g., 11,577 OI at $280 Put). This suggests a heavy "gamma floor" where market makers may need to defend these levels, potentially slowing downward momentum near these strikes.
*   **Call Concentration (The Ceiling):** Significant OI exists at the **$475–$480 calls** for 2027 and 2028. This indicates a psychological resistance zone; expect heavy selling pressure or "pinning" risk near these levels as expiry approaches.

### 3. 52wk Range Context
*   **Cheap Volatility (Puts):** Almost all OTM Puts (strikes $280–$300) are trading at the extreme low end (0%–4%) of their 52wk price range. This suggests that downside protection is currently relatively inexpensive, likely due to low realized volatility or a lack of recent "black swan" pricing.
*   **Expensive Volatility (Calls):** Long-dated Calls (2027–2028) are trading at the high end (76%–100%) of their 52wk range. This implies the market is pricing in a high probability of a massive breakout, making "buying the upside" via collars very costly.

### 4. Actionable Trade Idea: The "Low-Cost Structural Hedge"
For a client seeking to protect a large GOOGL position through the next year without heavy capital drag:

*   **Trade:** Long Sept 18, 2026 Collar
*   **Execution:** Buy $300 Put / Sell $495 Call
*   **Net Cost:** $1.88 per share ($188 per contract)
*   **Max Loss:** $87.66 per share (Spot $387.66 - $300 Put strike + $1.88 premium)
*   **Max Profit:** $105.44 per share (Call strike $495 - Spot $387.66 - $1.88 premium)
*   **Rationale:** This trade utilizes the "cheap" put pricing observed in the data to provide a hard floor at $300, while the $495 call is far enough OTM to capture most of the remaining upside, despite the debit cost.