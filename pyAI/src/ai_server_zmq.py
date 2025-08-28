import zmq
import json
import pandas as pd
import numpy as np

ADDR = "tcp://*:5555" 

def handle_tg_message(msg):
    token = msg.get("token")
    print('received ' + token )
    print(msg)
    #features = msg.get("features", [])
    # TODO: вызов твоей модели для триггера
    return {"handle_tg_message принял": token}

def handle_bnn_market_data(msg):
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
            raw = sock.recv_string()
            msg = json.loads(raw)
            mtype = (msg.get("type") or "").lower()

            if mtype == "tg":
                resp = handle_tg_message(msg)
            elif mtype == "bnn_market":
                resp = handle_bnn_market_data(msg)
            else:
                resp = {"error": f"unknown type '{mtype}'"}

            sock.send_string(json.dumps(resp))
        except Exception as e:
            print("Error:", e)
            sock.send_string(json.dumps({"error": str(e)}))

if __name__ == "__main__":
    main()
