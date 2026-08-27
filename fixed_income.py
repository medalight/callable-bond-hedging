"""Fixed income pricing engine: curves, swaps, bonds and a binomial lattice.

Nothing in here is specific to the hedging study. It is the general machinery
the notebooks import to bootstrap a discount curve from market quotes, price
vanilla swaps and coupon bonds off that curve, and value bonds with embedded
options on a calibrated short rate tree.

"""

import math
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from dateutil.relativedelta import relativedelta


# ---------------------------------------------------------------------------
# Discount curve
# ---------------------------------------------------------------------------
def load_market_data(path="market_data.csv"):
    """Read the quote file and add an empty discount factor column."""
    df = pd.read_csv(path)
    df["discount_factor"] = np.nan
    return df


def get_df(target_year, df_curve):
    """Discount factor for any year, log-linearly interpolated off the curve.

    Log-linear in the discount factor is linear in the zero rate, which keeps
    forward rates smooth. Interpolating the factors themselves would kink them.
    """
    # case 1: the year is quoted, just look it up
    matching_row = df_curve[df_curve["Years"] == target_year]
    if len(matching_row) > 0 and not np.isnan(matching_row["discount_factor"].values[0]):
        return matching_row["discount_factor"].values[0]

    # case 2: interpolate between the two nearest known years
    known = df_curve.dropna(subset=["discount_factor"])
    below = known[known["Years"] < target_year]
    above = known[known["Years"] > target_year]
    if len(below) == 0 or len(above) == 0:
        return np.nan          # nothing to interpolate from yet

    t1 = below["Years"].values[-1]
    df1 = below["discount_factor"].values[-1]
    t2 = above["Years"].values[0]
    df2 = above["discount_factor"].values[0]

    w = (target_year - t1) / (t2 - t1)
    return df1 ** (1 - w) * df2 ** w


def bootstrap_curve(df, n_ois=6, max_sweeps=20, tol=1e-10):
    """Bootstrap discount factors from OIS quotes and par swap rates.

    The swap quotes are not consecutive (5Y, then 7Y, then 10Y), so the 7Y
    needs D(6), which has to be interpolated from D(5) and D(7) while D(7) is
    still unknown. That circularity is resolved by sweeping the whole curve
    until it stops moving, a fixed point iteration.

    Returns the curve and the number of sweeps used.
    """
    # OIS: single payment, so the factor inverts directly
    for i in range(0, n_ois):
        rate = df.loc[i, "Rate (%)"] / 100
        years = df.loc[i, "Years"]
        df.loc[i, "discount_factor"] = 1 / (1 + rate * years)

    # pass 1: bootstrap what we can, skipping years we cannot interpolate yet
    for i in range(n_ois, len(df)):
        rate = df.loc[i, "Rate (%)"] / 100
        years = df.loc[i, "Years"]
        prior_dfs = 0.0
        for cy in range(1, int(years)):
            d = get_df(cy, df)
            if not np.isnan(d):
                prior_dfs += d
        df.loc[i, "discount_factor"] = (1 - rate * prior_dfs) / (1 + rate)

    # passes 2..n: every year is interpolatable now, sweep until stable
    for sweep in range(max_sweeps):
        max_change = 0.0
        for i in range(n_ois, len(df)):
            rate = df.loc[i, "Rate (%)"] / 100
            years = df.loc[i, "Years"]
            prior_dfs = 0.0
            for cy in range(1, int(years)):
                prior_dfs += get_df(cy, df)
            new_df = (1 - rate * prior_dfs) / (1 + rate)
            max_change = max(max_change, abs(new_df - df.loc[i, "discount_factor"]))
            df.loc[i, "discount_factor"] = new_df
        if max_change < tol:
            break

    return df, sweep + 1


def bump_curve(df_curve, tenor):
    """Copy of the curve with one pillar's zero rate shifted up by 1bp."""
    bumped = df_curve.copy()
    idx = (bumped["Years"] - tenor).abs().idxmin()     # closest curve point
    t = bumped.loc[idx, "Years"]
    bumped.loc[idx, "discount_factor"] *= np.exp(-0.0001 * t)
    return bumped


def zero_rates(df_curve):
    """Continuously compounded zero rates (%) for every quoted year > 0."""
    years = df_curve[df_curve["Years"] > 0]["Years"].values
    dfs = df_curve[df_curve["Years"] > 0]["discount_factor"].values
    rates = []
    for d, t in zip(dfs, years):
        rates.append(-np.log(d) / t * 100)
    return years, dfs, rates


