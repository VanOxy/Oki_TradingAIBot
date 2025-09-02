# exec_quick_demo.py
from stream_buffer import Buffers
from features import build_batch_state
from exec_core import PortfolioSim, last_close_prices

import random
import time, json, zmq

ENDPOINT = "tcp://127.0.0.1:5555"
COLLECT_SEC = 3.0

def collect_buffers(seconds: float = COLLECT_SEC) -> Buffers:
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.connect(ENDPOINT)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")
    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    buffers = Buffers()
    t0 = time.time()
    while time.time() - t0 < seconds:
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
    # 1) собираем немного данных
    bufs = collect_buffers()
    tokens = list(bufs.tokens.keys())
    print("tokens:", tokens)

    if not tokens:
        print("Нет токенов в пуле — запусти продюсер или mock_pub.py")
        raise SystemExit

    # 2) строим батч фич
    X, used = build_batch_state(bufs, tokens)
    print("batch:", X.shape, "used:", used[:8], "…")

    # 3) цены последних close
    prices = last_close_prices(bufs, used)

    # 4) случайные действия {-1,0,1} (позже их будет давать агент)
    actions = [random.choice([-1, 0, 1]) for _ in used]

    # 5) симуляция одного шага
    sim = PortfolioSim()  # можно подкрутить параметры в ExecConfig()
    reward, info = sim.step(used, actions, prices)

    print("\nACTIONS:", actions[:10], "…")
    print("REWARD:", round(reward, 6))
    print("EQUITY:", info["equity"], "CASH:", info["cash"])
    print("OPEN POS:", info["positions"])
    print("LOGS (первые 5):", info["logs"][:5])
