"""
Event-Driven RL Paper Trader — minimal ZMQ-based skeleton (Discrete 3 actions)
===========================================================================

What you get:
- Two async inputs: TG events (irregular) + Binance 5m klines (regular, on close)
- Single decision rhythm: we ONLY trade on KLINE_CLOSE events
- Discrete actions: 0=SELL, 1=HOLD, 2=BUY
- Tier-0 TG features (no encoder yet): last TG snapshot + age features (no decay)
- Paper-trading ledger (PnL, fees), per-asset
- ZMQ SUB listener with one queue for both streams

How to run (suggested):
1) pip install pyzmq
2) python paper_trader.py  (rename this file as you like)
3) Feed JSON messages over ZeroMQ PUB → SUB:
   - TG example (irregular):
     {
       "type": "tg",
       "token": "HUMAUSDT",
       "exchange": "ByBit",
       "openInterest": "8.492",
       "volume": "80.932",
       "trades8h": null,
       "oiChange4h": " 9.632",
       "coinChange24h": " 9.3",
       "notificationsCount8h": "9",
       "ts": 1724001000
     }
   - KLINE example (close event only):
     {
       "type": "kline",
       "exchange": "Binance",
       "token": "HUMAUSDT",
       "interval": "5m",
       "open": 1.2345,
       "high": 1.2400,
       "low": 1.2200,
       "close": 1.2380,
       "volume": 123456.0,
       "is_closed": true,
       "ts_close": 1724001300
     }

Environment variables (or edit defaults below):
- ZMQ_SUB_ADDR:  e.g. "tcp://127.0.0.1:5559"  (subscriber endpoint)
- ZMQ_TOPIC:     if you use pub-sub topics; otherwise leave empty to receive all

Notes:
- If your PUB sends Python repr instead of JSON — we try ast.literal_eval fallback.
- This is a *paper* trader. No real orders here.
- Policy = heuristic by default. Plug your SB3/FinRL model later via Policy interface.
"""

from __future__ import annotations
import os, time, json, math, threading, queue, signal
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Deque
from collections import defaultdict, deque
import ast
import zmq

# ----------------------- Config -----------------------
ZMQ_SUB_ADDR = os.getenv("ZMQ_SUB_ADDR", "tcp://127.0.0.1:5559")
ZMQ_TOPIC = os.getenv("ZMQ_TOPIC", "")  # empty → subscribe to all

# decay for TG features (seconds). Example: 1h half-life ~ tau ≈ 3600 / ln(2)
TAU_SEC = float(os.getenv("TG_DECAY_TAU_SEC", 3600.0))
FEE_BPS = float(os.getenv("FEE_BPS", 3.0))  # 3 bps per turnover leg (example)

# kline window for simple returns (Tier-0 kline features)
RET_WINDOW = int(os.getenv("RET_WINDOW", 3))

# --------------------- Data classes -------------------
@dataclass
class TGFeatures:
    openInterest: Optional[float] = None
    volume: Optional[float] = None
    trades8h: Optional[float] = None
    oiChange4h: Optional[float] = None
    coinChange24h: Optional[float] = None
    notificationsCount8h: Optional[float] = None
    ts: float = 0.0  # epoch seconds of last update

@dataclass
class KlineClose:
    open: float
    high: float
    low: float
    close: float
    volume: float
    ts_close: float

    open: float
    high: float
    low: float
    close: float
    volume: float
    ts_close: float

@dataclass
class AssetState:
    key: str  # "Exchange:TOKEN"
    tg: TGFeatures = field(default_factory=TGFeatures)
    last_close: Optional[float] = None
    position: int = 0  # -1,0,1
    realized_pnl: float = 0.0
    # for simple return features
    close_window: Deque[float] = field(default_factory=lambda: deque(maxlen=RET_WINDOW+1))

# --------------------- Feature utils ------------------

def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        s = str(x).strip()
        if s.lower() == 'none' or s == '':
            return None
        return float(s)
    except Exception:
        return None


def decay_weight(now_ts: float, last_ts: float, tau_sec: float = TAU_SEC) -> float:
    if last_ts <= 0 or now_ts <= last_ts:
        return 1.0 if last_ts > 0 else 0.0
    dt = now_ts - last_ts
    return math.exp(-dt / tau_sec)


