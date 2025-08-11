# ai_server_zmq.py
import zmq
import json

ADDR = "tcp://*:5555"  # слушаем все интерфейсы; можно сузить

def handle_trigger(msg):
    symbol = msg.get("symbol")
    features = msg.get("features", [])
    # TODO: вызов твоей модели для триггера
    score = 0.5  # заглушка
    return {"symbol": symbol, "score": float(score), "type": "trigger"}

def handle_market(msg):
    symbol = msg.get("symbol")
    features = msg.get("features", [])
    # TODO: вызов твоей модели для рынка (PPO/FinRL и т.п.)
    score = 0.7  # заглушка
    return {"symbol": symbol, "score": float(score), "type": "market"}

def main():
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(ADDR)
    print(f"✅ AI ZMQ server listening on {ADDR}")

    while True:
        try:
            raw = sock.recv_string()        # ждём JSON
            msg = json.loads(raw)
            mtype = (msg.get("type") or "").lower()

            if mtype == "trigger":
                resp = handle_trigger(msg)
            elif mtype == "market":
                resp = handle_market(msg)
            else:
                resp = {"error": f"unknown type '{mtype}'"}

            sock.send_string(json.dumps(resp))
        except Exception as e:
            print("Error:", e)
            sock.send_string(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    main()
