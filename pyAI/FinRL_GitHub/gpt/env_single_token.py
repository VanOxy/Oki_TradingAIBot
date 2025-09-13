# env_single_token.py
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from stream_buffer import Buffers
from features import build_batch_state, FEATURE_DIM
from exec_core import PortfolioSim, last_close_prices
from config import STEP_TIMEOUT_SEC

class SingleTokenEnv(gym.Env):
    """
    Окружение для одного токена.
    obs: (FEATURE_DIM,)
    action: Discrete(3) -> {0,1,2} => {-1,0,+1}
    Внутри используем PortfolioSim; остальные токены считаем HOLD.
    """
    metadata = {"render_modes": []}

    def __init__(self, buffers: Buffers, token: str, step_timeout_sec: float = STEP_TIMEOUT_SEC):
        super().__init__()
        self.buffers = buffers
        self.token = token
        self.sim = PortfolioSim()
        self.step_timeout_sec = step_timeout_sec
        self._last_ts = {}        # {token: last_seen_kline_ts}
        self._last_obs = None

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(FEATURE_DIM,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0,1,2 -> -1,0,+1

    def _obs(self):
        X, used = build_batch_state(self.buffers, [self.token])
        if len(used) == 0:
            return np.zeros((FEATURE_DIM,), dtype=np.float32)
        return X[0]
    
    def _safe_exec_snapshot(self):
        # даже если у симулятора нет полей, аккуратно соберём exec
        prices = last_close_prices(self.buffers, [self.token])
        cash = float(getattr(self.sim, "cash", getattr(self.sim, "cfg").start_cash))
        positions = dict(getattr(self.sim, "positions", {}))
        pos_val = 0.0
        for tok, pos in positions.items():
            qty = float(pos.get("qty", 0.0))
            px = float(prices.get(tok, pos.get("entry", 0.0)))
            pos_val += qty * px
        equity = float(getattr(self.sim, "equity", cash + pos_val))
        return {"equity": equity, "cash": cash, "positions": positions, "logs": [], "trades": 0}

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        # дождёмся хотя бы одной свечи (или быстро выйдем, если она уже есть)
        self.buffers.wait_for_new_kline(tokens=[self.token], timeout_sec=self.step_timeout_sec)
        # зафиксируем последнюю виденную TS (если есть)
        last = self.buffers.last_kline_ts(self.token)
        if last is not None:
            self._last_ts[self.token] = last
        self._last_obs = self._obs()
        return self._last_obs, {"token": self.token}

    def step(self, action):
        # 1) ждём новый kline, чтобы reward был «за следующий тик»
        prev_ts = self._last_ts.get(self.token, self.buffers.last_kline_ts(self.token) or -1.0)
        new_map = self.buffers.wait_for_new_kline(
            tokens=[self.token],
            since_ts={self.token: prev_ts},
            timeout_sec=self.step_timeout_sec,
            poll_interval_ms=100,
            min_new=1,
        )

        # Не блокировать шаг, если тик не пришёл
        if self.token not in new_map:
            # таймаут — шаг пустой, но info.exec обязательно есть
            info = {"token": self.token, "timeout": True, "exec": self._safe_exec_snapshot()}
            return self._last_obs if self._last_obs is not None else self._obs(), 0.0, False, False, info

        # 2) обновили «последнюю виденную» свечу
        self._last_ts[self.token] = new_map[self.token]

        # 3) исполняем действие через симулятор
        a = int(max(0, min(2, int(action))))
        mapped = [-1, 0, +1][a]

        prices = last_close_prices(self.buffers, [self.token])
        step_pnl, exec_info = self.sim.step(tokens=[self.token], actions=[mapped], prices=prices)

        # 4) награда: PnL/начальный капитал - штраф за сделки в этом шаге
        executed_trades = int(exec_info.get("trades", 0))
        reward = step_pnl / self.sim.cfg.start_cash - 0.0005 * executed_trades

        # 5) наблюдение и возврат
        obs = self._obs()
        self._last_obs = obs
        terminated = False
        truncated = False
        info = {
            "token": self.token,
            "price": prices.get(self.token, 0.0),
            "exec": exec_info
        }
        return obs, float(reward), terminated, truncated, info
