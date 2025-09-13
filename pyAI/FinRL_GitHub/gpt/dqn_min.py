# dqn_min2.py
import torch
import time
from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.callbacks import CheckpointCallback

from env_single_token import SingleTokenEnv
from single_token_demo import prime_buffers
from stream_buffer import Buffers

TOKEN = "HUMAUSDT"

def attach_buffers(token: str, endpoint: str | None = None, warmup_sec: float = 3.0) -> Buffers:
    """
    Создаёт Buffers и ждёт появления хотя бы одной свечи по token.
    endpoint=None -> используем дефолт конструктора Buffers().
    """
    try:
        bufs = Buffers(attach_endpoint=endpoint) if endpoint else Buffers()
    except TypeError:
        # на случай, если у Buffers другой сигнатуры
        bufs = Buffers()

    deadline = time.time() + warmup_sec
    while time.time() < deadline and bufs.last_kline_ts(token) is None:
        bufs.wait_for_new_kline([token], timeout_sec=0.5)
    return bufs

if __name__ == "__main__":
    bufs = attach_buffers(TOKEN, endpoint=None, warmup_sec=3.0) # мок/стрим уже крутится — 3 сек на прогрев
    env = SingleTokenEnv(bufs, TOKEN)

    # проверка совместимости
    check_env(env, warn=True)

    model = DQN(
        "MlpPolicy",
        env,
        device="cuda" if torch.cuda.is_available() else "auto",
        verbose=1,
        learning_rate=2.5e-4,
        buffer_size=50_000,
        learning_starts=1_000,
        batch_size=256,
        target_update_interval=2_000,
        gamma=0.99,
        train_freq=4,
        exploration_fraction=0.2,
        exploration_initial_eps=0.10,
        exploration_final_eps=0.02,
        tensorboard_log="./tb",
    )

    ckpt = CheckpointCallback(save_freq=5_000, save_path="./ckpts", name_prefix="dqn")
    model.learn(total_timesteps=100, progress_bar=True, callback=ckpt)
    model.save("./ckpts/dqn_last")
    
    # sanity: три шага подряд
    obs, _ = env.reset()
    for i in range(3):
        action, _ = model.predict(obs, deterministic=False)
        obs, reward, _, _, info = env.step(action)
        eq = info.get("exec", {}).get("equity", float("nan"))
        print(f"[sanity {i}] a={int(action)} r={reward:.6f} eq={eq:.2f}")