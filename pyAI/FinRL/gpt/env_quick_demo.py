# env_quick_demo.py
import numpy as np
import time, json, zmq

from stream_buffer import Buffers
from env_market import MarketEnv, MAX_TOKENS

ENDPOINT = "tcp://127.0.0.1:5555"

def collect_buffers(sec=3.0) -> Buffers:
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.connect(ENDPOINT)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    buffers = Buffers()
    t0 = time.time()
    while time.time() - t0 < sec:
        socks = dict(poller.poll(timeout=200))
        if sub in socks and socks[sub] == zmq.POLLIN:
            raw = sub.recv()
            try:
                msg = json.loads(raw.decode("utf-8"))
            except Exception:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
            if isinstance(msg, dict) and "type" in msg:
                buffers.handle_packet(msg)
    return buffers

if __name__ == "__main__":
    bufs = collect_buffers()
    env = MarketEnv(bufs)
    obs, info = env.reset()
    print("obs shape:", obs.shape, "active_n:", info["active_n"], "tokens:", info["active_tokens"])

    # сэмплим случайные действия из action_space (длина MAX_TOKENS)
    action = env.action_space.sample()
    print("sample action (first 10):", action[:10])

    obs, reward, terminated, truncated, info = env.step(action)
    print("reward:", reward, "| equity:", info["exec"]["equity"], "| cash:", info["exec"]["cash"])
    print("open pos:", info["exec"]["positions"])
    print("logs(<=3):", info["exec"]["logs"][:3])
