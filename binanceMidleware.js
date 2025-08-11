const Binance = require('node-binance-api');
const binance = new Binance().options({
  APIKEY: process.env.BINANCE_API_KEY,
  APISECRET: process.env.BINANCE_API_SECRET,
});

async function fetchMarketData(pair) {
  const ticker = await binance.prices(pair);
  const kline = await binance.candlesticks(pair, "1m", null, { limit: 1 });
  return {
    price: ticker[pair],
    open: kline[0][1],
    high: kline[0][2],
    low: kline[0][3],
    close: kline[0][4],
    volume: kline[0][5],
    timestamp: new Date(),
  };
}

// Запуск каждую минуту
setInterval(async () => {
  const data = await fetchMarketData("OLUSDT");
  console.log("📈 Данные с биржи:", data);
}, 60 * 1000);