# env_multi_token.py
import numpy as np
import gymnasium as gym
from gymnasium import spaces

from stream_buffer import Buffers
from features import build_batch_state, FEATURE_DIM
from exec_core import PortfolioSim, last_close_prices
from config import STEP_TIMEOUT_SEC

class MultiTokenPickEnv(gym.Env):
    """
    Мульти-токен окружение с действием вида: «выбери ОДИН токен и сделай -1/0/+1».
    - Обзор: до K токенов, фичи складываем в один длинный вектор [K * FEATURE_DIM]
    - Действие: Discrete(1 + 2*K)
        0                -> no-op
        1..K             -> SELL токена i (i = a-1)
        (K+1)..(2K)      -> BUY токена (i = a-1-K)
    Награда: dPnL за движение цены с прошлого тика (до исполнения) / start_cash - штраф за частые сделки.
    """
    metadata = {"render_modes": []}

    def __init__(
        self,
        buffers: Buffers,
        max_tokens: int = 5,
        step_timeout_sec: float = STEP_TIMEOUT_SEC,
        sim: PortfolioSim | None = None,
        universe: list[str] | None = None,   # если передали, берём из него; иначе выберем из buffers
        trade_penalty: float = 1e-4,         # мягкий штраф «за сделку на шаге»
    ):
        super().__init__()
        self.buffers = buffers
        self.sim = sim or PortfolioSim()
        self.max_tokens = int(max_tokens)
        self.step_timeout_sec = step_timeout_sec
        self.trade_penalty = float(trade_penalty)

        # Список токенов (порядок важен: индексы действия завязаны на него)
        self.tokens: list[str] = []
        self._last_ts: dict[str, float] = {}   # {token: last_seen_kline_ts}
        self._last_obs: np.ndarray | None = None

        # Экшен: 1 + 2*K (no-op + SELL/BUY по каждому токену)
        self.action_space = spaces.Discrete(1 + 2 * self.max_tokens)
        # Обсервация: объединяем K строк фичей в один длинный вектор
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(self.max_tokens * FEATURE_DIM,), dtype=np.float32
        )

        # если universe задан, используем его (укоротим/обрежем до K)
        self._static_universe = list(universe)[: self.max_tokens] if universe else None

    # ------------ helpers ------------
    def _pick_universe(self) -> list[str]:
        """
        Выбрать до K токенов. Если передали статический universe — использовать его.
        Иначе возьмём первые K токенов, для которых уже приходят kline (по алфавиту для детерминизма).
        """
        if self._static_universe:
            return self._static_universe[: self.max_tokens]

        # динамический выбор по текущему содержимому буфера
        candidates = []
        for t, tb in self.buffers.tokens.items():
            # берём токены, по которым уже есть свечи
            if getattr(tb, "klines", None):
                candidates.append(t)
        candidates.sort()
        if not candidates:
            # fallback: хотя бы какой-то один, чтобы не пусто
            candidates = list(self.buffers.tokens.keys())
            candidates.sort()
        return (candidates or [])[: self.max_tokens]

    def _obs_matrix(self) -> tuple[np.ndarray, list[str]]:
        """
        Собираем матрицу фичей [len(used) x FEATURE_DIM] и список used-токенов,
        затем дополняем нулями до [K x FEATURE_DIM] и разворачиваем в 1D-вектор.
        """
        X, used = build_batch_state(self.buffers, self.tokens)
        k = len(used)
        if k < self.max_tokens:
            pad = np.zeros((self.max_tokens - k, FEATURE_DIM), dtype=np.float32)
            if k > 0:
                X = np.concatenate([X, pad], axis=0)
            else:
                X = pad
        elif k > self.max_tokens:
            X = X[: self.max_tokens]
            used = used[: self.max_tokens]
        return X.reshape(-1).astype(np.float32), used

    def _exec_snapshot(self) -> dict:
        prices = last_close_prices(self.buffers, self.tokens)
        cash = float(getattr(self.sim, "cash", getattr(self.sim, "cfg").start_cash))
        positions = getattr(self.sim, "positions", {}) or {}
        pos_val = 0.0
        for t, p in positions.items():
            qty = float(getattr(p, "qty", 0.0))
            px = float(prices.get(t, getattr(p, "entry", 0.0)))
            pos_val += qty * px
        equity = float(getattr(self.sim, "equity", cash + pos_val))
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

    # ------------ gym API ------------
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)

        # Пересоберём universe (или подтвердим статический)
        self.tokens = self._pick_universe()
        if hasattr(self.sim, "reset"):
            self.sim.reset()
        self._last_ts.clear()

        # дождёмся первой свечи (или быстро выйдем)
        if self.tokens:
            self.buffers.wait_for_new_kline(tokens=self.tokens, timeout_sec=self.step_timeout_sec)
            for t in self.tokens:
                ts = self.buffers.last_kline_ts(t)
                if ts is not None:
                    self._last_ts[t] = ts

        obs_vec, used = self._obs_matrix()
        self._last_obs = obs_vec
        info = {"tokens": used}
        return obs_vec, info

    def step(self, action: int):
        # ждём новую свечу хотя бы по одному из self.tokens
        got = self.buffers.wait_for_new_kline(
            tokens=self.tokens,
            since_ts=self._last_ts,
            timeout_sec=self.step_timeout_sec,
            poll_interval_ms=100,
            min_new=1,
        )
        if not got:
            info = {"timeout": True, "exec": self._exec_snapshot(), "tokens": list(self.tokens)}
            obs = self._last_obs if self._last_obs is not None else self._obs_matrix()[0]
            return obs, 0.0, False, False, info

        for t, ts in got.items():
            self._last_ts[t] = ts

        prices = last_close_prices(self.buffers, self.tokens)

        # PnL за движение до исполнения текущего действия
        mtm_now = self._mark_to_market(prices)
        price_pnl = mtm_now - float(getattr(self.sim, "last_equity", self.sim.cfg.start_cash))

        # Декод действия
        a = int(action)
        K = self.max_tokens
        acts = [0] * len(self.tokens)  # -1/0/+1 по каждому токену (в этом шаге только один ≠ 0)
        trades = 0

        if a == 0:
            pass  # no-op
        elif 1 <= a <= K:
            i = a - 1
            if i < len(self.tokens):
                acts[i] = -1
        elif (K + 1) <= a <= (2 * K):
            i = a - 1 - K
            if i < len(self.tokens):
                acts[i] = +1

        # Исполняем
        _, exec_info = self.sim.step(tokens=self.tokens, actions=acts, prices=prices)
        trades = int(exec_info.get("trades", 0))

        # Награда
        reward = price_pnl / self.sim.cfg.start_cash - self.trade_penalty * trades

        # Наблюдение
        obs_vec, used = self._obs_matrix()
        self._last_obs = obs_vec
        info = {"exec": exec_info, "tokens": used, "timeout": False}
        return obs_vec, float(reward), False, False, info
