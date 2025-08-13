import { fetch } from 'undici';

async function getMinuteOHLCV(token, { market = 'spot', timeframe = '1m', limit = 10 } = {}) {
  const baseUrl =
    market === 'futures'
      ? 'https://fapi.binance.com/fapi/v1/klines'
      : 'https://api.binance.com/api/v3/klines';

  const url = `${baseUrl}?symbol=${token}&interval=${timeframe}&limit=${limit}`;

  const res = await fetch(url, { headers: { 'User-Agent': 'ohlcv-bot/1.0' } });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Binance ${market} klines HTTP ${res.status} ${text}`);
  }
  const raw = await res.json();

  // Документация klines: [ openTime, open, high, low, close, volume, closeTime, quoteVolume, trades, takerBuyBase, takerBuyQuote, ignore ]
  return raw.map(row => ({
    openTime: new Date(row[0]).getUTCMinutes(),
    open: Number(row[1]),
    high: Number(row[2]),
    low: Number(row[3]),
    close: Number(row[4]),
    volume: Number(row[5]),                  // base asset volume
    quoteVolume: Number(row[7]),
    trades: row[8],
    takerBuyBase: Number(row[9]),
    takerBuyQuote: Number(row[10]),
  }));
}

const run = async () => {
  const data = await getMinuteOHLCV('BTCUSDT', { market: 'spot', timeframe: '5m', limit: 5 });
  console.log('Свечей:', data.length);
  console.log('Последняя свеча:', data[data.length - 1]);
};

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