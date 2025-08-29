# features_quick_demo.py
import time, json, zmq
from stream_buffer import Buffers
from features import build_batch_state, FEATURE_DIM

ENDPOINT = "tcp://127.0.0.1:5555"  # тот же, куда шлёт твой продюсер
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
    bufs = collect_buffers()
    tokens = list(bufs.tokens.keys())
    print(f"Собрали токены: {tokens}")
    X, used = build_batch_state(bufs, tokens)
    print(f"batch shape = {X.shape}, feature_dim = {FEATURE_DIM}, used = {used[:5]}{'...' if len(used)>5 else ''}")
    if X.shape[0] > 0:
        print("Первые 8 значений первого вектора:", X[0][:8])
