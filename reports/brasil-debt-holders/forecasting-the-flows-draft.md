# Forecasting the Flows — Draft Content
> Brazil Federal Debt Holders Dashboard · t5 tab

---

## Section 1 — Flow Proxies

*Observable, near-real-time indicators that proxy for each investor class's demand before the monthly RMD is published (~3–4 week lag).*

---

### Banks (Instituições Financeiras)

**Basel III LCR ratio** — Core driver
BCB requires banks to hold High Quality Liquid Assets (HQLA) equal to 100% of projected 30-day stressed outflows. Brazilian HQLA is almost exclusively federal securities (LFTs, LTNs, NTN-Bs). Monthly LCR disclosures signal whether banks are at the floor and forced to buy, or holding excess buffer.

**Credit growth vs. deposit growth (BCB Nota de Crédito)** — Supporting
When loan growth lags deposit funding growth, the surplus lands in government bonds. Monitor the spread between total deposits and total credit outstanding; a widening gap is a leading indicator of bank DPF demand.

**CDB / LCI / LCA net issuance (ANBIMA monthly)** — Supporting
Banks that grow their liability book faster than their loan book must deploy the excess. Net issuance of CDBs and tax-exempt LCIs/LCAs above credit origination growth tends to flow into LFTs.

**COPOM rate decisions** — Directional
Rate hikes increase LFT daily carry, making them more attractive vs. credit risk on a risk-adjusted basis. Rate cuts do the opposite and can shift banks toward longer-duration NTN-Fs for yield pickup.

---

### Investment Funds (Fundos de Investimento)

**ANBIMA fund flow data (weekly)** — Core driver
Net subscriptions/redemptions by fund category (DI, renda fixa, multimercado) are the most direct proxy. DI fund inflows translate almost mechanically into LFT demand; renda fixa inflows into LTN/NTN-B demand.

**CRI / CRA new issuance (CVM/ANBIMA)** — Structural shift
Tax-exempt credit instruments compete directly with government bonds for fixed income fund allocations. Heavy CRI/CRA issuance months reliably correlate with government bond underperformance in fund portfolios.

**Tesouro Direto net flows** — Supporting
Retail Tesouro Direto net purchases signal broad fixed income sentiment. TD growth reduces the intermediary role of fixed income funds, structurally compressing DI fund AUM over time.

**Multimercado leverage (ANBIMA risk reports)** — Tactical
When multimercado funds are running high gross leverage in DI futures, they also tend to hold more government bond collateral. Futures positioning data (B3) gives a weekly read. Returns based analysis of "O Kit Brasil" can proxy positioning.

---

### Pensions (Previdência)

**PREVIC funded ratio reports** — Core driver
Funded ratio below 100% forces pension funds to extend duration and increase NTN-B allocations to close the gap between assets and actuarial liability. Published quarterly but widely tracked in real time by plan sponsors.

**NTN-B real yield vs. actuarial target** — Core driver
The actuarial benchmark for most Brazilian defined-benefit plans is INPC/IPCA + 5.5–6.0%/year. When NTN-B real yields trade above this level, buying is nearly automatic. When below, demand stalls.

**Benefit payment schedule / net cash flow** — Supporting
Pension funds with negative net cash flow (outflows > contributions) are forced sellers of LFTs to fund monthly benefits. Periods of demographic stress (more retirees) compress LFT holdings and increase NTN-B duration bias.

**FUNPRESP contribution flows** — Structural
The federal civil servant pension fund grows at a fixed rate tied to enrollment and contribution rules. Its DPF demand is policy-driven and largely insensitive to market signals — a baseline bid that can be modeled from payroll data.

---

### Foreigners (Não-residentes)

**BCB capital flow report (weekly)** — Core driver
BCB publishes weekly portfolio investment flows in fixed income ~10 days after the reference week — roughly 3 weeks ahead of the RMD. The closest real-time proxy available.

