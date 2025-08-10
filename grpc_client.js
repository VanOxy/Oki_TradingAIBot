const fs = require('fs');
const grpc = require('@grpc/grpc-js');
const protoLoader = require('@grpc/proto-loader');
const path = require('path');

const packageDef = protoLoader.loadSync('aimodelservice.proto', {});
const aimodelservice = grpc.loadPackageDefinition(packageDef).aimodelservice;

const client = new aimodelservice.AIModelService(
  "localhost:50051",
  grpc.credentials.createInsecure()
);

// Загружаем картинку
//const chartImage = fs.readFileSync("chart.png");

// Отправка триггера
export function sendTrigger(symbol, features) {
  client.SendTrigger({
    symbol: symbol,
    exchange: 'Binance',
    trigger_features: features, //[12.3, 0, 0.55, 0],
    timestamp: Date.now()
  }, (err, res) => {
    console.log('Trigger →', res);
  });
}

// Отправка рыночных данных
export function sendMarketData(symbol, features) {
  client.SendMarketData({
    symbol: symbol,
    exchange: 'Binance',
    ohlcv_1m: [1,2,3,4,5],
    ohlcv_5m: [1,2,3,4,5],
    open_interest: 123456,
    ma163: 1.1,
    ma200: 1.2,
    ma360: 1.3,
    vwap: 1.4,
    vwap_dev1: 0.1,
    vwap_dev2: 0.2,
    cvd_spot: 0.5,
    cvd_futures: -0.3,
    liq_buy: 1000,
    liq_sell: 800,
    timestamp: Date.now()
  }, (err, res) => {
    console.log('Market →', res);
  });
}

client.AnalyzeTrade({
  symbol: "BTC/USDT",
  price: 29950.12,
  timestamp: new Date().toISOString(),
  chart_image: chartImage
}, (err, response) => {
  if (err) {
    console.error("Ошибка:", err);
  } else {
    console.log(`Решение: ${response.decision} (уверенность ${response.confidence * 100}%)`);
  }
});






