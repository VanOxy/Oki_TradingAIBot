require('dotenv').config();
const fs = require('fs');
const input = require("input");
//const mongoose = require('mongoose');
const { TelegramClient } = require("telegram");
const { StringSession } = require("telegram/sessions");
const { NewMessage } = require("telegram/events");
const { parseNotification } = require('./tools/parsing');

// ====== MONGOOSE ======
// const MessageSchema = new mongoose.Schema({
//   chatId: String,
//   chatName: String,
//   messageId: Number,
//   text: String,
//   date: Date
// });
// const MessageModel = mongoose.model("Message", MessageSchema);

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
  // Подключение к MongoDB
  // await mongoose.connect(process.env.MONGO_URI, { 
  //   useNewUrlParser: true,
  //   useUnifiedTopology: true
  // });
  // console.log("✅ Подключено к MongoDB");

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


  try {
    const dialogs = await client.getDialogs();
    const OIbotDialog = dialogs.find(dialog => dialog.name === process.env.OI_BOT_NAME);
    if (!OIbotDialog) {
      console.error("❌ Канал не найден:", process.env.OI_BOT_NAME);
      return;
    }

    client.addEventHandler(async (event) => {
      const msg = event.message;
      if (!msg.message) return; // пустое сообщение (медиа без текста)
      const parsed = parseNotification(msg.message);
      console.log(parsed);

      //console.log("💬 Новое сообщение:", msg.message);

      // Сохраняем в MongoDB
      // const dbMsg = new MessageModel({
      //   chatId: targetChat.id.toString(),
      //   chatName: targetChat.name,
      //   messageId: msg.id,
      //   text: msg.message,
      //   date: msg.date
      // });
      //await dbMsg.save();

    }, new NewMessage({ chats: [OIbotDialog.id] }));

    // const messages = await client.getMessages(OIbot.id, { limit: 10 });
    // for (const message of messages) {
    //   console.log("💬", message.message);
    // }
  } catch (err) {
    console.error("❌ Ошибка при получении сообщений:", err.message);
  }
})();