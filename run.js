import 'dotenv/config';
import fs from 'fs';
import input from 'input';
import { TelegramClient } from 'telegram';
import { StringSession } from 'telegram/sessions/index.js';
import { NewMessage } from 'telegram/events/index.js';
import { parseNotification } from './tools/tgMsgParsing.js';
import zmqClient from './zmq_client.js';
import KlineFeed from './klineFeed.js';
import { log } from 'console';

// ====== GLOBALS ======
const apiId = parseInt(process.env.API_ID); // из твоего приложения Telegram
const apiHash = process.env.API_HASH;       // из того же приложения
const sessionFile = process.env.SESSION;
let isNewSession = false;
let stringSession;

// Загрузка сессии из файла
if (fs.existsSync(sessionFile)) {
  const saved = JSON.parse(fs.readFileSync(sessionFile, 'utf8'));
  stringSession = new StringSession(saved.session);
  console.log("Загружена существующая сессия.");
} else {
  stringSession = new StringSession("");
  isNewSession = true;
  console.log("Создана новая сессия.");
}

// TELEGRAM
const tgClient = new TelegramClient(stringSession, apiId, apiHash, {
    connectionRetries: 5,
});
if (!tgClient) {
  console.error("❌ Error on Tg client creation");
  process.exit(1);
}

// ====== MAIN ======
(async () => {

  console.log("⚙️ Запускаем Telegram client...");
  // connection
  if(isNewSession){ // если сессии нет — спрашиваем данные и авторизуемся
    console.log("No session detected");
    await tgClient.start({
      phoneNumber: async () => await input.text("📱 Введите номер телефона: "),
      password: async () => await input.text("🔑 Введите 2FA пароль (если включен): "),
      phoneCode: async () => await input.text("📩 Введите код из Telegram: "),
      onError: (err) => console.log(err),
    });
    const savedSession = tgClient.session.save();
    console.log("✅ Успешный вход!");
    fs.writeFileSync(sessionFile, JSON.stringify({session: savedSession}, null, 2));
  } else { // подключаемся без логина
    await tgClient.connect(); 
    console.log("🔌 Подключились по сохранённой сессии.");
  }

  // находим диалог с OI-ботом
  const tgDialogs = await tgClient.getDialogs();
  const OIbotDialog = tgDialogs.find(dialog => dialog.name === process.env.OI_BOT_NAME);
  if (!OIbotDialog) {
    console.error("❌ Канал не найден:", process.env.OI_BOT_NAME);
    return;
  }

  // подключаемся к ZMQ
  await zmqClient.connect();

  // ============ BINANCE STREAM =============
  const klineFeed = new KlineFeed({
    market: 'spot',   // или 'futures'
    interval: '1m',      // '1m','5m','15m', '1h'
    pingInterval: 15000, // интервал пинга в мс
  });

  klineFeed.on('status', s => {
    if (s.type === 'open') console.log('WS connected');
    if (s.type === 'close') console.log('WS closed');
    if (s.type === 'error') console.error('WS error:', s.error?.message);
    if (s.type === 'reconnect_scheduled') console.log('reconnect in', s.delay, 'ms');
  });

  klineFeed.on('kline', (candle) => {
    console.log(`[${candle.interval}] ${candle.symbol} ${candle.openTime} O:${candle.open} H:${candle.high} L:${candle.low} C:${candle.close} qVol:${candle.quoteVolume}`);
    // тут же можешь пушить в свою AI-модель/очередь
  });

  klineFeed.connect();

  tgClient.addEventHandler(async (event) => {
    const msg = event.message;
    if (!msg || !msg.message) return;

    const parsed = parseNotification(msg.message);
    console.log("📬 сообщение от ТГ парсера");
    console.log(parsed);

  //   const data = {
  //     exchange: exchange,
  //     openInterest: openInterest,
  //     volume: volume,
  //     trades8h: trades8h,
  //     oiChange4h: oiChange4h,
  //     coinChange24h: coinChange24h,
  //     tradesCount8h: tradesCount8h,
  // };

    try {
      const res = await zmqClient.sendTgData(parsed.token, features);
      if (res.error) {
        console.error("AI error:", res.error);
      } else {
        console.log(`🤖 AI(TRIGGER) ${parsed.symbol} → score=${Number(res.score).toFixed(3)}`);
      }
    } catch (e) {
      console.error("ZMQ Trigger error:", e.message);
    }

    // Когда добавишь сбор рынка (OHLCV/CVD/OI):
  // const marketFeatures = buildMarketFeaturesForSymbol(parsed.symbol);
  // if (marketFeatures) {
  //   try {
  //     const resM = await zmqClient.sendMarket(parsed.symbol, marketFeatures);
  //     if (resM.error) console.error("AI market error:", resM.error);
  //     else console.log(`🤖 AI(MARKET) ${parsed.symbol} → score=${Number(resM.score).toFixed(3)}`);

  }, new NewMessage({ chats: [OIbotDialog.id] }));
})().catch(error => {
  console.error("❌ Ошибка в основном процессе:", error)
  process.exit(1);
});

function nz(v) {
  return (v === null || v === undefined || Number.isNaN(v)) ? 0 : Number(v);
}

// Обработка graceful shutdown
async function shutdown() {
  console.log('Получен сигнал завершения, закрываем соединения...');
  try {
    //await closeBinanceFeed();
    console.log('Все соединения закрыты, завершаем процесс');
    process.exit(0);
  } catch (error) {
    console.error('Ошибка при закрытии соединений:', error);
    process.exit(1);
  }
}

// Обработка SIGINT (Ctrl+C)
process.on('SIGINT', async () => {
  console.log('Получен SIGINT (Ctrl+C)');
  await shutdown();
});

// Обработка SIGTERM (например, от Docker или ОС)
process.on('SIGTERM', async () => {
  console.log('Получен SIGTERM');
  await shutdown();
});

// Обработка необработанных ошибок (опционально)
process.on('uncaughtException', (error) => {
  console.error('Необработанная ошибка:', error);
  shutdown();
});

// Обработка события exit (только логирование, асинхронные операции здесь не работают)
process.on('exit', (code) => {
  console.log(`Процесс завершён с кодом: ${code}`);
});