import 'dotenv/config';
import fs from 'fs';
import input from 'input';
import { TelegramClient } from 'telegram';
import { StringSession } from 'telegram/sessions/index.js';
import { NewMessage } from 'telegram/events/index.js';
import { parseTgNotification, parseTg1hReportDict } from './tools/tgMsgParsing.js';
import zmqClient from './zmq_client.js';
import KlineFeed from './klineFeed.js';

// ====== GLOBALS ======
const apiId = parseInt(process.env.API_ID); // из твоего приложения Telegram
const apiHash = process.env.API_HASH;       // из того же приложения
const sessionFile = process.env.SESSION;
let isNewSession = false;
let stringSession;

// TELEGRAM
getOrInitSession(sessionFile);
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
  await tgConnect(tgClient, isNewSession);

  // находим диалог с OI-ботом
  const tgDialogs = await tgClient.getDialogs();
  const OIbotDialog = tgDialogs.find(dialog => dialog.name === process.env.OI_BOT_NAME);
  if (!OIbotDialog) {
    console.error("❌ Канал не найден:", process.env.OI_BOT_NAME);
    return;
  }

  // подключаемся к ZMQ
  await zmqClient.connect();

  // ============ INIT BINANCE SPOT KLine STREAM =============
  const klineFeed = new KlineFeed({
    market: 'spot',   // или 'futures'
    interval: '1m',      // '1m','5m','15m', '1h'
    pingInterval: 15000, // интервал пинга в мс
  });

  klineFeed.on('status', s => {
    if (s.type === 'open') console.log('Kline WS connected');
    if (s.type === 'close') console.log('Kline WS closed');
    if (s.type === 'error') console.error('Kline WS error:', s.error?.message);
    if (s.type === 'reconnect_scheduled') console.log('Kline WS reconnect in', s.delay, 'ms');
  });

  klineFeed.on('kline', async candle => {
    console.log("kline --> data from bbn:");
    console.log(`[${candle.interval}] ${candle.symbol} ${candle.openTime} O:${candle.open} H:${candle.high} L:${candle.low} C:${candle.close} qVol:${candle.quoteVolume}`);
    // тут же можешь пушить в zmq
    const res = await zmqClient.sendMarket(candle);
  });

  //klineFeed.connect();

  // ============== subscribe TG messages =====================
  tgClient.addEventHandler(async (event) => {
    const msg = event.message;
    if (!msg || !msg.message) return;

    // manage hourly reports
    if(msg.message.includes("8 HOUR REPORT")) {
      const report = parseTg1hReportDict(msg.message);
      console.log("8 HOUR REPORT");
      console.log( report);
    } else { 
      // manage notifications
      console.log("📬 Получено сообщение от бота:", msg.message);
      console.log("отправляю в парсер");
      const parsed = await parseTgNotification(msg.message);
      console.log("сообщение от ТГ парсера получено:", parsed);
      // check
      if (!parsed || !parsed.token) {
        console.error("❌ Ошибка парсинга сообщения:", msg.message);
        return;
      }
      // manage only binance tokens
      //if(parsed.exchange === 'Binance') {
        // подписываемся на символ в kline
        console.log("run.js --> Подписываемся на символ в kline:", parsed.token);
        //klineFeed.addSymbol(parsed.token);

        // отправляем в zmq
        try { 
          console.log('отсылаем data в zmq');
          const res = await zmqClient.sendTgData(parsed);
          if (res.error) {
            console.error("AI error:", res.error);
          } else {
            console.log(` ответ zmq ${parsed.token} → score=${Number(res.score).toFixed(3)}`);
          }
        } catch (e) {
          console.error("ZMQ error:", e.message);
        }
      //}
    }
  }, new NewMessage({ chats: [OIbotDialog.id] }));
  //testPyServer(zmqClient);
})().catch(error => {
  console.error("❌ Ошибка в основном процессе:", error)
  process.exit(1);
});

// ========= FUNCTIONS ===================

function getOrInitSession(sessionFile) {
  if (fs.existsSync(sessionFile)) {
    const saved = JSON.parse(fs.readFileSync(sessionFile, 'utf8'));
    stringSession = new StringSession(saved.session);
    console.log("Загружена существующая сессия.");
  } else {
    stringSession = new StringSession("");
    isNewSession = true;
    console.log("Создана новая сессия.");
  }
}

async function tgConnect(tgClient, isNewSession) {
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
}

// Обработка graceful shutdown
async function shutdown() {
  console.log('Получен сигнал завершения, закрываем соединения...');
  try {
    console.log('Закрываем соединение с Telegram...');
    await tgClient.disconnect();
    console.log('Соединение с Telegram закрыто.');
    console.log('Закрываем сокет ZMQ...');
    await zmqClient.sock.close();
    console.log('Сокет ZMQ закрыт.');
    console.log('Закрываем соединение с KlineFeed...');
    await klineFeed.close();
    console.log('Соединение с KlineFeed закрыто.');
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
  await shutdown();});
// Обработка необработанных ошибок (опционально)
process.on('uncaughtException', (error) => {
  console.error('Необработанная ошибка:', error);
  shutdown();
});
// Обработка события exit (только логирование, асинхронные операции здесь не работают)
process.on('exit', (code) => {
  console.log(`Процесс завершён с кодом: ${code}`);
});

async function testPyServer(zmqClient){
  const data = {
    token: 'UMAUSDT',
    exchange: 'ByBit',
    openInterest: '10.817',
    volume: '87.344',
    coinChange24h: ' 1.3',
    oiChange4h: '9.783',
    trades8h: 7777,
    notificationsCount8h: '3',
  };
  try{
    const res = await zmqClient.sendTgData(data);
    if (res.error) {
      console.error("AI error:", res.error);
    } else {
      console.log(`🤖 AI(TRIGGER) ${res.symbol} → score=${Number(res.score).toFixed(3)}`);
    }
  } catch (e) {
    console.error("ZMQ Trigger error:", e.message);
  }
}