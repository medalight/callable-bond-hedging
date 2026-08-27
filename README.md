# Hedging a Book of Callable Bonds

Can you strip the interest rate risk out of a portfolio of emerging market callable bonds using nothing but plain vanilla interest rate swaps? This project builds the pricing machinery from scratch to answer that quantitatively, and finds that you can remove **95% of the book's interest rate risk with four swap trades**, for a rebalancing cost of about **0.3 basis points of market value per year**.

---

## The problem

A AAA rated institution funds itself at SOFR flat and buys emerging market (EM) callable bonds. The credit risk is deliberate: it is the mandate, and it is how the desk earns its spread. What it wants to remove is the interest rate risk.

A callable bond's call decision depends on **two stochastic factors**, interest rates *and* the issuer's credit spread. An interest rate swap sees only one of them. In principle you cannot fully hedge an option that depends on two factors with an instrument that responds to one.

The practical answer is not to hedge each bond's embedded option. It is to **aggregate the whole book's rate risk into buckets along the curve and immunize those buckets with a strip of vanilla swaps**, then rebalance as the immunization decays.

## Why not just hedge the option directly

The obvious first idea is to replicate the embedded call rather than work around it: enter a cancellable swap, meaning a vanilla payer swap plus a Bermudan swaption giving the right to cancel it early. Option for option, matched against the bond's own call.

However, the Bermudan swaption's exercise decision, cancel the swap or keep it, is driven by comparing intrinsic value to continuation value at each date. That decision depends on **interest rates only**. The bond's call decision depends on **rates and the issuer's credit spread together**, since calling only makes sense if the issuer can actually refinance cheaper, which needs low rates and a spread that has not widened too much.

For a AAA to A+ issuer this mismatch barely matters since spread is stable, so the two exercise boundaries stay close together and a rates driven Bermudan tracks the bond well.

For a high yield or EM issuer it does matter. Take a scenario where rates fall and the credit spread widens or holds. On rates alone, cancelling the swap looks optimal. But the bond is not actually going to be called, because the wider spread kills the issuer's refinancing math. The hedge switches itself off exactly when the underlying rate risk is still there, leaving a choice between re-hedging at the new lower rate (a loss if rates keep falling) or not re-hedging (unprotected if rates snap back). High yield bonds compound this with step down call premiums, designed to make early calls expensive and unlikely, a feature a standard Bermudan swaption has no way to represent, since its strike cannot vary with time.

That is the starting point of this project. Trying to hedge the option itself introduces a second, harder mismatch on top of the first. The simpler approach, hedge the book's rate risk with vanilla swaps and leave the credit risk alone, gives up on being exact but avoids ever exercising on the wrong signal, since a vanilla swap has no optionality to mistime in the first place. What it costs instead is the rebalancing this project goes on to measure.

## The result

99% one day value at risk (VaR) on a $36M book of four EM callable bonds:

| Book | Rate VaR | Spread VaR | Total VaR |
|---|---|---|---|
| Unhedged | $97.8k | $168.1k | $183.7k |
| Immunized with 4 vanilla swaps | **$5.0k** | $168.1k | $170.7k |

Four liquid trades remove 95% of the interest rate risk and leave the credit risk, the risk the portfolio exists to hold, untouched to the dollar.

Read the **decomposition, not the total**. Total VaR barely moves because two roughly independent risks combine close to quadrature, so removing the rate leg entirely just drops the total to the spread floor. A hedge that drove total VaR to zero would mean the mandate had been hedged away by mistake.

## Three findings worth stating

1. The bond studied here is a five year, non call two (5NC2). Its option adjusted DV01 is $2,452 against $4,145 for the same bond without the call, so 59% of a bullet's rate risk. But bucketing that risk along the curve shows it concentrated at the **1Y** point, with almost nothing at the **2Y** call date. A naive hedge sized on total DV01 and placed at the call date therefore fails at the wrong *pillar*, not merely at the wrong size: it creates a short where no risk existed while leaving the real exposure open.

2. Four callables with four different call schedules put their risk in four different places on the curve, and no single tenor swap could hedge more than one of them. Summing their key rate duration (KRD) reports collapses the book into one row of five numbers that four swaps cancel exactly.

3. Widen every issuer's credit spread by 300bp with **no interest rate moving at all**, and the book's DV01 walks from $8,606 to $10,128 while the swap strip stays frozen at $8,617. A $1,511 per basis point exposure opens up without a single day of profit and loss to warn you. The cause is the coupling: spreads move the call's moneyness, which moves the expected life of the bonds, which moves their rate sensitivity, and the swaps cannot see any of it. No static sizing fixes this. You either rebalance or you buy the optionality back and pay the premium.

**And rebalancing is cheap.** Re-solving the strip quarterly through a year of steadily widening spreads costs roughly $949 on a $36.7M book, about 0.3bp of market value annually, against $97.8k of daily rate VaR removed. A Bermudan swaption overlay would hedge the option exactly and need no rebalancing, but charges its premium up front with a wide bid/ask and thin liquidity in EM sizes. The strip converts that premium into a small running cost.

## Repository contents

