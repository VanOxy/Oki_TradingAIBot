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
    Простое окружение для одного токена:
    - obs: (FEATURE_DIM,)
    - action: Discrete(3) -> {0,1,2} => {-1,0,+1}
    Внутри используем PortfolioSim; остальные токены считаем 'hold'.
    """
    metadata = {"render_modes": []}

    def __init__(self, buffers: Buffers, token: str, step_timeout_sec: float = STEP_TIMEOUT_SEC):
        super().__init__()
        self.buffers = buffers
        self.token = token
        self.sim = PortfolioSim()
        self.step_timeout_sec = step_timeout_sec

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(FEATURE_DIM,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0,1,2 -> -1,0,+1

    def _obs(self):
        X, used = build_batch_state(self.buffers, [self.token])
        return X[0] if len(used) else np.zeros((FEATURE_DIM,), dtype=np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        return self._obs(), {"token": self.token}

    def step(self, action):
        # 1) ждём новый kline, чтобы reward был «за следующий тик»
        prev_ts = self.buffers.last_kline_ts(self.token)
        self.buffers.wait_for_new_kline(
            [self.token],
            since_ts={self.token: prev_ts or -1.0},
            timeout_sec=self.step_timeout_sec,
            min_new=1,
        )

        # 2) маппим действие "map 0,1,2 -> -1,0,+1" и считаем PnL
        a = int(action); a = 0 if a < 0 else 2 if a > 2 else a
        mapped = [-1, 0, +1][a]

        # цены только по нашему токену
        prices = last_close_prices(self.buffers, [self.token])
        reward, exec_info = self.sim.step([self.token], [mapped], prices)

        obs = self._obs()
        terminated = False
        truncated = False
        info = {"token": self.token, "exec": exec_info, "price": prices.get(self.token, 0.0)}
        return obs, float(reward), terminated, truncated, info
