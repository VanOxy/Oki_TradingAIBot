// klineFeed.js  (ESM) <--> @binance/connector
import WebSocket from 'ws';
import { EventEmitter } from 'events';

export default class KlineFeed extends EventEmitter {
  /**
   * @param {Object} opts
   * @param {'spot'|'futures'} [opts.market='spot']
   * @param {string} [opts.interval='1m'] e.g. '1m','5m','15m','1h'
   * @param {number(ms)} [opts.pingInterval=15000]
   */
  constructor({ market = 'spot', interval = '1m', pingInterval = 15000 } = {}) {
    super();
    this.market = market;
    this.interval = interval;
    this.pingInterval = pingInterval;

    this.ws = null;
    this.connected = false;
    this.symbols = new Set();    // хранит символы в нижнем регистре
    this._pingTimer = null;
    this._reconnectTimer = null;
    this._reconnectAttempts = 0;
  }

  // Получить URL конечной точки WebSocket
  get endpoint() {
    return this.market === 'futures'
      ? 'wss://fstream.binance.com/ws'   // фьючи
      : 'wss://stream.binance.com:9443/ws'; // спот
  }

  /** Подключиться (или переподключиться) */
  connect() {
    if (this.ws) this.ws.close();
    this.ws = new WebSocket(this.endpoint);

    this.ws.on('open', () => {
      this.connected = true;
      this._reconnectAttempts = 0;
      this.emit('status', { type: 'open' });
      // подписываем всё, что есть в пуле
      if (this.symbols.size) {
        this._send({
          method: 'SUBSCRIBE',
          params: [...this.symbols].map(s => `${s}@kline_${this.interval}`),
          id: Date.now(),
        });
      }
      // пинги
      this._startPing();
    });

    this.ws.on('message', (buf) => {
      const msg = JSON.parse(buf.toString());
      // ответы на SUB/UNSUB игнорим
      if (msg?.result === null) return;

      // сообщения с kline
      if (msg?.e === 'kline' && msg?.k) {
        const k = msg.k;
        // берём событие только при закрытии свечи
        if (k.x === true) {
          const payload = mapKlineTokenClose(msg.s, k);
          this.emit('kline', payload);
        }
      }
    });

    this.ws.on('error', (err) => {
      this.emit('status', { type: 'error', error: err });
    });

    this.ws.on('close', () => {
      this.connected = false;
      this.emit('status', { type: 'close' });
      this._stopPing();
      this._scheduleReconnect();
    });
  }

  /** Добавить символ в пул и подписаться */
  addSymbol(symbol) {
    const s = String(symbol).toLowerCase();
    if (this.symbols.has(s)) return;
    this.symbols.add(s);
    console.log("Kline --> Подписываемся на символ:", s);
    console.log("pool --> ", this.symbols);
    if (this.connected) {
      this._send({
        method: 'SUBSCRIBE',
        params: [`${s}@kline_${this.interval}`],
        id: Date.now(),
      });
    }
  }

  /** Удалить символ из пула и отписаться */
  removeSymbol(symbol) {
    const s = String(symbol).toLowerCase();
    if (!this.symbols.has(s)) return;
    this.symbols.delete(s);
    if (this.connected) {
      this._send({
        method: 'UNSUBSCRIBE',
        params: [`${s}@kline_${this.interval}`],
        id: Date.now(),
      });
    }
  }

  /** Сменить интервал на лету (переподписка) */
  setInterval(interval) {
    if (interval === this.interval) return;
    const prev = this.interval;
    this.interval = interval;

    if (this.connected && this.symbols.size) {
      // отписаться от старого интервала
      this._send({
        method: 'UNSUBSCRIBE',
        params: [...this.symbols].map(s => `${s}@kline_${prev}`),
        id: Date.now(),
      });
      // подписаться на новый
      this._send({
        method: 'SUBSCRIBE',
        params: [...this.symbols].map(s => `${s}@kline_${this.interval}`),
        id: Date.now() + 1,
      });
    }
  }

  /** Закрыть соединение */
  close() {
    this._stopPing();
    clearTimeout(this._reconnectTimer);
    this._reconnectTimer = null;
    if (this.ws) {
      try { this.ws.close(); } catch {}
    }
    this.ws = null;
    this.connected = false;
  }

  /* --- внутренние --- */
  _send(obj) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify(obj), err => console.log(err));
  }

  _startPing() {
    this._stopPing();
    this._pingTimer = setInterval(() => {
      try { this.ws?.ping?.(); } catch {}
    }, this.pingInterval);
  }
  _stopPing() {
    if (this._pingTimer) {
      clearInterval(this._pingTimer);
      this._pingTimer = null;
    }
  }
  _scheduleReconnect() {
    if (this._reconnectTimer) return;
    const delay = Math.min(30000, 1000 * Math.pow(2, this._reconnectAttempts++)); // экспон. backoff до 30с
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this.connect();
    }, delay);
    this.emit('status', { type: 'reconnect_scheduled', delay });
  }
}

/** Приводим kline от Binance к твоему формату */
function mapKlineTokenClose(symbol, k) {
  // k: { t: openTime, T: closeTime, s: symbol, i: interval, f, L, o,h,l,c, v, n, x, q, V, Q, B }
  const open = Number(k.o);
  const high = Number(k.h);
  const low  = Number(k.l);
  const close = Number(k.c);

  return {
    symbol,
    interval: k.i,
    // твой прежний формат:
    openTime: new Date(k.t).toISOString().slice(11, 16), // HH:MM
    open,
    high,
    low,
    close,
    quoteVolume: Math.trunc(Number(k.q)),
    trades: k.n,
    takerBuyQuote: Math.trunc(Number(k.Q)),
    vwapApprox: Number(k.v) ? Number(k.q) / Number(k.v) : 0,
    typicalPrice: (high + low + close) / 3,
    range: (high - low),
    isFinal: k.x === true,
  };
}