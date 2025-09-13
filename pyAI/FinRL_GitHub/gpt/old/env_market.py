# env_market.py
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from stream_buffer import Buffers
from features import build_batch_state, FEATURE_DIM
from exec_core import PortfolioSim, last_close_prices
from config import STEP_TIMEOUT_SEC, MAX_TOKENS

# фиксируем верхний предел под action/obs формы
MAX_TOKENS = 80

class MarketEnv(gym.Env):
    """Минимальное Gym-окружение: батч токенов, MultiDiscrete действия {0,1,2} -> {-1,0,+1}."""
    metadata = {"render.modes": []}

    def __init__(self, buffers: Buffers):
        super().__init__()
        self.buffers = buffers
        self.sim = PortfolioSim()          # бюджет, стоп, комиссии уже внутри
        self.tokens_order = []             # текущие активные токены (<= MAX_TOKENS)

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(MAX_TOKENS, FEATURE_DIM), dtype=np.float32
        )
        self.action_space = spaces.MultiDiscrete([3] * MAX_TOKENS)  # 0,1,2 -> -1,0,+1

    def _snapshot_tokens(self):
        # берём список токенов из буфера, обрезаем до MAX_TOKENS
        toks = list(self.buffers.tokens.keys())
        toks.sort()  # стабильный порядок
        self.tokens_order = toks[:MAX_TOKENS]

    def _obs(self):
        # строим батч по активным, затем паддим до MAX_TOKENS
        X, used = build_batch_state(self.buffers, self.tokens_order)
        pad_n = MAX_TOKENS - X.shape[0]
        if pad_n > 0:
            pad = np.zeros((pad_n, X.shape[1]), dtype=X.dtype)
            X = np.vstack([X, pad])
        return X

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._snapshot_tokens()
        obs = self._obs()
        info = {"active_tokens": list(self.tokens_order), "active_n": len(self.tokens_order)}
        return obs, info

    def step(self, action):
        action = np.asarray(action, dtype=np.int64)
        action = np.clip(action, 0, 2)
        active_n = len(self.tokens_order)
        act_active = (action[:active_n] - 1).tolist()  # -> {-1,0,+1}

        # ждём хотя бы 1 новый kline среди активных
        since = {t: self.buffers.last_kline_ts(t) or -1.0 for t in self.tokens_order}
        self.buffers.wait_for_new_kline(
            self.tokens_order,
            since_ts=since,
            timeout_sec=STEP_TIMEOUT_SEC,
            min_new=1,  # можно увеличить, если хочешь ждать всех
        )

        # цены по активным токенам и симуляция шага
        prices = last_close_prices(self.buffers, self.tokens_order)
        reward, exec_info = self.sim.step(self.tokens_order, act_active, prices)

        # новое наблюдение
        obs = self._obs()
        terminated = False
        truncated = False
        info = {
            "active_tokens": list(self.tokens_order),
            "active_n": active_n,
            "prices": prices,
            "exec": exec_info,  # cash/equity/logs, и т.п.
        }
        return obs, float(reward), terminated, truncated, info
