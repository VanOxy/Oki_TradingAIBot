# dqn_min.py
import time
import torch
from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.callbacks import CheckpointCallback

from env_single_token import SingleTokenEnv
from exec_core import PortfolioSim, ExecConfig
from stream_buffer import Buffers
from config import ENDPOINT

TOKEN = "HUMAUSDT"

def attach_buffers(token: str, endpoint: str, warmup_sec: float = 3.0) -> Buffers:
    """Создаёт Buffers с подпиской на ZMQ и ждёт появления хотя бы одной свечи по token."""
    bufs = Buffers(attach_endpoint=endpoint)
    deadline = time.time() + warmup_sec
    while time.time() < deadline and bufs.last_kline_ts(token) is None:
        bufs.wait_for_new_kline([token], timeout_sec=0.5)
    return bufs

if __name__ == "__main__":
    # 1) мок/стрим уже крутится отдельно (mock_pub.py)
    bufs = attach_buffers(TOKEN, endpoint=ENDPOINT, warmup_sec=3.0) # мок/стрим уже крутится — 3 сек на прогрев

    # маленькая проверка входящих данных
    snap = bufs.snapshot_token(TOKEN)
    print("[warmup snapshot]", snap)

    # 2) более агрессивный сим, чтобы были сделки
    sim = PortfolioSim(ExecConfig(risk_per_step=0.1, fee_bps=0.0, slippage_bps=0.0))
    env = SingleTokenEnv(bufs, TOKEN, sim=sim)

    # проверка совместимости
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
        exploration_fraction=1.0,    # ← весь короткий прогон держим высокий ε
        exploration_initial_eps=1.0, # ← много рандома
        exploration_final_eps=0.2,   # ← и не сильно падаем
        tensorboard_log="./tb",
    )

    ckpt = CheckpointCallback(save_freq=5_000, save_path="./ckpts", name_prefix="dqn")
    model.learn(total_timesteps=300, progress_bar=True, callback=ckpt)
    model.save("./ckpts/dqn_last")

    # sanity: три шага подряд
    print("sanity check...")
    # reset env
    obs, _ = env.reset()
    print("obs_reset --> obs=", obs)
    for i in range(3):
        action, _ = model.predict(obs, deterministic=False)
        obs, reward, _, _, info = env.step(action)
        exec_ = info.get("exec", {})
        print(
            f"[sanity {i}] a={int(action)}  r={reward:.8f}  "
            f"eq={exec_.get('equity', float('nan')):.2f}  "
            f"trades={exec_.get('trades', 0)}  timeout={info.get('timeout', False)}"
        )
        # первые 2 лога, чтобы видеть исполнение
        if exec_.get("logs"):
            print("  logs:", exec_["logs"][:2])

    print("manual sanity (random actions)...")
    obs, _ = env.reset()
    for i in range(3):
        act = env.action_space.sample()   # 0/1/2 случайно
        obs, reward, _, _, info = env.step(act)
        ex = info["exec"]
        print(f"[man {i}] a={act} r={reward:.6f} eq={ex['equity']:.2f} trades={ex['trades']}")
        if ex["logs"]:
            print("  logs:", ex["logs"][:2])