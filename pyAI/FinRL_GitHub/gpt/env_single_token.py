# env_single_token.py
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from stream_buffer import Buffers
from features import build_batch_state, FEATURE_DIM
from exec_core import PortfolioSim, last_close_prices
from config import STEP_TIMEOUT_SEC

TRADE_PENALTY = 0.0  # было 0.0005 — пока обнулим, чтобы агент не коллапсировал в HOLD

class SingleTokenEnv(gym.Env):
    """
    Окружение для одного токена.
    obs: (FEATURE_DIM,)
    action: Discrete(3) -> 0,1,2 => {-1,0,+1}
    Внутри используем PortfolioSim; остальные токены считаем HOLD.
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
        self._last_ts: dict[str, float] = {}   # {token: last_seen_kline_ts}
        self._last_obs: np.ndarray | None = None

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(FEATURE_DIM,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0,1,2 -> -1,0,+1

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
        # positions может быть dict[str, dataclass Position]
        positions = getattr(self.sim, "positions", {}) or {}
        pos_val = 0.0
        for t, p in positions.items():
            qty = float(getattr(p, "qty", 0.0))
            px = float(prices.get(t, getattr(p, "entry", 0.0)))
            pos_val += qty * px
        equity = float(getattr(self.sim, "equity", cash + pos_val))
        # логи и trades пустые — это просто снимок
        return {"equity": equity, "cash": cash, "positions": positions, "logs": [], "trades": 0}
    
    def _mark_to_market(self, prices: dict) -> float:
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
        # СБРОС СИМУЛЯТОРА ДО СТАРТОВОГО СОСТОЯНИЯ
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
        # 1) ждём новую свечу по токену (чтобы награда была за «следующий» тик)
        prev_ts = self._last_ts.get(self.token, self.buffers.last_kline_ts(self.token) or -1.0)
        got = self.buffers.wait_for_new_kline(
            tokens=[self.token],
            since_ts={self.token: prev_ts},
            timeout_sec=self.step_timeout_sec,
            poll_interval_ms=100,
            min_new=1,
        )
        if self.token not in got:
            # таймаут — «пустой» шаг, но возвращаем exec-снимок для стабильного логирования
            info = {"token": self.token, "timeout": True, "exec": self._exec_snapshot()}
            obs = self._last_obs if self._last_obs is not None else self._obs()
            return obs, 0.0, False, False, info

        # 2) обновили «последнюю виденную» свечу
        self._last_ts[self.token] = got[self.token]
        prices = last_close_prices(self.buffers, [self.token])

        # 3) PnL ЗА ДВИЖЕНИЕ ЦЕНЫ С ПРОШЛОГО ТИКА (до сделки)
        mtm_now = self._mark_to_market(prices)
        price_pnl = mtm_now - float(getattr(self.sim, "last_equity", self.sim.cfg.start_cash))

        # 4) маппим действие 0/1/2 -> -1/0/+1 и  исполняем текущее действие через сим
        a = [-1, 0, +1][int(max(0, min(2, action)))]
        _, exec_info = self.sim.step(tokens=[self.token], actions=[a], prices=prices)

        # 5) reward: dPnL/начальный капитал - лёгкий штраф за частые сделки
        trades = int(exec_info.get("trades", 0))
        # reward = price_pnl / self.sim.cfg.start_cash - 0.0005 * trades
        reward = price_pnl / self.sim.cfg.start_cash - TRADE_PENALTY * trades

         # 6) наблюдение и возврат
        obs = self._obs()
        self._last_obs = obs    
        info = {
            "token": self.token,
            "price": prices.get(self.token, 0.0),
            "exec": exec_info
        }
        return obs, float(reward), False, False, info
