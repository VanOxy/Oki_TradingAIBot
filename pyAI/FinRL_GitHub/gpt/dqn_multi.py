# dqn_multi.py
import time
import torch
from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.callbacks import CheckpointCallback

from env_multi_token import MultiTokenPickEnv
from exec_core import PortfolioSim, ExecConfig
from stream_buffer import Buffers
from config import ENDPOINT, MAX_TOKENS

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
    warm_tokens = len(bufs.tokens) or 1
    K_TRAIN = min(MAX_TOKENS, max(6, warm_tokens))

    sim = PortfolioSim(ExecConfig(risk_per_step=0.02, fee_bps=10.0, slippage_bps=10.0)) #bps --> basis points
    env = MultiTokenPickEnv(
        bufs,
        max_tokens=K_TRAIN,
        sim=sim,
        trade_penalty=1e-4,
        universe=None,
        min_hold_steps=3,
        max_swaps_per_step=1,
        tg_recent_sec=15*60
    )

    check_env(env, warn=True)

    model = DQN(
        "MlpPolicy",
        env,
        device="cuda" if torch.cuda.is_available() else "auto",
        verbose=1,
        learning_rate=2.5e-4,
        buffer_size=50000,
        learning_starts=1000,
        batch_size=256,
        target_update_interval=2000,
        gamma=0.99,
        train_freq=4,
        exploration_fraction=0.5,   # для коротких прогонов — выше ε
        exploration_initial_eps=0.1,
        exploration_final_eps=0.02,
        tensorboard_log="./tb",
    )

    ckpt = CheckpointCallback(save_freq=5000, save_path="./ckpts", name_prefix="dqn_multi")
    model.learn(total_timesteps=5000, progress_bar=True, callback=ckpt)
    #for real stream
    #model.learn(total_timesteps=1000, progress_bar=True, callback=ckpt, reset_num_timesteps=False)
    model.save("./ckpts/dqn_multi_last")

    # sanity: несколько шагов
    print("sanity multi:")
    obs, _ = env.reset()
    for i in range(50):
        # deterministic=True — смотреть, что реально выбирает сеть
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, _, _, info = env.step(action)
        print(f"[{i}] a={int(action)}  r={reward:.6f} slots={info['slots']} eq={info['equity']:.2f} trades={info['trades']}")
        scores = info.get("slot_scores", {})
        if scores:
            print("  scores:", {k: round(v, 3) for k, v in scores.items()})
        if info["logs"]:
            print("  logs:", info["logs"][:2])