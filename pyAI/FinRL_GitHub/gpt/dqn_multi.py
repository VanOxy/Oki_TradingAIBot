# dqn_multi.py
import time
import torch
from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.callbacks import CheckpointCallback

from env_multi_token import MultiTokenPickEnv
from exec_core import PortfolioSim, ExecConfig
from stream_buffer import Buffers
from config import ENDPOINT

MAX_TOKENS = 5       # размер портфеля, на котором учимся

def attach_buffers_any(endpoint: str, warmup_sec: float = 3.0) -> Buffers:
    bufs = Buffers(attach_endpoint=endpoint)
    deadline = time.time() + warmup_sec
    while time.time() < deadline:
        # ждём хотя бы один токен с kline
        has_any = any(getattr(tb, "klines", None) for tb in bufs.tokens.values())
        if has_any:
            break
        bufs.wait_for_new_kline(list(bufs.tokens.keys()) or ["HUMAUSDT"], timeout_sec=0.5)
    return bufs

if __name__ == "__main__":
    bufs = attach_buffers_any(ENDPOINT, warmup_sec=3.0)
    # агрессивнее риск, чтобы сделки были заметнее
    sim = PortfolioSim(ExecConfig(risk_per_step=0.1, fee_bps=0.0, slippage_bps=0.0))
    #env = MultiTokenPickEnv(bufs, max_tokens=MAX_TOKENS, sim=sim, trade_penalty=TRADE_PENALTY)
    env = MultiTokenPickEnv(
        bufs,
        max_tokens=2,
        sim=sim,
        trade_penalty=1e-4,
        universe=["A2ZUSDT", "HUMAUSDT"]       # зафиксировали порядок
    )

    check_env(env, warn=True)

    model = DQN(
        "MlpPolicy",
        env,
        device="cuda" if torch.cuda.is_available() else "auto",
        verbose=1,
        learning_rate=2.5e-4,
        buffer_size=50_000,
        learning_starts=0,
        batch_size=256,
        target_update_interval=2_000,
        gamma=0.99,
        train_freq=4,
        exploration_fraction=0.2,   # для коротких прогонов — выше ε
        exploration_initial_eps=0.10,
        exploration_final_eps=0.02,
        tensorboard_log="./tb",
    )

    ckpt = CheckpointCallback(save_freq=5_000, save_path="./ckpts", name_prefix="dqn_multi")
    model.learn(total_timesteps=10000, progress_bar=True, callback=ckpt)
    model.save("./ckpts/dqn_multi_last")

    # sanity: несколько шагов
    print("sanity multi:")
    obs, _ = env.reset()
    for i in range(5):
        # deterministic=True — смотреть, что реально выбирает сеть
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, _, _, info = env.step(action)
        ex = info["exec"]
        print(
            f"[{i}] a={int(action)}  r={reward:.6f}  eq={ex['equity']:.2f}  "
            f"trades={ex['trades']}  tokens={info.get('tokens', [])[:MAX_TOKENS]}"
        )
        if ex["logs"]:
            print("  logs:", ex["logs"][:2])
