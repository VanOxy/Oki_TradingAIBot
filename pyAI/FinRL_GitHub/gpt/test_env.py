# import gym
# import ray
# import pandas as pd
# import zmq

# print("gym:", gym.__version__)
# print("ray:", ray.__version__)
# print("pandas:", pd.__version__)
# print("pyzmq:", zmq.__version__)
# print("Setup successful!")

import gym, pandas as pd, zmq
try:
    import ray
    from stable_baselines3 import DQN
    ok = True
except Exception as e:
    ok = e

print("gym:", gym.__version__)
print("pandas:", pd.__version__)
print("pyzmq:", zmq.__version__)
print("ray:", getattr(ray, "__version__", "missing"))
print("sb3.DQN import:", "OK" if ok is True else f"ERR: {ok}")