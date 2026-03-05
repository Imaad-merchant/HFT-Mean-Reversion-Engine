# region imports
from AlgorithmImports import *
# endregion

class MeanReversionStrategy(QCAlgorithm):
    """
    High-frequency mean-reversion strategy targeting liquidity inefficiencies
    at PDH/PDL (Previous Day High/Low) and Equilibrium levels.

    Execution model uses Fibonacci retracements and Standard Deviation bands
    to identify high-probability reversal zones. Automated risk parameters
    include a trailing stop loss to mitigate drawdown and preserve capital.
    """

    # ── Configurable parameters ────────────────────────────────────────────
    TICKER          = "SPY"          # Primary instrument
    RESOLUTION      = Resolution.Minute

    # Fibonacci retracement levels (measured from PDL toward PDH)
    FIB_LEVELS      = [0.236, 0.382, 0.500, 0.618, 0.786]

    # Standard-Deviation band
    STD_PERIOD      = 20             # Rolling window length for mean / std
    STD_MULTIPLIER  = 2.0            # σ band half-width

    # Entry / risk parameters
    ENTRY_PROXIMITY = 0.001          # 0.1 % price tolerance around key levels
    RISK_PER_TRADE  = 0.01           # 1 % of portfolio equity per trade
    REWARD_RATIO    = 3.0            # 1 : 3 risk-to-reward
    TRAILING_STOP   = 0.005          # 0.50 % trailing stop distance
    MAX_DRAWDOWN    = 0.10           # Pause trading if drawdown exceeds 10 %
    MAX_POSITIONS   = 3              # Maximum simultaneous open positions

    # ── Internal state ─────────────────────────────────────────────────────
    _pdh: float = None               # Previous-day high
    _pdl: float = None               # Previous-day low
    _equilibrium: float = None       # Mid-point of PDH / PDL
    _fib_levels: list = []           # Computed Fibonacci price levels
    _daily_bar = None                # Consolidator output (previous daily bar)
    _peak_equity: float = None       # High-water mark for drawdown calculation
    _open_positions: dict = {}       # ticket → (stop_price, direction)

    # ──────────────────────────────────────────────────────────────────────
    def Initialize(self):
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 1, 1)
        self.SetCash(100_000)

        # Subscribe to minute-bar data
        self._equity = self.AddEquity(self.TICKER, self.RESOLUTION)
        self._equity.SetDataNormalizationMode(DataNormalizationMode.Raw)
        self._symbol = self._equity.Symbol

        # ── Indicators ────────────────────────────────────────────────────
        # Simple moving average & std-dev over STD_PERIOD bars
        self._sma = self.SMA(self._symbol, self.STD_PERIOD, self.RESOLUTION)
        self._std = self.STD(self._symbol, self.STD_PERIOD, self.RESOLUTION)

        # Daily consolidator to capture yesterday's high / low
        daily_consolidator = TradeBarConsolidator(timedelta(days=1))
        daily_consolidator.DataConsolidated += self._on_daily_bar
        self.SubscriptionManager.AddConsolidator(self._symbol, daily_consolidator)

        # ── Scheduled events ──────────────────────────────────────────────
        # Recalculate Fibonacci / equilibrium levels at the start of each day
        self.Schedule.On(
            self.DateRules.EveryDay(self._symbol),
            self.TimeRules.AfterMarketOpen(self._symbol, 1),
            self._recalculate_levels,
        )
        # Flatten all positions before the market closes
        self.Schedule.On(
            self.DateRules.EveryDay(self._symbol),
            self.TimeRules.BeforeMarketClose(self._symbol, 5),
            self._close_all_positions,
        )

        self._peak_equity = self.Portfolio.TotalPortfolioValue
        self.Log("MeanReversionStrategy initialised.")

    # ──────────────────────────────────────────────────────────────────────
    # Daily consolidator callback – capture the completed day bar
    # ──────────────────────────────────────────────────────────────────────
    def _on_daily_bar(self, sender, bar: TradeBar):
        self._daily_bar = bar

    # ──────────────────────────────────────────────────────────────────────
    # Recalculate PDH / PDL, equilibrium, and Fibonacci levels
    # ──────────────────────────────────────────────────────────────────────
    def _recalculate_levels(self):
        if self._daily_bar is None:
            return

        self._pdh = float(self._daily_bar.High)
        self._pdl = float(self._daily_bar.Low)
        self._equilibrium = (self._pdh + self._pdl) / 2.0

        rng = self._pdh - self._pdl
        if rng <= 0:
            self._fib_levels = []
            return

        # Retracement levels measured from PDH downward (bearish) and
        # from PDL upward (bullish) – we store absolute price levels
        self._fib_levels = [
            self._pdh - rng * lvl for lvl in self.FIB_LEVELS
        ] + [
            self._pdl + rng * lvl for lvl in self.FIB_LEVELS
        ]
        self._fib_levels = sorted(set(self._fib_levels))

        self.Log(
            f"Levels updated | PDH={self._pdh:.2f}  PDL={self._pdl:.2f}  "
            f"EQ={self._equilibrium:.2f}  Fibs={[f'{p:.2f}' for p in self._fib_levels]}"
        )

    # ──────────────────────────────────────────────────────────────────────
    # Main data event handler
    # ──────────────────────────────────────────────────────────────────────
    def OnData(self, data: Slice):
        if not data.ContainsKey(self._symbol):
            return
        if not (self._sma.IsReady and self._std.IsReady):
            return
        if self._pdh is None or self._pdl is None:
            return

        bar   = data[self._symbol]
        price = float(bar.Close)

        # ── Drawdown guard ────────────────────────────────────────────────
        equity = self.Portfolio.TotalPortfolioValue
        self._peak_equity = max(self._peak_equity, equity)
        drawdown = (self._peak_equity - equity) / self._peak_equity
        if drawdown >= self.MAX_DRAWDOWN:
            self._close_all_positions()
            return

        # ── Update trailing stops for existing positions ──────────────────
        self._update_trailing_stops(price)

        # ── Entry logic ───────────────────────────────────────────────────
        if len(self._open_positions) >= self.MAX_POSITIONS:
            return

        sma_val = float(self._sma.Current.Value)
        std_val = float(self._std.Current.Value)
        upper_band = sma_val + self.STD_MULTIPLIER * std_val
        lower_band = sma_val - self.STD_MULTIPLIER * std_val

        reversal_signal = self._detect_reversal_zone(price, upper_band, lower_band)
        if reversal_signal == 0:
            return

        self._enter_trade(price, reversal_signal)

    # ──────────────────────────────────────────────────────────────────────
    # Determine whether the current price is inside a high-probability
    # reversal zone.  Returns +1 (long), -1 (short), or 0 (no signal).
    # ──────────────────────────────────────────────────────────────────────
    def _detect_reversal_zone(self, price: float, upper_band: float, lower_band: float) -> int:
        tol = price * self.ENTRY_PROXIMITY

        # Collect all key levels
        key_levels = [self._pdh, self._pdl, self._equilibrium] + self._fib_levels

        near_resistance = any(abs(price - lvl) <= tol for lvl in key_levels)
        near_support    = any(abs(price - lvl) <= tol for lvl in key_levels)

        # Standard-deviation band confluence
        at_upper_band = price >= upper_band - tol
        at_lower_band = price <= lower_band + tol

        # Short signal: price near resistance + at or above upper SD band
        if near_resistance and at_upper_band:
            return -1

        # Long signal: price near support + at or below lower SD band
        if near_support and at_lower_band:
            return 1

        return 0

    # ──────────────────────────────────────────────────────────────────────
    # Size and submit an order; record stop-loss details
    # ──────────────────────────────────────────────────────────────────────
    def _enter_trade(self, price: float, direction: int):
        equity       = self.Portfolio.TotalPortfolioValue
        risk_dollars = equity * self.RISK_PER_TRADE

        stop_dist  = price * self.TRAILING_STOP
        take_profit = price + direction * stop_dist * self.REWARD_RATIO

        # Position size derived from fixed-fractional risk
        shares = int(risk_dollars / stop_dist) if stop_dist > 0 else 0
        if shares <= 0:
            return

        if direction == 1:
            ticket = self.MarketOrder(self._symbol, shares)
            stop_price = price - stop_dist
        else:
            ticket = self.MarketOrder(self._symbol, -shares)
            stop_price = price + stop_dist

        order_id = ticket.OrderId
        self._open_positions[order_id] = {
            "direction":  direction,
            "stop_price": stop_price,
            "take_profit": take_profit,
            "peak_price": price,
            "shares": shares,
        }

        self.Log(
            f"ENTRY {'LONG' if direction == 1 else 'SHORT'}  "
            f"price={price:.2f}  shares={shares}  "
            f"stop={stop_price:.2f}  tp={take_profit:.2f}"
        )

    # ──────────────────────────────────────────────────────────────────────
    # Update trailing stops and check take-profit / stop-out
    # ──────────────────────────────────────────────────────────────────────
    def _update_trailing_stops(self, price: float):
        filled_tickets  = [
            oid for oid, info in self._open_positions.items()
            if (order := self.Transactions.GetOrderById(oid)) is not None
               and order.Status == OrderStatus.Filled
        ]

        to_close = []
        for oid in filled_tickets:
            info      = self._open_positions[oid]
            direction = info["direction"]
            stop_dist = price * self.TRAILING_STOP

            # Ratchet trailing stop in favour of the trade
            if direction == 1:
                new_stop = price - stop_dist
                if new_stop > info["stop_price"]:
                    info["stop_price"] = new_stop
                hit_stop   = price <= info["stop_price"]
                hit_target = price >= info["take_profit"]
            else:
                new_stop = price + stop_dist
                if new_stop < info["stop_price"]:
                    info["stop_price"] = new_stop
                hit_stop   = price >= info["stop_price"]
                hit_target = price <= info["take_profit"]

            if hit_stop or hit_target:
                reason = "TP" if hit_target else "SL"
                self.Log(f"EXIT ({reason}) oid={oid}  price={price:.2f}")
                to_close.append(oid)

        for oid in to_close:
            info = self._open_positions.pop(oid)
            # Close exactly the shares opened by this order (handles multiple positions)
            exit_qty = info["shares"] * (-info["direction"])
            self.MarketOrder(self._symbol, exit_qty)

    # ──────────────────────────────────────────────────────────────────────
    # Flatten all open positions (EOD / drawdown guard)
    # ──────────────────────────────────────────────────────────────────────
    def _close_all_positions(self):
        if self.Portfolio[self._symbol].Invested:
            self.Liquidate(self._symbol)
            self.Log("All positions closed.")
        self._open_positions.clear()

    # ──────────────────────────────────────────────────────────────────────
    # Optional: log summary statistics at the end of each day
    # ──────────────────────────────────────────────────────────────────────
    def OnEndOfDay(self, symbol):
        if symbol != self._symbol:
            return
        equity   = self.Portfolio.TotalPortfolioValue
        drawdown = (self._peak_equity - equity) / self._peak_equity * 100
        self.Log(
            f"EOD | equity={equity:,.2f}  peak={self._peak_equity:,.2f}  "
            f"drawdown={drawdown:.2f}%  open_positions={len(self._open_positions)}"
        )
