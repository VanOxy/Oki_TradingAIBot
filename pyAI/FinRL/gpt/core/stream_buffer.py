# stream_buffer.py
# минимальный каркас: подписка на ZMQ, буфер по токенам, безопасная нормализация

import json
import time
from collections import deque, defaultdict
from typing import Dict, Any, Deque, Optional

import zmq


# ============ CONFIG ============
ZMQ_ENDPOINT = "tcp://127.0.0.1:5555"  # поменяй на свой
TG_DEQUE_MAX = 10
KLINE_DEQUE_MAX = 72  # ~6 часов по 5м
HEARTBEAT_SEC = 10


# ============ HELPERS ============

def to_float(x: Any, default: float = 0.0) -> float:
    """Строки вида ' 9.632' -> 9.632; None/пустое -> default; ошибки -> default."""
    if x is None:
        return default
    if isinstance(x, (int, float)):
        return float(x)
    try:
        s = str(x).strip().replace(",", ".")
        return float(s) if s else default
    except Exception:
        return default

# one-hot кодирование биржи str -> {0, 1}
def exchange_one_hot(name: Optional[str]) -> Dict[str, float]:
    """One-hot по бирже; масштабируемо на будущее (OKX и пр.)."""
    name = (name or "").strip().lower()
    binance = 1.0 if name == "binance" else 0.0
    bybit   = 1.0 if name == "bybit"   else 0.0
    # пример расширения: okx = 1.0 if name == "okx" else 0.0
    return {"ex_binance": binance, "ex_bybit": bybit}


def now_ts() -> float:
    return time.time()


# ============ BUFFER ============

class TokenBuffer:
    """Хранилище по одному токену: последние TG и KLINE-пакеты + служебные поля."""
    def __init__(self) -> None:
        self.last_tg: Deque[Dict[str, Any]] = deque(maxlen=TG_DEQUE_MAX)
        self.klines: Deque[Dict[str, Any]] = deque(maxlen=KLINE_DEQUE_MAX)
        self.last_seen_ts: float = 0.0

    def update_from_tg(self, pkt: Dict[str, Any]) -> None:
        ts = pkt.get("ts") or now_ts()
        ex = exchange_one_hot(pkt.get("exchange"))
        item = {
            "ts": ts,
            "token": pkt.get("token"),
            "openInterest": to_float(pkt.get("openInterest")),
            "volume": to_float(pkt.get("volume")),
            "trades8h": to_float(pkt.get("trades8h")),  # ByBit -> 0
            "oiChange4h": to_float(pkt.get("oiChange4h")),
            "coinChange24h": to_float(pkt.get("coinChange24h")),
            "notificationsCount8h": to_float(pkt.get("notificationsCount8h")),
            **ex,
        }
        self.last_tg.append(item)
        self.last_seen_ts = ts

    def update_from_kline(self, pkt: Dict[str, Any]) -> None:
        ts = pkt.get("ts") or now_ts()
        # ожидаемые поля: open, high, low, close, volume, MA99/163/200/360, vwap и т.д.
        item = {"ts": ts, "token": pkt.get("token")}
        # переносим всё числовое как float
        for key, val in pkt.items():
            if key in ("type", "token", "exchange"):  # exchange можно игнорить в kline
                continue
            item[key] = to_float(val)
        self.klines.append(item)
        self.last_seen_ts = ts

    def snapshot_light(self) -> Dict[str, Any]:
        """Лёгкий снепшот для логов/отладки (без тяжёлого флэттенинга)."""
        last_tg = self.last_tg[-1] if self.last_tg else None
        last_kl = self.klines[-1] if self.klines else None
        return {
            "last_tg": last_tg,
            "last_kline": last_kl,
            "tg_len": len(self.last_tg),
            "kline_len": len(self.klines),
            "last_seen_ts": self.last_seen_ts,
        }


class Buffers:
    """Глобальный пул: token -> TokenBuffer."""
    def __init__(self) -> None:
        self.tokens: Dict[str, TokenBuffer] = defaultdict(TokenBuffer)

    def handle_packet(self, pkt: Dict[str, Any]) -> None:
        t = (pkt.get("type") or "").strip().lower()
        token = pkt.get("token")
        if not token:
            return
        buf = self.tokens[token]
        if t == "tg":
            buf.update_from_tg(pkt)
        elif t == "kline":
            buf.update_from_kline(pkt)
        # else: игнорим

    def stats(self) -> Dict[str, Any]:
        active = len(self.tokens)
        tg_total = sum(len(b.last_tg) for b in self.tokens.values())
        kl_total = sum(len(b.klines) for b in self.tokens.values())
        return {"active_tokens": active, "tg_items": tg_total, "kline_items": kl_total}

    def snapshot_token(self, token: str) -> Optional[Dict[str, Any]]:
        buf = self.tokens.get(token)
        return buf.snapshot_light() if buf else None


# ============ ZMQ SUBSCRIBER LOOP ============

def run():
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.connect(ZMQ_ENDPOINT)
    sub.setsockopt_string(zmq.SUBSCRIBE, "")  # подписка на всё

    poller = zmq.Poller()
    poller.register(sub, zmq.POLLIN)

    buffers = Buffers()
    last_hb = 0.0  # время последнего heartbeat

    print(f"✅ SUB подключен к {ZMQ_ENDPOINT}. Жду пакеты…")
    try:
        while True:
            # ждём до 1000 мс, чтобы уметь печатать heartbeat
            socks = dict(poller.poll(timeout=1000))
            if sub in socks and socks[sub] == zmq.POLLIN:
                raw = sub.recv()  # bytes
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except Exception:
                    print("Не смог распарсить JSON 1")
                    # попробуем ещё раз: вдруг уже dict->str->bytes
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        print("⚠️  Не смог распарсить JSON:", raw[:200])
                        continue

                # минимальная валидация
                if not isinstance(msg, dict) or "type" not in msg:
                    print("⚠️  Некорректный пакет:", msg)
                    continue

                buffers.handle_packet(msg)

            # heartbeat раз в HEARTBEAT_SEC
            now = now_ts()
            if now - last_hb >= HEARTBEAT_SEC:
                s = buffers.stats()
                print(f"💓 heartbeat | tokens={s['active_tokens']} "
                      f"tg={s['tg_items']} kl={s['kline_items']}")
                last_hb = now

    except KeyboardInterrupt:
        print("\n🧹 Завершение по Ctrl+C")
        s = buffers.stats()
        print("Итоговая статистика:", s)

        # Пример: быстрый снепшот по конкретному токену
        example = next(iter(buffers.tokens.keys()), None)
        if example:
            snap = buffers.snapshot_token(example)
            print(f"🔎 Снепшот по {example}:", json.dumps(snap, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
