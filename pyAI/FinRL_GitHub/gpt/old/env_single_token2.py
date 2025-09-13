# env_single_token2.py
import gymnasium as gym
from gymnasium import spaces

from stream_buffer import Buffers
from exec_core import PortfolioSim, last_close_prices
from features import build_batch_state, FEATURE_DIM

STEP_TIMEOUT_SEC = 1.0  # для демо

class SingleTokenEnv(gym.Env):
    def __init__(self,  buffers: Buffers, token: str,  step_timeout_sec: float = STEP_TIMEOUT_SEC):
        super().__init__()
        self.token = token
        self.buffers = buffers
        self.sim = PortfolioSim()
        self._last_ts = {}           # {token: last_seen_kline_ts}
        self._last_obs = None
        self.step_timeout_sec = step_timeout_sec

        # действия: 0=SELL(-1), 1=HOLD(0), 2=BUY(+1)
        self.action_space = spaces.Discrete(3)
        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(FEATURE_DIM,), dtype=float
        )

    def _obs(self):
        # берём батч из одного токена и разворачиваем в 1D
        batch, used = build_batch_state(self.buffers, batch_size=1)
        return batch[0]

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        # подождём первую свечу, чтобы было, от чего отталкиваться
        self.buffers.wait_for_new_kline([self.token], timeout_sec=STEP_TIMEOUT_SEC)
        self._last_ts.clear()
        self._last_obs = self._obs()
        return self._last_obs, {}

    def step(self, action: int):
        # 1) ждём НОВУЮ свечу по нашему токену
        new_ts = self.buffers.wait_for_new_kline(
            tokens=[self.token],
            since_ts=self._last_ts,
            timeout_sec=STEP_TIMEOUT_SEC,
            poll_interval_ms=100,
            min_new=1,
        )
        if self.token not in new_ts:
            # таймаут — считаем, что шаг «пустой»
            info = {"timeout": True}
            return self._last_obs, 0.0, False, False, info

        # 2) обновили «последнюю виденную» свечу
        self._last_ts[self.token] = new_ts[self.token]

        # 3) исполняем действие через симулятор
        # перевод 0/1/2 -> -1/0/+1
        a = [-1, 0, +1][int(action)]
        prices = last_close_prices(self.buffers, [self.token])
        step_pnl, info = self.sim.step(tokens=[self.token], actions=[a], prices=prices)

        # 4) наблюдение и награда
        obs = self._obs()
        reward = step_pnl / self.sim.cfg.start_cash

        # 5) для простоты эпизод бесконечный (стрим), done=False
        self._last_obs = obs
        terminated = False
        truncated = False
        return obs, reward, terminated, truncated, info
