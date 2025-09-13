# dqn_min.py
import numpy as np
import torch
from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env

from stream_buffer import Buffers
from env_single_token import SingleTokenEnv
from single_token_demo import prime_buffers

TOKEN = "HUMAUSDT"

if __name__ == "__main__":
    bufs = prime_buffers(3.0)
    env = SingleTokenEnv(bufs, TOKEN)

    # проверка совместимости
    check_env(env, warn=True)

    model = DQN(
        "MlpPolicy",
        env,
        device="cuda" if torch.cuda.is_available() else "auto",
        verbose=1,
        learning_rate=1e-3,
        buffer_size=5000,
        learning_starts=200,
        batch_size=64,
        target_update_interval=250,

        gamma=0.99,

        tensorboard_log=None,
    )

    # слегка потреним (синтетика, чтобы просто пройтись по циклу)
    model.learn(total_timesteps=100)

    # один шаг «предсказания»
    obs, _ = env.reset()
    action, _ = model.predict(obs, deterministic=False)
    obs, reward, _, _, info = env.step(action)
    print("DQN action:", int(action), "reward:", reward, "equity:", info["exec"]["equity"])
