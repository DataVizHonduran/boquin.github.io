---
description: Create an earnings tearsheet for a company
args:
  ticker:
    description: Stock ticker symbol (e.g., "INTC", "AAPL", "MSFT")
    required: true
  quarter:
    description: Fiscal quarter (e.g., "Q4 FY2025", "Q1 FY2026")
    required: false
---

You are creating an earnings tearsheet for **{{ticker}}** to be published on boquin.xyz.

# Task

1. **Research the most recent earnings** for {{ticker}}:
   - Search for the latest earnings release, press release, and earnings call transcript
   - Find key metrics: Revenue, EPS (GAAP and Non-GAAP), margins, segment performance
   - Look for guidance for next quarter and full year
   - Find analyst consensus estimates to compare actual vs. expected
   - Note the stock price reaction (regular hours and after-hours)

2. **Create the tearsheet** following this exact structure:

```markdown
# [TICKER] [QUARTER] Review: [Compelling Headline Summary]

**Report Date:** [Today's date]
**Earnings Release Date:** [Date earnings were released]
**Fiscal Period:** [Quarter and end date]

---

## THE DASHBOARD

| Metric | Actual | YoY % | vs. Consensus |
|--------|--------|-------|---------------|
| **Revenue** | $X.XB | +X% | Beat/Miss by X% |
| **Non-GAAP EPS** | $X.XX | +X% | Beat/Miss |
| **GAAP EPS** | $X.XX | +X% | N/A |
| **Operating Margin** | X% | +Xbps | In-line/Beat/Miss |
| [Segment 1] | $X.XB | +X% | Beat/Miss |
| [Segment 2] | $X.XB | +X% | Beat/Miss |

---

## EXECUTIVE SUMMARY

- **[Key Insight 1]:** [2-3 sentences explaining the most important takeaway]

- **[Key Insight 2]:** [What drove the beat/miss]

- **[Key Insight 3]:** [Guidance reaction and stock movement]

- **[Key Insight 4]:** [Strategic or thematic implication]

---

## GUIDANCE & OUTLOOK

### Next Quarter Guidance
| Metric | Guidance |
|--------|----------|
| Revenue | $X.XB - $X.XB |
| EPS | $X.XX - $X.XX |

### Full Year Guidance
| Metric | Guidance | Vs. Consensus |
|--------|----------|---------------|
| Revenue | $X.XB - $X.XB | Above/Below/In-line |
| EPS | $X.XX - $X.XX | Above/Below/In-line |

**Management Commentary:** [Key quotes or themes from the call]

---

## SEGMENT PERFORMANCE

### [Segment 1 Name] ($X.XB, +X% YoY)
- [Key driver 1]
- [Key driver 2]
- [Outlook]

### [Segment 2 Name] ($X.XB, +X% YoY)
- [Key driver 1]
- [Key driver 2]
- [Outlook]

---

## CAPITAL ALLOCATION & BALANCE SHEET

### Balance Sheet
| Metric | Amount |
|--------|--------|
| Cash & Equivalents | $X.XB |
| Total Debt | $X.XB |
| Net Cash (Debt) | $X.XB |

### Cash Flow
- **Operating Cash Flow:** $X.XB
- **Free Cash Flow:** $X.XB
- **Capex:** $X.XB

### Shareholder Returns
- **Buybacks:** [Amount and details]
- **Dividend:** [Details if applicable]

---

## ANALYST TAKEAWAY

**[Thesis assessment in bold.]** [2-3 sentences on investment implications, valuation, key risks, and recommendation/outlook. Be specific about catalysts and what would change the view.]

---

## Sources

- [Source 1](URL)
- [Source 2](URL)
- [Source 3](URL)
```

3. **Save the file** to `/reports/earnings/{{ticker}}-[YYYY-MM-DD].md` where the date is today's date

4. **Regenerate the index** by running:
   ```bash
   cd /home/user/boquin.github.io && python scripts/generate_earnings_index.py
   ```

5. **Commit and push** with message: "Add {{ticker}} earnings tearsheet - [TODAY'S DATE]"

# Quality Guidelines

- **Be specific**: Use exact numbers, not vague descriptions
- **Context matters**: Compare to consensus, prior quarter, and year-ago period
- **Focus on "so what"**: Every data point should connect to an investment implication
- **Headline should hook**: Make it clear if this was a beat/miss and why it matters
- **Sources required**: Always cite earnings release, transcript, and data sources
- **Stock reaction**: Include both regular and after-hours price movement with percentages

# Important Notes

- If quarter is not provided, research to find the most recently reported quarter
- The ticker in the filename should be uppercase
- Use today's date for the report date and filename
- Be thorough but concise - aim for 100-200 lines
- Include the disclaimer footer if the report contains forward-looking statements
