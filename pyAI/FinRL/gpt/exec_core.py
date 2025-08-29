# exec_core.py
# Минимальный симулятор портфеля под дискретные действия {-1,0,1} c рисками.

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
import math

# ---- Конфиг по рискам/издержкам ----
@dataclass
class ExecConfig:
    start_cash: float = 10_000.0
    fee_bps: float = 5.0          # комиссия 0.05% в каждую сторону
    slippage_bps: float = 5.0     # слиппедж 0.05%
    stop_loss_pct: float = 0.05   # фиксированный стоп 5% от цены входа
    risk_per_step: float = 0.01   # суммарный бюджет на сделки в шаге = 1% equity

@dataclass
class Position:
    qty: float = 0.0
    entry: float = 0.0  # средняя цена входа

@dataclass
class PortfolioSim:
    cfg: ExecConfig = field(default_factory=ExecConfig)
    cash: float = field(init=False)
    positions: Dict[str, Position] = field(default_factory=dict)
    last_equity: float = field(init=False)

    def __post_init__(self):
        self.cash = self.cfg.start_cash
        self.last_equity = self.cfg.start_cash

    # ---------- helpers ----------
    @staticmethod
    # Применение слиппеджа к цене
    def _price_with_slippage(price: float, side: int, slippage_bps: float) -> float:
        # side: +1 buy, -1 sell
        slip = slippage_bps / 10_000.0
        return price * (1.0 + slip * (1 if side > 0 else -1))

    @staticmethod
    # Применение комиссии к денежному потоку
    def _apply_fee(amount: float, fee_bps: float) -> float:
        fee = abs(amount) * (fee_bps / 10_000.0)
        return amount - fee

    # Переоценка позиций по текущим ценам
    def _mark_to_market(self, prices: Dict[str, float]) -> float:
        equity = self.cash
        for t, pos in self.positions.items():
            px = prices.get(t, 0.0)
            if px > 0 and pos.qty != 0.0:
                equity += pos.qty * px
        return equity

    # ---------- публичные методы ----------
    def sync_tokens(self, tokens: List[str]) -> None:
        """Убедиться, что под каждый токен есть запись позиции (qty=0 по умолчанию)."""
        for t in tokens:
            self.positions.setdefault(t, Position())

    def step(
        self,
        tokens: List[str],
        actions: List[int],
        prices: Dict[str, float],
    ) -> Tuple[float, Dict]:
        """
        Выполнить один шаг.
        - tokens: список токенов в батче (должен соответствовать actions порядком)
        - actions: значения {-1,0,1} для каждого токена (sell/hold/buy)
        - prices: map token->last_close
        Возвращает: (reward, info)
        """
        assert len(tokens) == len(actions), "len(tokens) != len(actions)"
        self.sync_tokens(tokens)

        prev_equity = self._mark_to_market(prices)

        # Сколько токенов реально торгуем на шаге
        trade_idxs = [i for i, a in enumerate(actions) if a != 0]
        n_trades = max(1, len(trade_idxs))  # чтобы деление не на 0

        # Общий риск-бюджет на шаг
        budget_step = prev_equity * self.cfg.risk_per_step
        budget_per_trade = budget_step / n_trades

        logs = []

        # 1) исполним торговые действия
        for i in trade_idxs:
            t = tokens[i]
            a = actions[i]  # -1/ +1
            px = prices.get(t, 0.0)
            if px <= 0:
                logs.append((t, "skip(no_price)"))
                continue

            pos = self.positions[t]
            side = 1 if a > 0 else -1

            # капитал, который готовы задействовать в этой сделке
            notional = min(self.cash, budget_per_trade)
            if notional <= 0:
                logs.append((t, "skip(no_cash)"))
                continue

            trade_px = self._price_with_slippage(px, side, self.cfg.slippage_bps)
            qty = (notional / trade_px) * side

            # Денежный поток: платим/получаем и уплачиваем комиссию
            flow = -qty * trade_px  # buy => отрицательный (денежка уходит), sell => положительный
            flow = self._apply_fee(flow, self.cfg.fee_bps)
            self.cash += flow

            # Обновляем позицию (средняя цена при наращивании)
            new_qty = pos.qty + qty
            if pos.qty == 0.0 or (pos.qty > 0 and qty > 0) or (pos.qty < 0 and qty < 0):
                # наращиваем в ту же сторону -> новая средняя
                if new_qty != 0:
                    pos.entry = (pos.entry * abs(pos.qty) + trade_px * abs(qty)) / abs(new_qty)
            else:
                # уменьшаем/переворот — pos.entry перезапишется при смене знака
                if new_qty == 0:
                    pos.entry = 0.0
                elif (pos.qty > 0 and qty < 0) or (pos.qty < 0 and qty > 0):
                    # переворот
                    pos.entry = trade_px
            pos.qty = new_qty

            logs.append((t, f"trade {a:+d} @ {trade_px:.6f} qty={qty:.6f} cash={self.cash:.2f}"))

        # 2) применим стоп-лосс к открытым позициям (фиксированный от entry)
        for t, pos in self.positions.items():
            if pos.qty == 0.0:
                continue
            px = prices.get(t, 0.0)
            if px <= 0:
                continue

            if pos.qty > 0:
                # long: стоп если цена <= entry*(1 - stop)
                stop_level = pos.entry * (1.0 - self.cfg.stop_loss_pct)
                if px <= stop_level:
                    # закрываем по рынку (со слиппеджем в "sell")
                    trade_px = self._price_with_slippage(px, side=-1, slippage_bps=self.cfg.slippage_bps)
                    flow = -(-pos.qty) * trade_px  # продаем pos.qty
                    flow = self._apply_fee(flow, self.cfg.fee_bps)
                    self.cash += flow
                    logs.append((t, f"STOP LONG @{trade_px:.6f} qty={-pos.qty:.6f}"))
                    pos.qty = 0.0
                    pos.entry = 0.0

            elif pos.qty < 0:
                # short: стоп если цена >= entry*(1 + stop)
                stop_level = pos.entry * (1.0 + self.cfg.stop_loss_pct)
                if px >= stop_level:
                    trade_px = self._price_with_slippage(px, side=+1, slippage_bps=self.cfg.slippage_bps)
                    flow = -(+(-pos.qty)) * trade_px  # выкупаем шорт
                    flow = self._apply_fee(flow, self.cfg.fee_bps)
                    self.cash += flow
                    logs.append((t, f"STOP SHORT @{trade_px:.6f} qty={+(-pos.qty):.6f}"))
                    pos.qty = 0.0
                    pos.entry = 0.0

        # 3) считаем equity и reward
        equity = self._mark_to_market(prices)
        reward = equity - prev_equity  # dPnL за шаг

        info = {
            "prev_equity": round(prev_equity, 6),
            "equity": round(equity, 6),
            "cash": round(self.cash, 6),
            "positions": {t: {"qty": p.qty, "entry": p.entry} for t, p in self.positions.items() if p.qty != 0.0},
            "logs": logs,
        }
        self.last_equity = equity
        return reward, info


# --------- удобная утилита для извлечения цен из наших буферов (последняя close) ---------
def last_close_prices(buffers, tokens: List[str]) -> Dict[str, float]:
    out = {}
    for t in tokens:
        buf = buffers.tokens.get(t)
        px = 0.0
        if buf and buf.klines:
            last = buf.klines[-1]
            px = float(last.get("close", 0.0) or 0.0)
        out[t] = px
    return out