| File | What it is |
|---|---|
| `fixed_income.py` | The pricing engine: curve bootstrapping, swap and bond pricers, the binomial lattice, OAS solver. No hedging logic, nothing study specific. |
| `01_pricing_engine.ipynb` | Builds and validates the engine against published examples before it is trusted. |
| `02_hedging_the_book.ipynb` | The study: the position, the hedges, the portfolio, VaR, decay, rebalancing cost, limitations. |
| `market_data.csv` | The rate quotes the curve is bootstrapped from. See below. |

## Methodology

**The discount curve.** Overnight index swap (OIS) quotes out to 6 months invert directly to discount factors. Par swap rates from 1Y to 30Y are bootstrapped from the condition that a par swap prices to zero. Because the quotes are not consecutive (5Y, then 7Y, then 10Y), the 7Y point needs a 6Y discount factor that must be interpolated from a 7Y point not yet solved. That circularity is resolved by sweeping the whole curve until it stops moving, a fixed point iteration converging in 16 passes. Interpolation is log linear in the discount factor, equivalently linear in the zero rate, which keeps forward rates smooth.

**Bond and swap pricing.** Bonds are priced off the curve with real settlement dates and act/act accrued interest, so mid period settlement is handled properly. Yield to maturity is then solved by root finding as the flat rate reproducing that price, making yield an output rather than an input. Swaps use the telescoping floating leg identity, so no forward projection is needed on a single curve.

**Callable bonds.** A callable's cash flows are state dependent, so there is nothing to discount until future rates are modelled. This uses a Black-Derman-Toy style binomial short rate lattice with nodes spaced `r_j = r_low · exp(2jσ)`, making rates lognormal. Each time step is calibrated by solving for the single unknown low rate that makes a par bond of that maturity value back to 100 on the tree built so far, which is what makes the tree arbitrage free. Valuation rolls backward from maturity, and the embedded option is one line: the issuer caps each node at the call price, an investor would floor it at the put price.

**Option adjusted spread.** The constant spread added to every node that reconciles model price with market price, solved by root finding.

**Risk measurement.** Effective duration and key rate durations are computed by bumping the curve and **fully rebuilding and repricing the tree**, never by an analytic formula, since analytic duration assumes cash flows that do not move. The option adjusted spread is held constant across bumps.

**The hedge.** The book's aggregate KRD vector is the hedging target. A swap of tenor T has exactly zero sensitivity beyond T, so ordering the pillars longest to shortest makes the sensitivity matrix triangular and the notionals solve by back substitution, exactly rather than by least squares fitting.

**VaR.** Historical simulation over 500 daily scenarios, with the four bonds fully revalued on the lattice in every scenario and swap profit and loss entering at first order through KRD. Rate and spread factors are simulated separately so their contributions can be read apart. Reported with expected shortfall and a Basel style exception count.

**Validation.** The lattice, OAS solver and effective duration are checked against worked examples in Fabozzi's *Handbook of Fixed Income Securities*, Chapter 37 (Fabozzi, Kalotay and Dorigan) and Chapter 39 (Audley, Chin and Ramamurthy). The tree reproduces Exhibit 37-9 node by node, and the option free, callable and putable prices (104.643, 102.899, 105.327), the 35bp OAS example and an effective duration of 2.24 all match. Notebook 1 shows those checks.

## About the data

`market_data.csv` is an **illustrative** set of quotes, not a market snapshot. The levels and curve shape are realistic (SOFR OIS out to 6 months, par swap rates from 1Y to 30Y), which is all the study needs, since its conclusions come from the *shape* of a callable's rate sensitivity rather than from any particular rate level. To run on real data, replace the file with quotes in the same four column format (`Tenor, Years, Rate (%), Instrument`) and rerun. Nothing else changes.

The four bonds in the portfolio are likewise constructed rather than real issues, chosen to differ in coupon, spread, maturity and call schedule so that their risk profiles genuinely conflict.

## Limitations

The limitations are discussed at length in Notebook 2 and are worth reading before quoting any number here. The most important:

- **Credit is modelled as a spread, never as a default.** Issuer curves are the SOFR curve plus a flat spread. There is no hazard rate, default probability, recovery assumption or CDS curve. What is computed is therefore **spread VaR**, mark to market repricing risk, and never credit VaR. Real credit loss is skewed and fat tailed in a way no Gaussian spread shock reaches, so this is a floor on the true risk rather than a measure of it.
- **Volatility is assumed.** 15%, at every rate level. It is also the single most price sensitive input in the model.
- **One factor in the tree**, even though the entire thesis is that the problem has two. Spread enters as an exogenous shift, capturing levels but not dynamics.
- **The VaR history is synthetic.** Gaussian factors, chosen rather than estimated, so every VaR figure is conditional on that calibration and is not an empirical estimate.

None of these change the qualitative conclusion, because the two factor structure of the residual is a property of the instrument rather than of the model. They would move the magnitudes.

## Running it

```bash
pip install -r requirements.txt
jupyter notebook
```

Run the notebooks from the repository root so `market_data.csv` and `fixed_income.py` resolve. Requires numpy, pandas, scipy, matplotlib and python-dateutil.

## A note on how this was built

The thesis, the modelling approach, the validation against published examples and the interpretation of every result are my own. I used Claude (Anthropic) as a coding assistant to implement the Python, build the visualisations and iterate on structure. All numbers were checked against the textbook's worked examples before being trusted.
