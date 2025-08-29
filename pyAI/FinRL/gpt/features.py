# features.py
# Строит фиксированный вектор признаков для каждого токена из TokenBuffer.

from typing import List, Dict, Any, Tuple
import numpy as np
import time

from stream_buffer import TokenBuffer, Buffers  # run() не вызовется — он под if __main__


# ---- Конфиг фич ----
TG_SEQ = 10
KLINE_WIN = 72

# TG-фичи на один элемент последовательности:
# [openInterest, volume, trades8h, oiChange4h, coinChange24h, notificationsCount8h,
#  ex_binance, ex_bybit, age_minutes]
TG_FEAT_PER_ITEM = 9
TG_TOTAL = TG_SEQ * TG_FEAT_PER_ITEM

# Kline-фичи:
# текущие: [open, high, low, close, volume]
# спред: [ (high-low)/close ]
# ретерны: [r1, r3, r12, r36, r72] (если мало данных — 0)
# вола: [std_logret_12, std_logret_36]
# объем: [vol_rel_12] (последний объем / mean последних 12 - 1)
# дистанции до MA/VWAP: [d_ma99,d_ma163,d_ma200,d_ma360,d_vwap] = (close-MA)/MA
KLINE_FEAT_DIM = 5 + 1 + 5 + 2 + 1 + 5  # = 19

FEATURE_DIM = TG_TOTAL + KLINE_FEAT_DIM


def _safe_get_float(d: Dict[str, Any], key: str, default: float = 0.0) -> float:
    v = d.get(key)
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).strip().replace(",", ".")
        return float(s) if s else default
    except Exception:
        return default


def _build_tg_seq_features(buf: TokenBuffer, now_ts: float) -> np.ndarray:
    """Последние TG (до 10 штук) -> вектор длиной TG_TOTAL, паддинг нулями."""
    out = np.zeros((TG_SEQ, TG_FEAT_PER_ITEM), dtype=np.float32)

    # Идём с конца (самые свежие) и кладём вправо, чтобы порядок был консистентным.
    items = list(buf.last_tg)[-TG_SEQ:]
    start = TG_SEQ - len(items)

    for i, itm in enumerate(items, start=start):
        ts = _safe_get_float(itm, "ts", default=now_ts)
        age_min = max(0.0, (now_ts - ts) / 60.0)

        out[i, 0] = _safe_get_float(itm, "openInterest")
        out[i, 1] = _safe_get_float(itm, "volume")
        out[i, 2] = _safe_get_float(itm, "trades8h")
        out[i, 3] = _safe_get_float(itm, "oiChange4h")
        out[i, 4] = _safe_get_float(itm, "coinChange24h")
        out[i, 5] = _safe_get_float(itm, "notificationsCount8h")
        out[i, 6] = _safe_get_float(itm, "ex_binance")
        out[i, 7] = _safe_get_float(itm, "ex_bybit")
        out[i, 8] = age_min

    return out.reshape(-1)  # (TG_SEQ*TG_FEAT_PER_ITEM,)


def _build_kline_features(buf: TokenBuffer) -> np.ndarray:
    """Окно до 72 Kline -> компактный набор фич фикс. размера."""
    if not buf.klines:
        return np.zeros((KLINE_FEAT_DIM,), dtype=np.float32)

    kl = list(buf.klines)[-KLINE_WIN:]
    close = np.array([_safe_get_float(x, "close") for x in kl], dtype=np.float64)
    open_ = np.array([_safe_get_float(x, "open") for x in kl], dtype=np.float64)
    high = np.array([_safe_get_float(x, "high") for x in kl], dtype=np.float64)
    low = np.array([_safe_get_float(x, "low") for x in kl], dtype=np.float64)
    vol = np.array([_safe_get_float(x, "volume") for x in kl], dtype=np.float64)

    def last_or0(arr):
        return float(arr[-1]) if arr.size else 0.0

    out = []

    # текущие OHLCV
    out += [last_or0(open_), last_or0(high), last_or0(low), last_or0(close), last_or0(vol)]

    # спред
    c_last = last_or0(close)
    h_last = last_or0(high)
    l_last = last_or0(low)
    spread = (h_last - l_last) / c_last if c_last != 0 else 0.0
    out.append(spread)

    # ретерны over horizons
    def ret_h(h):
        if close.size > h and close[-h] != 0:
            return float(close[-1] / close[-h] - 1.0)
        return 0.0

    for h in (1, 3, 12, 36, 72):
        out.append(ret_h(h))

    # волатильность по логретам
    def std_logret(n):
        if close.size > 1:
            lr = np.diff(np.log(np.clip(close[-(n+1):], 1e-12, None)))
            return float(np.std(lr)) if lr.size > 0 else 0.0
        return 0.0

    out.append(std_logret(12))
    out.append(std_logret(36))

    # относительный объем к среднему за 12
    if vol.size >= 1:
        mean12 = np.mean(vol[-12:]) if vol.size >= 12 else np.mean(vol)
        vol_rel = (vol[-1] / mean12 - 1.0) if mean12 > 0 else 0.0
    else:
        vol_rel = 0.0
    out.append(vol_rel)

    # дистанции до MA/VWAP
    def dist_to(field):
        v = _safe_get_float(kl[-1], field)
        if v != 0.0 and c_last != 0.0:
            return float((c_last - v) / v)
        return 0.0

    for field in ("MA99", "MA163", "MA200", "MA360", "vwap"):
        out.append(dist_to(field))

    return np.asarray(out, dtype=np.float32)  # (KLINE_FEAT_DIM,)


def build_token_state(buf: TokenBuffer, now_ts: float | None = None) -> np.ndarray:
    """Единый вектор признаков фиксированного размера FEATURE_DIM для одного токена."""
    now_ts = now_ts or time.time()
    tg_vec = _build_tg_seq_features(buf, now_ts)
    kl_vec = _build_kline_features(buf)
    # конкат:
    out = np.concatenate([tg_vec, kl_vec], axis=0)
    # sanity:
    if out.shape[0] != FEATURE_DIM:
        # на всякий — выровняем паддингом/усечём
        if out.shape[0] < FEATURE_DIM:
            out = np.pad(out, (0, FEATURE_DIM - out.shape[0]))
        else:
            out = out[:FEATURE_DIM]
    return out.astype(np.float32)


def build_batch_state(buffers: Buffers, tokens: List[str]) -> Tuple[np.ndarray, List[str]]:
    """Батч для списка токенов -> [N, FEATURE_DIM], + список реально построенных токенов."""
    feats = []
    used = []
    for t in tokens:
        buf = buffers.tokens.get(t)
        if not buf:
            continue
        feats.append(build_token_state(buf))
        used.append(t)
    if not feats:
        return np.zeros((0, FEATURE_DIM), dtype=np.float32), []
    return np.stack(feats, axis=0), used
