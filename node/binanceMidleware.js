import { fetch } from 'undici';

function baseUrl(market, path) {
  const host = market === 'futures'
    ? 'https://fapi.binance.com'
    : 'https://api.binance.com';
  return `${host}${path}`;
}

async function request(url) {
  const res = await fetch(url, { headers: { 'User-Agent': 'oki-bot/1.0' } });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`HTTP ${res.status} ${text}`);
  }
  return res.json();
}

async function getMinuteOHLCV(token, { market = 'spot', timeframe = '1m', limit = 10 } = {}) {
  const path = market === 'futures' ? '/fapi/v1/klines' : '/api/v3/klines';
  const url = baseUrl(market, path) + `?symbol=${symbol}&interval=${timeframe}&limit=${limit}`;

  const raw = await request(url);

  // Документация klines: [ 0openTime, 1open, 2high, 3low, 4close, 5volume, 6closeTime, 7quoteVolume, 8trades, 9takerBuyBase, 10takerBuyQuote, ignore ]
  return raw.map(row => ({
    openTime: new Date(row[0]).toISOString().slice(11, 16), // HH:MM
    open: Number(row[1]),
    high: Number(row[2]),
    low: Number(row[3]),
    close: Number(row[4]),
    quoteVolume: Math.trunc(Number(row[7])),
    trades: row[8],
    takerBuyQuote: Math.trunc(Number(row[10])),
    vwapApprox: (Number(row[7]) / Math.max(Number(row[5]), 1e-12)), // quoteVolume / volume
    typicalPrice: (Number(row[2]) + Number(row[3]) + Number(row[4])) / 3, // (H+L+C)/3
    range: Number(row[2]) - Number(row[3]),

  }));
}

/** ---- Доп. методы ---- */
async function get24h(symbol, { market = 'spot' } = {}) {
  const path = market === 'futures' ? '/fapi/v1/ticker/24hr' : '/api/v3/ticker/24hr';
  return request(baseUrl(market, path) + `?symbol=${symbol}`);
}

async function getBookTicker(symbol, { market = 'spot' } = {}) {
  const path = market === 'futures' ? '/fapi/v1/ticker/bookTicker' : '/api/v3/ticker/bookTicker';
  return request(baseUrl(market, path) + `?symbol=${symbol}`);
}

async function getDepth(symbol, { market = 'spot', limit = 100 } = {}) {
  const safeLimit = Math.min(Math.max(limit, 5), 5000);
  const path = market === 'futures' ? '/fapi/v1/depth' : '/api/v3/depth';
  return request(baseUrl(market, path) + `?symbol=${symbol}&limit=${safeLimit}`);
}

async function getTrades(symbol, { market = 'spot', limit = 1000 } = {}) {
  const safeLimit = Math.min(Math.max(limit, 1), 1000);
  const path = market === 'futures' ? '/fapi/v1/trades' : '/api/v3/trades';
  return request(baseUrl(market, path) + `?symbol=${symbol}&limit=${safeLimit}`);
}

async function getAggTrades(symbol, { market = 'spot', limit = 1000 } = {}) {
  const safeLimit = Math.min(Math.max(limit, 1), 1000);
  const path = market === 'futures' ? '/fapi/v1/aggTrades' : '/api/v3/aggTrades';
  return request(baseUrl(market, path) + `?symbol=${symbol}&limit=${safeLimit}`);
}

/** ---- Только для фьючерсов ---- */
async function getPremiumIndex(symbol) {
  return request(`https://fapi.binance.com/fapi/v1/premiumIndex?symbol=${symbol}`);
}

async function getFundingRateHistory(symbol, { limit = 1000, startTime, endTime } = {}) {
  const params = new URLSearchParams({ symbol, limit: String(Math.min(limit, 1000)) });
  if (startTime) params.set('startTime', String(startTime));
  if (endTime) params.set('endTime', String(endTime));
  return request(`https://fapi.binance.com/fapi/v1/fundingRate?${params}`);
}

async function getOpenInterest(symbol) {
  return request(`https://fapi.binance.com/fapi/v1/openInterest?symbol=${symbol}`);
}

async function getOpenInterestHist(symbol, { period = '5m', limit = 500 } = {}) {
  const safeLimit = Math.min(Math.max(limit, 1), 500);
  return request(`https://fapi.binance.com/futures/data/openInterestHist?symbol=${symbol}&period=${period}&limit=${safeLimit}`);
}

/** ---- demo ---- */
const run = async () => {
  const data = await getMinuteOHLCV('BTCUSDT', { market: 'spot', timeframe: '5m', limit: 5 });
  console.log(data);

  // console.log(await get24h('BTCUSDT'));
  // console.log(await getBookTicker('BTCUSDT'));
  // console.log(await getDepth('BTCUSDT', { limit: 50 }));
  // console.log(await getTrades('BTCUSDT', { limit: 200 }));
  // console.log(await getAggTrades('BTCUSDT', { limit: 200 }));
  // console.log(await getPremiumIndex('BTCUSDT'));
  // console.log(await getFundingRateHistory('BTCUSDT', { limit: 100 }));
  // console.log(await getOpenInterest('BTCUSDT'));
  // console.log(await getOpenInterestHist('BTCUSDT', { period: '15m', limit: 100 }));
};

// to remove at the and of tests
run().catch(console.error);

export { getMinuteOHLCV };

/*
const WebSocket = require('ws');

// Храним все WebSocket-соединения
const connections = [];

async function startBinanceFeed(symbol = 'btcusdt') {
  try {
    const ws = new WebSocket(`wss://stream.binance.com:9443/ws/${symbol}@trade`);
    connections.push(ws);

    ws.on('open', () => {
      console.log(`WebSocket для ${symbol} открыт`);
    });

    ws.on('message', (data) => {
      console.log(`Данные для ${symbol}:`, JSON.parse(data));
    });

    ws.on('error', (error) => {
      console.error(`Ошибка WebSocket для ${symbol}:`, error);
    });

    ws.on('close', () => {
      console.log(`WebSocket для ${symbol} закрыт`);
      // Удаляем из массива при закрытии
      const index = connections.indexOf(ws);
      if (index !== -1) connections.splice(index, 1);
    });

    return new Promise((resolve) => {
      ws.on('open', resolve);
    });
  } catch (error) {
    console.error(`Ошибка при запуске Binance feed для ${symbol}:`, error);
    throw error;
  }
}

async function closeBinanceFeed() {
  const closePromises = connections.map((ws, index) => {
    return new Promise((resolve) => {
      if (ws && ws.readyState !== WebSocket.CLOSED) {
        ws.on('close', () => {
          console.log(`WebSocket ${index + 1} закрыт`);
          resolve();
        });
        ws.close();
      } else {
        console.log(`WebSocket ${index + 1} уже закрыт`);
        resolve();
      }
    });
  });

  await Promise.all(closePromises);
  connections.length = 0; // Очищаем массив
  console.log('Все WebSocket-соединения закрыты');
}

module.exports = { startBinanceFeed, closeBinanceFeed };
*/