def build_observation(asset: AssetState, now_ts: float, kline_feats: Optional[list] = None,
                      event_type: int = 0, trade_allowed: int = 0, last_close_ts: Optional[float] = None) -> list:
    """
    Build Tier-0 observation (fixed-size vector).
    - TG part: last snapshot **without** value decay (we add staleness as separate features)
    - KLINE part: simple return features (if provided), else zeros
    - Meta: one_hot(event_type), trade_allowed, age metrics
    event_type: 0=TG, 1=KLINE_CLOSE
    """
    tg = asset.tg

    def to_num(x):
        v = _to_float(x)
        return 0.0 if v is None else float(v)

    # RAW TG values (no decay). We let the model see staleness via dt_* features instead.
    tg_part = [
        to_num(tg.openInterest),
        to_num(tg.volume),
        to_num(tg.trades8h),
        to_num(tg.oiChange4h),
        to_num(tg.coinChange24h),
        to_num(tg.notificationsCount8h),
    ]

    if kline_feats is None:
        kline_part = [0.0] * (RET_WINDOW)  # returns placeholder
    else:
        kline_part = kline_feats
        if len(kline_part) < RET_WINDOW:
            kline_part = kline_part + [0.0] * (RET_WINDOW - len(kline_part))
        else:
            kline_part = kline_part[:RET_WINDOW]

    # meta
    one_hot = [1.0, 0.0] if event_type == 0 else [0.0, 1.0]
    dt_tg_min = 0.0 if tg.ts <= 0 else max(0.0, (now_ts - tg.ts) / 60.0)
    dt_close_min = 0.0 if last_close_ts is None else max(0.0, (now_ts - last_close_ts) / 60.0)

    obs = tg_part + kline_part + one_hot + [float(trade_allowed), dt_tg_min, dt_close_min]
    return obs

# ----------------------- Policy -----------------------
class Policy:
    """Interface for a trading policy. Replace with your SB3/FinRL model later."""
    def predict(self, obs: list) -> int:
        # Default heuristic: BUY if decayed coinChange24h > 0, SELL if <0, else HOLD
        coin_change = obs[4]  # index per build_observation tg_part[4]
        if coin_change > 0:
            return 2  # BUY
        elif coin_change < 0:
            return 0  # SELL
        else:
            return 1  # HOLD

# -------------------- Paper Trader --------------------
class PaperTrader:
    def __init__(self, fee_bps: float = FEE_BPS):
        self.assets: Dict[str, AssetState] = {}
        self.policy = Policy()
        self.last_close_ts: Dict[str, float] = {}
        self.fee_bps = fee_bps
        self.lock = threading.Lock()

    def get_asset(self, key: str) -> AssetState:
        if key not in self.assets:
            self.assets[key] = AssetState(key=key)
        return self.assets[key]

    def _fees(self, turnover_qty_value: float) -> float:
        # fee in value terms (bps of traded notional)
        return (self.fee_bps / 1e4) * turnover_qty_value

    def on_tg(self, msg: dict):
        key = f"{msg.get('exchange')}:{msg.get('token')}"
        now_ts = float(msg.get('ts') or time.time())
        a = self.get_asset(key)
        a.tg = TGFeatures(
            openInterest=_to_float(msg.get('openInterest')),
            volume=_to_float(msg.get('volume')),
            trades8h=_to_float(msg.get('trades8h')),
            oiChange4h=_to_float(msg.get('oiChange4h')),
            coinChange24h=_to_float(msg.get('coinChange24h')),
            notificationsCount8h=_to_float(msg.get('notificationsCount8h')),
            ts=now_ts,
        )
        # Build observation for TG event (trade_allowed=0) — feeding memory if you switch to RNN in future
        _obs = build_observation(a, now_ts, kline_feats=None, event_type=0, trade_allowed=0,
                                 last_close_ts=self.last_close_ts.get(key))
        # We do NOT trade on TG events; no action taken.

    def on_kline_close(self, msg: dict):
        key = f"{msg.get('exchange')}:{msg.get('token')}"
        a = self.get_asset(key)
        kl = KlineClose(
            open=float(msg['open']), high=float(msg['high']), low=float(msg['low']),
            close=float(msg['close']), volume=float(msg['volume']), ts_close=float(msg['ts_close'])
        )

        # Feature: simple returns over last RET_WINDOW closes
        if a.close_window.maxlen != RET_WINDOW+1:
            a.close_window = deque(maxlen=RET_WINDOW+1)
        a.close_window.append(kl.close)
        rets = []
        if len(a.close_window) >= 2:
            closes = list(a.close_window)
            for i in range(1, len(closes)):
                prev = closes[i-1]
                cur = closes[i]
                rets.append(0.0 if prev == 0 else (cur/prev - 1.0))
        # Build observation for KLINE_CLOSE (trade_allowed=1)
        obs = build_observation(a, kl.ts_close, kline_feats=rets, event_type=1, trade_allowed=1,
                                last_close_ts=self.last_close_ts.get(key))

        # Compute PnL from previous close to this close on existing position
        if a.last_close is not None:
            price_diff = kl.close - a.last_close
            pnl = price_diff * a.position
            a.realized_pnl += pnl
        # Decide new action
        action = self.policy.predict(obs)  # 0 sell, 1 hold, 2 buy
        target_pos = {-1: -1, 0: -1, 1: 0, 2: 1}[action]  # map 0/1/2 → -1/0/1
        # Fees for turnover: |Δpos| * notional (we use close as 1x notional unit for demo)
        turnover = abs(target_pos - a.position) * kl.close
        fees = self._fees(turnover)
        a.realized_pnl -= fees
        # Apply new position
        a.position = target_pos
        a.last_close = kl.close
        self.last_close_ts[key] = kl.ts_close

        print(f"[{time.strftime('%H:%M:%S')}] {key} close={kl.close:.6f} action={action} pos={a.position} PnL={a.realized_pnl:.6f}")

    def snapshot(self) -> Dict[str, dict]:
        out = {}
        for k, a in self.assets.items():
            out[k] = dict(position=a.position, last_close=a.last_close, pnl=a.realized_pnl,
                          last_tg_ts=a.tg.ts)
        return out

