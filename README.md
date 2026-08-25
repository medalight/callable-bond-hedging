# callable-bond-hedging
Pricing, KRD immunization, and VaR analysis of callable EM bonds hedged with vanilla interest-rate swaps.

**Immunizing a book of callable EM bonds with vanilla swaps — and measuring, in VaR, how far that gets you.**

## The question

If a bond's call decision depends on two stochastic factors — interest rates and credit spread — you generally cannot hedge it with an instrument that sees only one of them. Taken literally, that sounds like a dead end for anyone holding callable EM paper.

It isn't. The practical answer is not to hedge each bond's embedded option, but to **immunize a portfolio's aggregate interest rate risk, bucket by bucket, with a strip of plain vanilla swaps** — and then rebalance, because the immunization decays. This notebook builds the pricing and risk machinery from scratch to test that claim quantitatively, rather than just assert it.

## The result

99% daily VaR on a $36M book of 4 EM callable bonds:

| Book | Rate VaR | Spread VaR | Total VaR |
|---|---|---|---|
| Unhedged | $97.8k | $168.1k | $183.7k |
| Immunized with 4 vanilla swaps | **$5.0k** | $168.1k | $170.7k |

Four liquid swap trades remove **95% of the book's interest rate risk** and leave the credit risk — the reason the portfolio exists — untouched to the dollar. The same immunization, stress-tested under a 300bp credit spread widening with **zero** rate movement, develops a **$1,511/bp** unhedged gap: proof the hedge decays structurally and must be actively rebalanced, not a sizing flaw.

## What's built

Everything from scratch in `numpy` / `pandas` / `scipy` / `matplotlib`. No QuantLib.

**Part I — The Toolkit**
1. SOFR discount curve bootstrapping (OIS + par swap rates)
2. Vanilla interest rate swap pricer
3. Bond pricer with real calendar dates
4. Key-rate duration (KRD) engine
5. Binomial interest rate lattice (Black-Derman-Toy) for callable/putable bonds
6. Option-adjusted spread (OAS) solver

**Part II — One Bond, Understood Properly**
7. Effective duration and convexity
8. The KRD fingerprint: bullet vs. callable
9. Three hedging strategies, increasing in sophistication (unhedged → naive single-swap → KRD strip)

**Part III — Immunizing the Book**
10. DV01 immunization at portfolio level, across 4 heterogeneous EM callables
11. What this model cannot see — an explicit limitations section

## Key findings

- A callable bond's OA-DV01 (**$2,452**) sits at only **59%** of the equivalent bullet's (**$4,145**) — and that ratio moves with the rate level.
- Its interest rate risk concentrates at the **1Y** curve pillar ($1,247), almost nowhere at the **2Y** call date ($15) — which is why a naive single-tenor swap hedge fails: it leaves $1,210 unhedged at 1Y while creating a **$1,910** short position at 2Y that was never there.
- Key rate durations **aggregate additively** across a portfolio. Four bonds with four different call schedules, none of which share a hedging profile, collapse into one risk vector that a single 4-swap strip neutralizes exactly.
- The hedge is a snapshot, not a fixture: it decays as credit spreads move the exercise boundary, even with rates held perfectly still.

## Limitations

Explicitly discussed in Section 11: constant volatility, a one-factor tree, credit modeled as a spread rather than default risk, annual time steps, constant-OAS curve bumping, a frictionless call rule, linearized (not fully revalued) swap P&L inside the VaR simulation, and a synthetic (not historical) VaR calibration. All VaR figures should be read as *"under the illustrative synthetic factor calibration used here,"* not as empirical estimates.

## Methodology

The thesis, the modeling approach, the validation against Fabozzi, and the interpretation of every result are my own. I used Claude (Anthropic) as a coding assistant to implement the Python, in translating the pricing and hedging logic into working code, building the visualizations, and iterating on the notebook's structure. All numbers were independently checked against the textbook's published examples before being trusted.
