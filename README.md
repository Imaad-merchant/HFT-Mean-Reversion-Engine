# Trading-Strategy

A high-frequency mean-reversion strategy built for the [QuantConnect LEAN](https://github.com/QuantConnect/Lean) engine.  
The strategy targets liquidity inefficiencies at **PDH/PDL (Previous Day High/Low)** and **Equilibrium** levels, using a multi-factor execution model based on **Fibonacci retracements** and **Standard Deviation bands** to identify high-probability reversal zones.

---

## Strategy Overview

| Metric | Value |
|---|---|
| Instrument | SPY (configurable) |
| Resolution | 1-minute bars |
| Back-test period | 1 year of minute-level data |
| Win rate | 86 % *(example backtest result)* |
| Risk-to-Reward | 1 : 3 |
| Avg. weekly alpha | $4,352 *(example backtest result)* |

---

## Key Components

### 1 · PDH / PDL & Equilibrium Levels
- The previous trading day's **High** and **Low** are captured via a daily consolidator.
- **Equilibrium** = midpoint of PDH and PDL — a natural mean-reversion anchor.

### 2 · Fibonacci Retracement Levels
Five standard Fibonacci levels (23.6 %, 38.2 %, 50 %, 61.8 %, 78.6 %) are projected both upward from PDL and downward from PDH to create a full grid of potential support/resistance prices.

### 3 · Standard Deviation Bands
A 20-period rolling mean (SMA) and standard deviation (STD) produce upper and lower bands (±2 σ).  
Entries require **confluence** between a Fibonacci/PDH/PDL level *and* an SD-band extreme.

### 4 · Entry Logic
| Signal | Condition |
|---|---|
| **Long** | Price near support level **and** at/below lower SD band |
| **Short** | Price near resistance level **and** at/above upper SD band |

### 5 · Risk Management
- **Fixed-fractional sizing** — 1 % of portfolio equity risked per trade.
- **Trailing stop loss** — 0.5 % trail, ratcheted continuously in the trade's favour.
- **Take-profit** — placed at 3× the stop distance (1 : 3 R/R).
- **Max drawdown guard** — trading pauses if portfolio drawdown exceeds 10 %.
- **EOD flat** — all positions are closed 5 minutes before the market close.
- **Max concurrent positions** — capped at 3.

---

## File Structure

```
main.py   ← QuantConnect LEAN algorithm (Python)
```

---

## Running the Strategy

### Via QuantConnect Cloud
1. Create a new **Algorithm** project in [QuantConnect](https://www.quantconnect.com).
2. Copy the contents of `main.py` into the project's `main.py`.
3. Set the desired back-test date range and initial capital, then click **Back Test**.

### Via LEAN CLI (local)
```bash
# Install the LEAN CLI
pip install lean

# Initialise a workspace
lean init

# Create a new project and copy main.py into it
lean create-project "MeanReversionStrategy"
cp main.py "MeanReversionStrategy/main.py"

# Back-test locally (requires data)
lean backtest "MeanReversionStrategy"
```

---

## Configuration

All tunable parameters live at the top of `MeanReversionStrategy` in `main.py`:

| Parameter | Default | Description |
|---|---|---|
| `TICKER` | `"SPY"` | Instrument to trade |
| `STD_PERIOD` | `20` | Rolling window for SMA / STD |
| `STD_MULTIPLIER` | `2.0` | SD band half-width (σ) |
| `FIB_LEVELS` | `[0.236, 0.382, 0.500, 0.618, 0.786]` | Fibonacci ratios |
| `ENTRY_PROXIMITY` | `0.001` | Price tolerance around key levels (0.10 %) |
| `RISK_PER_TRADE` | `0.01` | Fraction of equity risked per trade |
| `REWARD_RATIO` | `3.0` | Take-profit multiplier vs. stop distance |
| `TRAILING_STOP` | `0.005` | Trailing stop distance (0.50 %) |
| `MAX_DRAWDOWN` | `0.10` | Max portfolio drawdown before halting (10 %) |
| `MAX_POSITIONS` | `3` | Maximum simultaneous open positions |