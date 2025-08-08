require('dotenv').config();
const fs = require('fs');
const input = require("input");
const { TelegramClient } = require("telegram");
const { StringSession } = require("telegram/sessions");

// GLOBALS
const apiId = parseInt(process.env.API_ID); // из твоего приложения Telegram
const apiHash = process.env.API_HASH;       // из того же приложения
const sessionFile = process.env.SESSION;

let stringSession;
let isNewSession = false;

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
    console.log("💾 Ваш session string:", savedSession);
    fs.writeFileSync(sessionFile, JSON.stringify({session: savedSession}, null, 2));
  } else { // подключаемся без логина
    await client.connect(); 
    console.log("🔌 Подключились по сохранённой сессии.");
  }

  const dialogs = await client.getDialogs();

  try {
    const OIbot = dialogs.find(dialog => dialog.name === process.env.OI_BOT_NAME);
    if (!OIbot) {
      console.error("❌ Канал не найден:", process.env.OI_BOT_NAME);
      return;
    }

    const messages = await client.getMessages(OIbot.id, { limit: 10 });
    for (const message of messages) {
      console.log("💬", message.message);
    }
  } catch (err) {
    console.error("❌ Ошибка при получении сообщений:", err.message);
  }
})();