# env_multi_token.py
import time
from typing import List, Dict, Optional, Tuple

import numpy as np
import gymnasium as gym
from gymnasium import spaces

from stream_buffer import Buffers
from exec_core import PortfolioSim, last_close_prices
from features import build_batch_state, FEATURE_DIM
from config import STEP_TIMEOUT_SEC

class MultiTokenPickEnv(gym.Env):
    """
    Динамическое top-K окружение.
    - На каждом шаге выбираем до K токенов в 'слоты' по score().
    - Действия привязаны к слотам текущего шага: 0=no-op, 1..K=SELL, K+1..2K=BUY.
    - Ожидание новой свечи происходит по *текущим слотам*, чтобы reward был за следующий тик.
    - В info возвращаем 'slots' (список tickers в порядке слотов), их score, и свопы.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        buffers: Buffers,
        max_tokens: int,
        sim: Optional[PortfolioSim] = None,
        trade_penalty: float = 0.0,
        universe: Optional[List[str]] = None,   # если None — берем все из buffers.tokens
        step_timeout_sec: float = STEP_TIMEOUT_SEC,
        min_hold_steps: int = 3,                # гистерезис: минимум N шагов держим слот
        max_swaps_per_step: int = 1,            # ограничим "дерганье" слотов
        tg_recent_sec: float = 15 * 60,         # токен с недавним tg получает бонус
    ):
        super().__init__()
        self.buffers = buffers
        self.sim = sim or PortfolioSim()
        self.K = int(max_tokens)
        self.trade_penalty = float(trade_penalty)
        self.universe = list(universe) if universe else None
        self.step_timeout_sec = float(step_timeout_sec)

        # стабилизация слотов
        self.min_hold_steps = int(min_hold_steps)
        self.max_swaps_per_step = int(max_swaps_per_step)
        self.tg_recent_sec = float(tg_recent_sec)

        # текущее состояние слотов
        self.slots: List[Optional[str]] = [None] * self.K
        self.slot_age: List[int] = [0] * self.K
        self._last_ts: Dict[str, float] = {}   # last seen kline ts per token
        self._last_obs: Optional[np.ndarray] = None

        # gym spaces
        # obs — это K * FEATURE_DIM, просто конкатенация по слотам
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(self.K * FEATURE_DIM,), dtype=np.float32
        )
        # actions: 0=noop, 1..K=SELL, K+1..2K=BUY
        self.action_space = spaces.Discrete(1 + 2 * self.K)

    # --------- ранжирование/слоты ---------
    def _candidate_tokens(self) -> List[str]:
        if self.universe is not None:
            return [t for t in self.universe if t in self.buffers.tokens]
        return list(self.buffers.tokens.keys())

    def _score_token(self, t: str, now: float) -> float:
        """
        Простая эвристика: tg-буст + abs(oiChange4h) + abs(coinChange24h) + proxy волатильности.
        Ничего «сверхумного», главное — чтобы «горячие» монеты набирали больше очков.
        """
        tb = self.buffers.tokens.get(t)
        if not tb:
            return -1e9

        s = 0.0

        # TG бонус: если недавно была tg-нота — +1.0
        ltg = getattr(tb, "tg", None) or getattr(tb, "last_tg", None)
        if ltg and isinstance(ltg, dict):
            ts = float(ltg.get("ts", 0.0) or 0.0)
            if now - ts <= self.tg_recent_sec:
                s += 1.0
            s += 0.5 * abs(float(ltg.get("oiChange4h", 0.0) or 0.0))
            s += 0.2 * abs(float(ltg.get("coinChange24h", 0.0) or 0.0))

        # Волатильность по последним ~10 свечам (если есть)
        closes = []
        if getattr(tb, "klines", None):
            for k in list(tb.klines)[-10:]:
                c = float(k.get("close", 0.0) or 0.0)
                if c > 0:
                    closes.append(c)
        if len(closes) >= 3:
            arr = np.array(closes, dtype=np.float64)
            vol = float(np.std(arr) / (np.mean(arr) + 1e-9))
            s += 2.0 * vol  # небольшой вес

        # Если нет цены — сильно понижаем
        px = 0.0
        if getattr(tb, "klines", None):
            last = tb.klines[-1]
            px = float(last.get("close", 0.0) or 0.0)
        if px <= 0:
            s -= 5.0

        return s

    def _refresh_slots(self) -> Dict[str, float]:
        """
        Пересчитать приоритеты и обновить слоты с гистерезисом:
        - минимум min_hold_steps — держим старый слот,
        - максимум max_swaps_per_step замен за раз,
        - требуем, чтобы кандидат имел score заметно выше текущего (margin).
        Возвращаем словарь score по выбранным токенам.
        """
        now = time.time()
        cand = self._candidate_tokens()
        scored = [(t, self._score_token(t, now)) for t in cand]
        scored.sort(key=lambda x: x[1], reverse=True)

        # текущие токены в слотах и их score
        current = set([t for t in self.slots if t])
        score_map = {t: s for t, s in scored}

        # сперва старим слоты (возраст +1)
        self.slot_age = [age + 1 if tok else 0 for tok, age in zip(self.slots, self.slot_age)]

        swaps = 0
        margin = 0.2  # требуем небольшой запас по score, чтобы не дёргать лишний раз

        # пройдёмся по позициям слотов
        for i in range(self.K):
            tok = self.slots[i]

            # пустой слот — берём следующий лучший, которого ещё нет в слотах
            if tok is None:
                for t, s in scored:
                    if t not in current:
                        self.slots[i] = t
                        current.add(t)
                        self.slot_age[i] = 1
                        swaps += 1
                        break
                continue

            # если слот слишком молод — держим
            if self.slot_age[i] < self.min_hold_steps:
                continue

            # проверим, нет ли кандидата, который заметно лучше
            best_t, best_s = None, None
            for t, s in scored:
                if t in current:
                    continue
                best_t, best_s = t, s
                break

            if best_t is None:
                continue

            cur_s = score_map.get(tok, -1e9)
            if best_s is not None and best_s > cur_s + margin and swaps < self.max_swaps_per_step:
                # меняем слот
                current.remove(tok)
                current.add(best_t)
                self.slots[i] = best_t
                self.slot_age[i] = 1
                swaps += 1

        # соберём итоговый score только для выбранных слотов
        out_scores = {t: score_map.get(t, 0.0) for t in self.slots if t}
        return out_scores

    # ---------- obs helpers ----------
    def _obs(self) -> np.ndarray:
        # строим батч в порядке текущих слотов
        use = [t for t in self.slots if t]  # без None
        if not use:
            # пусто — вернём нули
            return np.zeros((self.K * FEATURE_DIM,), dtype=np.float32)

        batch, used = build_batch_state(self.buffers, use)
        # паддинг до K
        if batch.shape[0] < self.K:
            pad = np.zeros((self.K - batch.shape[0], FEATURE_DIM), dtype=np.float32)
            batch = np.vstack([batch, pad])
        return batch.astype(np.float32).reshape(-1)
    
    def _exec_snapshot(self) -> dict:
        """Снимок equity/cash/positions даже без шага симулятора (для таймаутов)."""
        # берём цены по всем токенам, по которым есть открытые позиции
        pos_tokens = list(getattr(self.sim, "positions", {}).keys())
        prices = last_close_prices(self.buffers, pos_tokens) if pos_tokens else {}

        cash = float(getattr(self.sim, "cash", self.sim.cfg.start_cash))
        equity = cash
        positions = getattr(self.sim, "positions", {}) or {}
        # dataclass Position -> берём qty/entry
        for t, p in positions.items():
            qty = float(getattr(p, "qty", 0.0))
            px  = float(prices.get(t, getattr(p, "entry", 0.0)) or 0.0)
            equity += qty * px

        # приведём позиции к простому dict, чтобы не печатать dataclass
        pos_out = {t: {"qty": float(getattr(p, "qty", 0.0)),
                    "entry": float(getattr(p, "entry", 0.0))}
                for t, p in positions.items()}
        return {"equity": equity, "cash": cash, "positions": pos_out, "logs": [], "trades": 0}
    
    def _decode_action_vector(self, a: int) -> list[int]:
        """
        Преобразуем single Discrete action -> вектор длины K, где
        0=HOLD, 1=SELL, 2=BUY.
        """
        out = [0] * self.K
        x = int(a)
        for i in range(self.K):
            out[i] = x % 3
            x //= 3
        return out

    # ---------- gym API ----------
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)

        # Полная перезагрузка симулятора (если у него есть reset)
        if hasattr(self.sim, "reset"):
            self.sim.reset()

        # Инициализация слотов
        self._refresh_slots()

        # дождёмся хотя бы одной свечи по *какому-то* из слотов
        active = [t for t in self.slots if t]
        if active:
            self.buffers.wait_for_new_kline(tokens=active, timeout_sec=self.step_timeout_sec)
            for t in active:
                ts = self.buffers.last_kline_ts(t)
                if ts is not None:
                    self._last_ts[t] = ts

        self._last_obs = self._obs()
        info = {"slots": list(self.slots)}
        return self._last_obs, info

    def step(self, action: int):
        # 1) ждём новую свечу по *текущим* слотам
        active = [t for t in self.slots if t]
        since = {t: self._last_ts.get(t, self.buffers.last_kline_ts(t) or -1.0) for t in active}
        got = {}
        if active:
            got = self.buffers.wait_for_new_kline(
                tokens=active,
                since_ts=since,
                timeout_sec=self.step_timeout_sec,
                poll_interval_ms=100,
                min_new=1,
            )
        if not got:
            obs = self._last_obs if self._last_obs is not None else self._obs()
            snap = self._exec_snapshot()
            info = {
                "timeout": True,
                "slots": list(self.slots),
                "slot_scores": {},   # можно заполнить, если хочешь
                "tokens": [],
                "price_map": {},
                "trades": 0,
                "logs": [],
                "equity": snap["equity"],
            }
            return obs, 0.0, False, False, info

        for t, ts in got.items():
            self._last_ts[t] = ts

        # 2) маппим действие
        a = int(action)
        side = 0
        slot_idx = -1
        if a == 0:
            side = 0
        elif 1 <= a <= self.K:
            side = -1
            slot_idx = a - 1
        elif self.K + 1 <= a <= 2 * self.K:
            side = +1
            slot_idx = a - (self.K + 1)
        else:
            side = 0

        # 3) собираем цены, готовим списки для симулятора
        prices = last_close_prices(self.buffers, active)  # только по активным
        tokens = []
        actions = []
        # наполняем действиями: по всем активным слотам HOLD, а если выбран slot_idx — side там
        for i, t in enumerate(active):
            tokens.append(t)
            actions.append(0)
        if 0 <= slot_idx < len(active):
            # проверим, есть ли цена
            if prices.get(active[slot_idx], 0.0) > 0:
                actions[slot_idx] = side

        # 4) шаг симулятора
        _, exec_info = self.sim.step(tokens=tokens, actions=actions, prices=prices)

        # 5) reward: dPnL за движение цены с прошлого шага (сим его хранит) минус лёгкий штраф
        trades = int(exec_info.get("trades", 0))
        # цена за шаг — уже внутри симулятора; reward отдаём постфактум:
        step_pnl = float(exec_info["equity"] - exec_info["prev_equity"])
        reward = step_pnl / self.sim.cfg.start_cash - self.trade_penalty * trades
        # --- inventory cost (мягкий штраф за «висеть» в позиции)
        INV_COST_BPS = 0.5  # 0.5 б.п. за шаг
        gross = 0.0
        for t, p in self.sim.positions.items():
            qty = float(getattr(p, "qty", 0.0))
            px  = float(self.buffers.tokens.get(t).klines[-1].get("close", 0.0)) if (self.buffers.tokens.get(t) and self.buffers.tokens[t].klines) else 0.0
            gross += abs(qty) * max(px, 0.0)

        inv_penalty = (INV_COST_BPS / 10_000.0) * gross / self.sim.cfg.start_cash
        reward -= inv_penalty

        # 6) обновляем слоты для СЛЕДУЮЩЕГО шага (динамика!)
        scores = self._refresh_slots()

        # 7) наблюдение и возврат
        obs = self._obs()
        self._last_obs = obs
        info = {
            "slots": list(self.slots),
            "slot_scores": scores,
            "tokens": list(tokens),
            "price_map": prices,
            "trades": trades,
            "logs": exec_info.get("logs", []),
            "equity": exec_info.get("equity", None),
        }
        return obs, float(reward), False, False, info
