# env_single_token.py
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from stream_buffer import Buffers
from features import build_batch_state, FEATURE_DIM
from exec_core import PortfolioSim, last_close_prices
from config import STEP_TIMEOUT_SEC

# Пока без штрафа за частые сделки: включим потом, когда агент оживет
TRADE_PENALTY = 0.0

class SingleTokenEnv(gym.Env):
    """
    Окружение для одного токена (действие влияет на текущий reward):
    - На шаге t: выполняем действие по текущей цене.
    - Ждем следующий тик.
    - Начисляем reward = (MTM_{t+1} - MTM_{после_сделки_на_t}) / start_cash - penalty*trades_t
    """
    metadata = {"render_modes": []}

    def __init__(
        self,
        buffers: Buffers,
        token: str,
        step_timeout_sec: float = STEP_TIMEOUT_SEC,
        sim: PortfolioSim | None = None,
    ):
        super().__init__()
        self.buffers = buffers
        self.token = token
        self.sim = sim or PortfolioSim()
        self.step_timeout_sec = step_timeout_sec

        self._last_ts: dict[str, float] = {}     # {token: last_seen_kline_ts}
        self._last_obs: np.ndarray | None = None

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(FEATURE_DIM,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0=SELL(-1), 1=HOLD(0), 2=BUY(+1)


    # ------- helpers -------
    def _obs(self) -> np.ndarray:
        X, used = build_batch_state(self.buffers, [self.token])
        if len(used) == 0:
            return np.zeros((FEATURE_DIM,), dtype=np.float32)
        return X[0]

    def _exec_snapshot(self) -> dict:
        """Безопасный снепшот, даже если симулятор ещё «пустой»."""
        prices = last_close_prices(self.buffers, [self.token])
        cash = float(getattr(self.sim, "cash", getattr(self.sim, "cfg").start_cash))
        positions = getattr(self.sim, "positions", {}) or {}
        pos_val = 0.0
        for t, p in positions.items():
            qty = float(getattr(p, "qty", 0.0))
            px = float(prices.get(t, getattr(p, "entry", 0.0)))
            pos_val += qty * px
        equity = float(getattr(self.sim, "equity", cash + pos_val))
        return {"equity": equity, "cash": cash, "positions": positions, "logs": [], "trades": 0}

    def _mark_to_market_now(self) -> float:
        """MTM по текущим последним ценам."""
        prices = last_close_prices(self.buffers, [self.token])
        cash = float(getattr(self.sim, "cash", self.sim.cfg.start_cash))
        eq = cash
        positions = getattr(self.sim, "positions", {}) or {}
        for t, p in positions.items():
            qty = float(getattr(p, "qty", 0.0))
            px = float(prices.get(t, getattr(p, "entry", 0.0)))
            eq += qty * px
        return float(eq)

    # ------- gym API -------
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if hasattr(self.sim, "reset"):
            self.sim.reset()

        # дождёмся хотя бы одной свечи (или быстро выйдем, если она уже есть)
        self.buffers.wait_for_new_kline(tokens=[self.token], timeout_sec=self.step_timeout_sec)
        last = self.buffers.last_kline_ts(self.token)
        if last is not None:
            self._last_ts[self.token] = last

        self._last_obs = self._obs()
        return self._last_obs, {"token": self.token}

    def step(self, action: int):
        """
        Порядок:
        1) Берём текущие цены и исполняем действие (по текущей цене).
        2) Фиксируем equity_after_trade.
        3) Ждём НОВУЮ свечу.
        4) Считаем reward как прирост MTM от equity_after_trade до новой цены.
        """
        # --- 1) исполняем действие прямо сейчас (по текущей цене)
        prices_now = last_close_prices(self.buffers, [self.token])

        # маппим действие 0/1/2 -> -1/0/+1 и  исполняем текущее действие через сим
        a = [-1, 0, +1][int(max(0, min(2, action)))]
        _, exec_info_now = self.sim.step(tokens=[self.token], actions=[a], prices=prices_now)

        # --- 2) equity сразу после сделки (учтены кэш/позы/комиссия)
        equity_after_trade = self._mark_to_market_now()

        # --- 3) ждём новую свечу по токену (чтобы награда была за «следующий» тик)
        prev_ts = self._last_ts.get(self.token, self.buffers.last_kline_ts(self.token) or -1.0)
        got = self.buffers.wait_for_new_kline(
            tokens=[self.token],
            since_ts={self.token: prev_ts},
            timeout_sec=self.step_timeout_sec,
            poll_interval_ms=100,
            min_new=1,
        )
        if self.token not in got:
            # таймаут — нет нового тика → ревард 0, но вернём текущее состояние
            info = {"token": self.token, "timeout": True, "exec": exec_info_now}
            obs = self._last_obs if self._last_obs is not None else self._obs()
            return obs, 0.0, False, False, info

        # обновили «последнюю виденную» свечу
        self._last_ts[self.token] = got[self.token]

        # --- 4) ревард: прирост с учётом новой цены после сделки
        prices_new = last_close_prices(self.buffers, [self.token])
        mtm_new = self._mark_to_market_now()
        step_pnl = mtm_new - equity_after_trade

        trades = int(exec_info_now.get("trades", 0))
        reward = step_pnl / self.sim.cfg.start_cash - TRADE_PENALTY * trades

         # наблюдение и возврат
        obs = self._obs()
        self._last_obs = obs    
        info = {
            "token": self.token,
            "price_now": prices_now.get(self.token, 0.0),
            "prices_new": prices_new.get(self.token, 0.0),
            "exec": exec_info_now # сделки этого шага
        }
        return obs, float(reward), False, False, info
