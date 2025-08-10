require('dotenv').config();
const fs = require('fs');
const input = require("input");
//const mongoose = require('mongoose');
const { TelegramClient } = require("telegram");
const { StringSession } = require("telegram/sessions");
const { NewMessage } = require("telegram/events");
const { parseNotification } = require('./tools/tgMsgParsing');
const zmqClient = require('./zmq_client');

// ====== GLOBALS ======
const apiId = parseInt(process.env.API_ID); // из твоего приложения Telegram
const apiHash = process.env.API_HASH;       // из того же приложения
const sessionFile = process.env.SESSION;
let isNewSession = false;
let stringSession;

// Попытка загрузить сессию из файла
if (fs.existsSync(sessionFile)) {
  const saved = JSON.parse(fs.readFileSync(sessionFile, 'utf8'));
  stringSession = new StringSession(saved.session);
  console.log("📁 Загружена существующая сессия.");
} else {
  stringSession = new StringSession("");
  isNewSession = true;
  console.log("🆕 Создана новая сессия.");
}

// Создание клиента
const client = new TelegramClient(stringSession, apiId, apiHash, {
    connectionRetries: 5,
});
if (!client) {
  console.error("❌ Error on client creation");
  return;
}

// ====== MAIN ======
(async () => {

  console.log("⚙️ Запускаем Telegram client...");
  // connection
  if(isNewSession){ // если сессии нет — спрашиваем данные и авторизуемся
    console.log("No session detected");
    await client.start({
      phoneNumber: async () => await input.text("📱 Введите номер телефона: "),
      password: async () => await input.text("🔑 Введите 2FA пароль (если включен): "),
      phoneCode: async () => await input.text("📩 Введите код из Telegram: "),
      onError: (err) => console.log(err),
    });
    const savedSession = client.session.save();
    console.log("✅ Успешный вход!");
    fs.writeFileSync(sessionFile, JSON.stringify({session: savedSession}, null, 2));
  } else { // подключаемся без логина
    await client.connect(); 
    console.log("🔌 Подключились по сохранённой сессии.");
  }

  // подключаемся к ZMQ один раз
  await zmqClient.connect();

  const dialogs = await client.getDialogs();
  const OIbotDialog = dialogs.find(dialog => dialog.name === process.env.OI_BOT_NAME);
  if (!OIbotDialog) {
    console.error("❌ Канал не найден:", process.env.OI_BOT_NAME);
    return;
  }

  client.addEventHandler(async (event) => {
    const msg = event.message;
    if (!msg || !msg.message) return;

    const parsed = parseNotification(msg.message);
    console.log(parsed);

    const data = {
      pair: pair,
      exchange: exchange,
      openInterest: openInterest,
      volume: volume,
      trades8h: trades8h,
      oiChange4h: oiChange4h,
      coinChange24h: coinChange24h,
      tradesCount8h: tradesCount8h,
  };

    if (parsed?.type === 'TRIGGER') {
      const f = parsed.features || {};
      const features = [
        nz(f.oi_pct),
        nz(f.volume_pct),
        nz(f.trades_8h),
        nz(f.oi_chg_4h_pct),
        nz(f.coin_chg_24h_pct),
        nz(f.score_8h),
        parsed.exchange === 'Binance' ? 1 : 0,
        parsed.exchange === 'Bybit' ? 1 : 0,
      ];

      try {
        const res = await zmqClient.sendTrigger(parsed.symbol, features);
        if (res.error) {
          console.error("AI error:", res.error);
        } else {
          console.log(`🤖 AI(TRIGGER) ${parsed.symbol} → score=${Number(res.score).toFixed(3)}`);
        }
      } catch (e) {
        console.error("ZMQ Trigger error:", e.message);
      }
    }

    // Когда добавишь сбор рынка (OHLCV/CVD/OI):
  // const marketFeatures = buildMarketFeaturesForSymbol(parsed.symbol);
  // if (marketFeatures) {
  //   try {
  //     const resM = await zmqClient.sendMarket(parsed.symbol, marketFeatures);
  //     if (resM.error) console.error("AI market error:", resM.error);
  //     else console.log(`🤖 AI(MARKET) ${parsed.symbol} → score=${Number(resM.score).toFixed(3)}`);
  //   } catch (e) {
  //     console.error("ZMQ Market error:", e.message);
  //   }
  // }

  }, new NewMessage({ chats: [OIbotDialog.id] }));


  // const messages = await client.getMessages(OIbot.id, { limit: 10 });
  // for (const message of messages) {
  //   console.log("💬", message.message);
  // }
})().catch(console.error);

function nz(v) {
  return (v === null || v === undefined || Number.isNaN(v)) ? 0 : Number(v);
}