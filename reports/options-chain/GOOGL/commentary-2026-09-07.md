## Best Collar Combinations

| Expiry | Put Strike | Call Strike | Net Cost | Scenario |
|---|---|---|---|---|
| 2026-12-18 | $265 | $435 | $0.83 debit | Cheapest near-term collar in the book — floor -21.7%, cap +28.5%, both legs carry real OI (1,939 puts / 577 calls). Good fit for a holder wanting near-costless downside insurance into year-end without giving up much upside room. |
| 2027-01-15 | $265 | $435 | $1.59 debit | Same strikes, one month further out — cost roughly doubles for the extra 30 days of protection. Put OI here is the deepest in the whole chain (8,573), so exit liquidity on the hedge leg is strong. |
| 2027-06-17 | $265 | $435 | $7.05 debit | Same strike pair a step further out shows a big jump in net cost (0.83 → 7.05) relative to the ~50% jump in DTE — term structure is pricing meaningfully more uncertainty into 2027, so this is a "pay up for time" hedge, not a cheap one. |

## OI Hot Spots

- **2026-12-18 $415 call — OI 5,822**, the single largest strike in the book. Sits ~23% above spot; a level like that concentrating open interest into a single December expiry often acts as a soft resistance/pin zone as expiry nears.
- **2027-01-15 $250 put — OI 10,683**, the deepest put in the chain, floor ~26% below spot. Read as sustained tail-hedge demand rather than a pin risk, since it's far OTM and January-dated (post-holidays, post-earnings).
- **2027-01-15 $265 put — OI 8,573**, second-deepest, floor ~22% below spot — same January cluster, reinforcing that January is where the crowd is buying protection.
- **2028-01-21 $420/$430 calls — OI 4,036 / 3,895**, notable given this is the longest-dated expiry in the sample; OI that far out usually reflects LEAPS-style directional positioning rather than short-term hedging.

## 52wk Range Context

Every OTM contract sampled — calls and puts, near-dated and far-dated — is pricing in the bottom quartile (0–25%) of its own 52-week range, with most near-term puts and calls sitting at or near 0%. That's consistent across the whole chain rather than isolated to one expiry, which points to broad-based richening of the *reference* high/low (i.e., these contracts were far more expensive earlier in their life, likely around an IV spike) rather than any single strike being unusually cheap today. Nothing in this OTM slice is trading rich relative to its own history — there's no obvious "sell the rip" candidate in this dataset.

## Trade Idea

**Buy the Dec-18-2026 $265 put / sell the Dec-18-2026 $435 call.** Net cost is $0.83 debit on a stock at $338.46 — about as close to costless as the book offers. Floor locks in max loss at -21.7% from spot ($265), cap gives up upside beyond +28.5% ($435). Both legs have workable OI (1,939 puts, 577 calls) for entry/exit. Max loss ≈ $74.29/share (spot to floor) + $0.83 premium; max gain ≈ $96.54/share (spot to cap) − $0.83 premium. Best suited to a holder who wants to protect a long position through year-end earnings without paying meaningfully for it.

*Note: commentary generated directly by Claude (session assistant) rather than the automated Gemma pipeline — HuggingFace inference credits for this repo were exhausted (402 Payment Required) at the time of this refresh.*
