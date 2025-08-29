# mock_pub.py
import json, time, zmq, random

PUB_ENDPOINT = "tcp://127.0.0.1:5555"  # тот же, что в stream_buffer.py

ctx = zmq.Context.instance()
pub = ctx.socket(zmq.PUB)
pub.bind(PUB_ENDPOINT)
time.sleep(0.5)  # дать SUB успеть подключиться

tokens = ["HUMAUSDT", "A2ZUSDT"]

def send(obj):
    pub.send(json.dumps(obj).encode("utf-8"))

i = 0
while True:
    # TG пакет
    send({
        "type": "tg",
        "token": random.choice(tokens),
        "exchange": random.choice(["Binance", "ByBit"]),
        "openInterest": f"{8 + random.random()*5:.3f}",
        "volume": f"{80 + random.random()*10:.3f}",
        "trades8h": None,
        "oiChange4h": f"{5 + random.random()*10:.3f}",
        "coinChange24h": f"{-2 + random.random()*6:.1f}",
        "notificationsCount8h": str(i % 12),
        "ts": time.time(),
    })
    time.sleep(1)

    # KLINE пакет (упрощённый)
    send({
        "type": "kline",
        "token": random.choice(tokens),
        "open": 1.0 + random.random()*0.1,
        "high": 1.05 + random.random()*0.1,
        "low": 0.95 + random.random()*0.1,
        "close": 1.0 + random.random()*0.1,
        "volume": 1000 + int(random.random()*500),
        "MA99": 1.0, "MA163": 1.0, "MA200": 1.0, "MA360": 1.0,
        "vwap": 1.0,
        "ts": time.time(),
    })
    i += 1
    time.sleep(1)