# -------------------- ZMQ subscriber ------------------
class ZMQSubscriber(threading.Thread):
    def __init__(self, addr: str, topic: str, out_queue: "queue.Queue[dict]"):
        super().__init__(daemon=True)
        self.addr = addr
        self.topic = topic.encode() if topic else None
        self.out_queue = out_queue
        self.ctx = zmq.Context.instance()
        self.sock = self.ctx.socket(zmq.SUB)
        self.sock.connect(self.addr)
        if self.topic is None:
            self.sock.setsockopt(zmq.SUBSCRIBE, b"")
        else:
            self.sock.setsockopt(zmq.SUBSCRIBE, self.topic)

    def run(self):
        while True:
            try:
                if self.topic is None:
                    raw = self.sock.recv()
                    payload = raw
                else:
                    topic, payload = self.sock.recv_multipart()
                msg = self._parse(payload)
                if msg:
                    self.out_queue.put(msg)
            except Exception as e:
                print("ZMQ recv error:", e)
                time.sleep(0.5)

    @staticmethod
    def _parse(payload: bytes) -> Optional[dict]:
        s = payload.decode('utf-8', errors='ignore').strip()
        try:
            return json.loads(s)
        except Exception:
            try:
                return ast.literal_eval(s)
            except Exception:
                return None

# ----------------------- Runner -----------------------
class Runner:
    def __init__(self):
        self.q: "queue.Queue[dict]" = queue.Queue(maxsize=100000)
        self.sub = ZMQSubscriber(ZMQ_SUB_ADDR, ZMQ_TOPIC, self.q)
        self.trader = PaperTrader()
        self._stop = False

    def start(self):
        self.sub.start()
        signal.signal(signal.SIGINT, self._sig)
        signal.signal(signal.SIGTERM, self._sig)
        print(f"[Runner] Listening {ZMQ_SUB_ADDR} topic='{ZMQ_TOPIC or '*'}'")
        while not self._stop:
            try:
                msg = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            mtype = str(msg.get('type', '')).lower()
            if mtype == 'tg':
                self.trader.on_tg(msg)
            elif mtype == 'kline':
                # only process closed klines
                is_closed = bool(msg.get('is_closed', True))
                if is_closed:
                    self.trader.on_kline_close(msg)
            # else: ignore

    def _sig(self, *args):
        self._stop = True
        print("\n[Runner] Stopping...")

if __name__ == "__main__":
    Runner().start()