# ---------------------------------------------------------------------------
# Vanilla interest rate swaps
# ---------------------------------------------------------------------------
def price_swap(df_curve, tenor, notional, start_year=0, npv=0, verbose=False):
    """Par rate, annuity, fixed rate and DV01 of a vanilla fixed for floating swap.

    The floating leg telescopes to D(start) - D(maturity), so no forward
    projection is needed on a single curve.
    """
    df_temp = df_curve
    if 0.0 not in df_temp["Years"].values:
        row_0 = {"Tenor": "0Y", "Years": 0.0, "Rate (%)": 0.0, "discount_factor": 1.0}
        df_temp = pd.concat([pd.DataFrame([row_0]), df_temp], ignore_index=True)

    maturity_year = start_year + tenor
    coupon_years = list(range(start_year + 1, maturity_year + 1))

    annuity = 0.0
    for cy in coupon_years:
        annuity += get_df(cy, df_temp)

    float_leg = get_df(start_year, df_temp) - get_df(maturity_year, df_temp)

    par_rate = float_leg / annuity
    fixed_rate = (float_leg - npv / notional) / annuity
    dv01 = annuity * 0.0001 * notional

    if verbose:
        print(f"Tenor      : {tenor}Y  (starting year {start_year})")
        print(f"Notional   : ${notional:,.0f}")
        print(f"Par rate   : {par_rate*100:.4f}%")
        print(f"Fixed rate : {fixed_rate*100:.4f}%")
        print(f"NPV        : ${npv:,.0f}")
        print(f"DV01       : ${dv01:,.0f}")

    return {"tenor": tenor, "par_rate": par_rate, "fixed_rate": fixed_rate,
            "annuity": annuity, "float_leg": float_leg, "dv01": dv01}


def swap_npv(df_curve, tenor, fixed_rate, notional):
    """NPV of a pay fixed swap under any curve, positive when rates have risen."""
    annuity = 0.0
    for cy in range(1, tenor + 1):
        annuity += get_df(cy, df_curve)
    float_leg = 1.0 - get_df(tenor, df_curve)
    return (float_leg - fixed_rate * annuity) * notional


def swap_krd_vector(df_curve, tenor, fixed_rate, notional, pillars=(1, 2, 3, 4, 5)):
    """Key rate durations of a pay fixed swap, one pillar bumped at a time.

    A swap of tenor T has no cash flow beyond T, so its sensitivity at longer
    pillars is exactly zero. That is what makes the hedge system triangular.
    """
    base = swap_npv(df_curve, tenor, fixed_rate, notional)
    krds = []
    for pillar in pillars:
        krds.append(swap_npv(bump_curve(df_curve, pillar), tenor, fixed_rate, notional) - base)
    return krds


# ---------------------------------------------------------------------------
# Coupon bonds with real settlement dates
# ---------------------------------------------------------------------------
def bond_pricer(coupon_annual_pct, face, df_curve,
                settlement_date, prev_coupon_date,
                first_coupon_date, maturity_date,
                convention="act/act",
                notional=1_000_000,
                verbose=False):
    """Clean price, dirty price, yield, duration and convexity of a coupon bond.

    Settling mid period is handled by w, the fraction of the current coupon
    period still to run, so cash flow k lands at (k + w) / 2 years. Accrued
    interest uses act/act between the surrounding coupon dates.
    """
    c = (coupon_annual_pct / 2) * face          # semi-annual coupon amount

    days_in_period = (first_coupon_date - settlement_date).days
    if convention == "30/360":
        days_full_period = 180
    else:
        days_full_period = (first_coupon_date - prev_coupon_date).days
    days_elapsed = days_full_period - days_in_period
    w = days_in_period / days_full_period

    # semi-annual coupon calendar out to maturity
    coupon_dates = []
    d = first_coupon_date
    while d <= maturity_date:
        coupon_dates.append(d)
        d = d + relativedelta(months=6)

    cashflows = []
    for k, cpn_date in enumerate(coupon_dates):
        years = (k + w) / 2
        cf = c + face if cpn_date == maturity_date else c
        disc=np.interp(years, df_curve["Years"].values,
                         df_curve["discount_factor"].values)
        cashflows.append((cpn_date, years, cf, disc, cf * disc))

    dirty = 0.0
    for cpn_date, years, cf, disc, pv in cashflows:
        dirty += pv
    accrued = c * (days_elapsed / days_full_period)
    clean = dirty - accrued
    pv_dollars = (dirty / face) * notional

    def ytm_error(y):
        """Present value at a trial yield, minus the dirty price."""
        i, pv = y / 2, 0.0
        for k, (cpn_date, years, cf, disc, _) in enumerate(cashflows):
            pv += cf / (1 + i) ** (k + w)
        return pv - dirty

    ytm = brentq(ytm_error, 0.0001, 0.99)

    i = ytm / 2
    num = 0.0
    for k, (cpn_date, years, cf, disc, _) in enumerate(cashflows):
        num += years * (cf / (1 + i) ** (k + w))
    mac_dur = num / dirty
    mod_dur = mac_dur / (1 + i)

    num = 0.0
    for k, (cpn_date, years, cf, disc, _) in enumerate(cashflows):
        num += years * (years + 0.5) * (cf / (1 + i) ** (k + w))
    convexity = num / (dirty * (1 + i) ** 2)

    dv01 = mod_dur * dirty * 0.0001 * (notional / face)

    if verbose:
        print("-" * 68)
        print(f"  Coupon {coupon_annual_pct*100:.3f}%  |  {len(cashflows)} periods  |  {convention}")
        print(f"  Settlement {settlement_date}  |  Maturity {maturity_date}")
        print(f"  w = {w:.4f}  ({days_in_period} days to next coupon / {days_full_period})")
        print("-" * 68)
        print(f"  Dirty      : {dirty:.4f}")
        print(f"  Accrued    : {accrued:.4f}")
        print(f"  Clean      : {clean:.4f}")
        print(f"  PV ($)     : ${pv_dollars:,.0f}")
        print(f"  YTM        : {ytm*100:.4f}%")
        print(f"  Mod dur    : {mod_dur:.4f} yrs")
        print(f"  Convexity  : {convexity:.4f}")
        print(f"  DV01       : ${dv01:,.2f}")
        print("-" * 68)

    return {"dirty": dirty, "clean": clean, "accrued": accrued, "pv": pv_dollars,
            "ytm": ytm, "duration": mod_dur, "convexity": convexity,
            "dv01": dv01, "cashflows": cashflows}


