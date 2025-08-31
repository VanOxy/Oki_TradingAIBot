# single_token_demo.py
import json, time, zmq, numpy as np
from stream_buffer import Buffers
from FinRL.gpt.envs.env_single_token import SingleTokenEnv

ENDPOINT = "tcp://127.0.0.1:5555"
TOKEN = "HUMAUSDT"

def prime_buffers(sec=3.0):
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.connect(ENDPOINT)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    poller = zmq.Poller(); poller.register(sub, zmq.POLLIN)

    bufs = Buffers()
    t0 = time.time()
    while time.time() - t0 < sec:
        socks = dict(poller.poll(timeout=200))
        if sub in socks and socks[sub] == zmq.POLLIN:
            raw = sub.recv()
            try:
                msg = json.loads(raw.decode("utf-8"))
            except Exception:
                try: msg = json.loads(raw)
                except Exception: continue
            if isinstance(msg, dict) and "type" in msg:
                bufs.handle_packet(msg)
    return bufs

if __name__ == "__main__":
    bufs = prime_buffers()
    env = SingleTokenEnv(bufs, TOKEN)
    obs, info = env.reset()
    print("obs shape:", obs.shape, "token:", info["token"])

    # сэмплим случайное действие {0,1,2}
    action = np.random.randint(0, 3)
    obs, reward, term, trunc, info = env.step(action)
    print("action:", action, "reward:", reward, "equity:", info["exec"]["equity"], "cash:", info["exec"]["cash"])
