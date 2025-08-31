# dqn_min.py
import numpy as np
from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env

from stream_buffer import Buffers
from FinRL.gpt.envs.env_single_token import SingleTokenEnv
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
        learning_rate=1e-3,
        buffer_size=5000,
        learning_starts=200,   # чуть накопить опыта
        batch_size=64,
        gamma=0.99,
        target_update_interval=250,
        verbose=1,
        tensorboard_log=None,
    )

    # слегка потреним (синтетика, чтобы просто пройтись по циклу)
    model.learn(total_timesteps=1000)

    # один шаг «предсказания»
    obs, _ = env.reset()
    action, _ = model.predict(obs, deterministic=False)
    obs, reward, _, _, info = env.step(action)
    print("DQN action:", int(action), "reward:", reward, "equity:", info["exec"]["equity"])