**B3 foreign custody data** — Core driver
B3 publishes daily foreign holdings of DPMFi bonds in custody. Provides near-daily resolution on foreign demand direction even before BCB or RMD data.

**Cupom Cambial** — Supporting
At times, foreign hedge funds can buy LTNs and hedge out FX while getting a pickup over USD equivalent debt that is quite attractive.

---

## Section 2 — Price Signals

*Market prices that influence or predict each investor class's allocation decisions.*

---

### Banks (Instituições Financeiras)

**SELIC / DI rate level** — Primary
LFTs reprice daily at SELIC. A high absolute SELIC rate makes LFTs attractive vs. private credit on a risk-adjusted basis — banks earn near-sovereign returns with zero duration risk. The higher the SELIC, the more LFT-heavy bank portfolios tend to be.

**Short end of the yield curve (DI futures, 1–3Y)** — Primary
When the front end of the DI curve is inverted or flat, banks favor LFTs over LTNs for LCR purposes (LFTs have no mark-to-market volatility). A steep curve can encourage extension into LTNs for yield pickup.

**CDB spread over DI** — Supporting
When bank funding costs (CDB rates) rise above DI, NIM compression incentivizes more sovereign bond holding as a low-risk, liquid asset. Narrow CDB spreads allow banks to be more selective.

**BCB COPOM forward guidance** — Directional
Clear rate guidance anchors duration decisions. A hiking cycle → LFT overweight; credible easing cycle → incremental shift to LTN/NTN-F.

---

### Investment Funds (Fundos de Investimento)

**DI rate vs. IPCA (ex-ante real rate)** — Primary
High real rates attract inflows to fixed income funds broadly. When the DI-implied real rate exceeds ~7–8%, retail allocation to fixed income funds surges, and government bond demand follows.

**LTN / NTN-F term premium** — Supporting
The slope between 1Y and 5Y LTN yields determines whether funds extend duration. A steep curve (>150bps) encourages duration extension into NTN-Fs; a flat or inverted curve pushes funds to LFTs or shorter LTNs.

**CRI/CRA spread vs. LTN (same duration)** — Structural
The key substitution signal for fixed income fund managers. When tax-exempt credit spreads compress toward government bond yields (net of tax advantage), funds rotate back into government bonds. Currently tracking ~80–120bps net spread.

**Ibovespa / equity risk premium** — Tactical
When equities are cheap relative to bonds (earnings yield well above NTN-B real yield), multimercado funds rotate from fixed income to equities, reducing DPF demand. The equity/bond frontier matters for multi-asset allocations.

---

### Pensions (Previdência)

**NTN-B real yield curve (2035, 2045, 2050)** — Primary
The single most important price signal for pension demand. Long-end NTN-B real yields above IPCA + 6.5% have historically triggered aggressive buying by defined-benefit plans. Currently ~7.0–7.5% on the long end — elevated by historical standards.

**NTN-B curve shape (short vs. long end)** — Primary
When long-end NTN-Bs yield 50–100bps more than 5Y NTN-Bs, pension funds extend duration to match long-dated liabilities. When the curve is flat or inverted, they park in shorter NTN-Bs and LFTs.

**IPCA expectations — FOCUS survey (2Y ahead)** — Supporting
Higher inflation expectations erode the attractiveness of nominal bonds (LTN/NTN-F) for pensions with IPCA-linked liabilities. Elevated FOCUS inflation = tilt toward NTN-B over NTN-F.

**Actuarial discount rate regulatory floor (CNPC)** — Structural
CNPC Resolution 30 sets maximum discount rates for actuarial liability valuation at INPC + 4.16%–6.05% depending on plan vintage. When market NTN-B yields approach or breach the cap, pensions are technically in surplus — reducing urgency to buy.

---

### Foreigners (Não-residentes)

**Spot trends as it pertains to CTA momentum signals

**Carry to vol


---

*Draft — not published. Last updated: March 2026.*
