# env_single_token.py
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from stream_buffer import Buffers
from features import build_batch_state, FEATURE_DIM
from exec_core import PortfolioSim, last_close_prices

class SingleTokenEnv(gym.Env):
    """
    Простое окружение для одного токена:
    - obs: (FEATURE_DIM,)
    - action: Discrete(3) -> {0,1,2} => {-1,0,+1}
    Внутри используем PortfolioSim; остальные токены считаем 'hold'.
    """
    metadata = {"render_modes": []}

    def __init__(self, buffers: Buffers, token: str):
        super().__init__()
        self.buffers = buffers
        self.token = token
        self.sim = PortfolioSim()

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(FEATURE_DIM,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0,1,2 -> -1,0,+1

    def _obs(self):
        X, used = build_batch_state(self.buffers, [self.token])
        if len(used) == 0:
            # если нет данных — вернем нули
            return np.zeros((FEATURE_DIM,), dtype=np.float32)
        return X[0]

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        obs = self._obs()
        info = {"token": self.token}
        return obs, info

    def step(self, action):
        # map 0,1,2 -> -1,0,+1
        a = int(action)
        a = max(0, min(2, a))
        mapped = [-1, 0, +1][a]

        # цены только по нашему токену
        prices = last_close_prices(self.buffers, [self.token])
        reward, exec_info = self.sim.step([self.token], [mapped], prices)

        obs = self._obs()
        terminated = False
        truncated = False
        info = {"token": self.token, "exec": exec_info, "price": prices.get(self.token, 0.0)}
        return obs, float(reward), terminated, truncated, info