# ---------------------------------------------------------------------------
# Binomial short rate lattice
# ---------------------------------------------------------------------------
def build_tree(par_rates, vol):
    """Calibrate a Black-Derman-Toy style short rate tree to a par curve.

    Nodes within a step are spaced r_j = r_low * exp(2 j vol), which makes the
    rates lognormal. Each step then has a single unknown, r_low, solved so a
    par bond of that maturity values back to 100 on the tree built so far.
    That is what makes the tree arbitrage free.
    """
    n = len(par_rates)
    tree = [[par_rates[0]]]                       # year 0 node

    for t in range(1, n):
        coupon = par_rates[t]                     # par bond of maturity t+1

        def par_bond_error(r_low):
            """Pricing error of the par bond on a trial value of the low node."""
            nodes_t = [r_low * math.exp(2 * j * vol) for j in range(t + 1)]

            # roll back from maturity through the candidate step
            values = [100 + coupon * 100] * (t + 2)
            new_values = []
            for j in range(t + 1):
                v = 0.5 * values[j + 1] / (1 + nodes_t[j]) + 0.5 * values[j] / (1 + nodes_t[j])
                new_values.append(v)
            values = new_values

            # then back through the already calibrated steps
            for t2 in range(t - 1, -1, -1):
                new_values = []
                for j in range(t2 + 1):
                    v = 0.5 * (values[j + 1] + coupon * 100) / (1 + tree[t2][j]) + 0.5 * (values[j] + coupon * 100) / (1 + tree[t2][j])
                    new_values.append(v)
                values = new_values

            return values[0] - 100                # zero when calibrated

        r_low = brentq(par_bond_error, 1e-6, 1.0)
        tree.append([r_low * math.exp(2 * j * vol) for j in range(t + 1)])

    return tree


def bond_pricer_lattice(coupon, tenor, par_rates, vol=0.10,
                        call=False, call_price=100, first_call_year=2,
                        put=False, put_price=100, first_put_year=1,
                        oas=0.0):
    """Price a bond on the calibrated tree, optionally callable or putable.

    Rolling backwards, each node is the discounted average of its two
    successors plus the coupon. A call caps that value at the call price,
    which is the issuer choosing the cheaper of holding or retiring the bond.
    A put floors it, which is the investor's choice. An option adjusted
    spread, if given, is added to every node rate.
    """
    # a tenor year bond needs rate nodes for years 0 .. tenor-1
    tree = build_tree(par_rates[:tenor], vol)
    n = len(tree)

    values = [100] * (n + 1)                      # at maturity: face only

    for t in range(n - 1, -1, -1):
        new_values = []
        for j in range(t + 1):
            r = tree[t][j] + oas
            v = 0.5 * (values[j + 1] + coupon * 100) / (1 + r) + 0.5 * (values[j] + coupon * 100) / (1 + r)
            if call and t >= first_call_year:
                v = min(call_price, v)
            if put and t >= first_put_year:
                v = max(put_price, v)
            new_values.append(v)
        values = new_values

    return values[0]


def solve_oas(market_price, coupon, tenor, par_rates, vol, **kwargs):
    """Constant spread on every node that makes the model price the market price."""
    def oas_error(oas):
        return bond_pricer_lattice(coupon, tenor, par_rates, vol, oas=oas, **kwargs) - market_price
    return brentq(oas_error, -0.02, 0.02)


def issuer_par_curve(sofr_curve, spread, n_years=11):
    """SOFR par curve shifted by a flat credit spread, giving an issuer curve.

    Credit is represented purely as a parallel shift of the discounting curve.
    There is no hazard rate, default probability or recovery here, which is the
    deepest simplification in the study and is discussed in the limitations.
    """
    rates = []
    for y in range(n_years):
        sofr_par = np.interp(y, sofr_curve["Years"].values, sofr_curve["Rate (%)"].values) / 100
        rates.append(sofr_par + spread)
    return rates
