import WebSocket from 'ws';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

class BinanceSpotLargeTrades {
    constructor(symbols = ['btcusdt'], minAmountUSD = 10000) {
        if (!Array.isArray(symbols) || symbols.length === 0) {
            throw new Error('Symbols must be a non-empty array');
        }
        this.symbols = [...new Set(symbols.map(s => s.toLowerCase()))]; // Убираем дубликаты
        this.minAmountUSD = minAmountUSD;
        this.ws = null;
        this.socketUrl = null; // Явная инициализация
        this.reconnectAttempts = 0; // Счетчик попыток переподключения
        this.maxReconnectAttempts = 5; // Максимум попыток
        this.reconnectDelay = 1000; // Задержка 1 секунда
        this.shutdown = false; // Флаг завершения
        this.updateSocketUrl();
    }

    updateSocketUrl() {
        const streams = this.symbols.map(s => `${s}@aggTrade`).join('/');
        this.socketUrl = `wss://stream.binance.com:9443/stream?streams=${streams}`;
    }

    addSymbol(symbol) {
        const normalizedSymbol = symbol.toLowerCase();
        if (this.symbols.includes(normalizedSymbol)) {
            console.log(`Символ ${normalizedSymbol} уже в подписке`);
            return false;
        }
        this.symbols.push(normalizedSymbol);
        console.log(`Добавлен символ: ${normalizedSymbol}. Переподключение...`);
        this.restart();
        return true;
    }

    restart() {
        if (this.ws) {
            this.ws.close();
        }
        this.updateSocketUrl();
        this.run();
    }

    onMessage(message) {
        try {
            const msg = JSON.parse(message);
            const trade = msg.data;
            if (trade) {
                const amountUSD = parseFloat(trade.p) * parseFloat(trade.q);
                if (amountUSD >= this.minAmountUSD) {
                    console.log(`📈 Крупная сделка: ${trade.s}`);
                    console.log(`Сторона: ${trade.m ? 'Sell' : 'Buy'}`);
                    console.log(`Объем: ${parseFloat(trade.q).toFixed(4)}`);
                    console.log(`Цена: ${parseFloat(trade.p).toFixed(2)} USD`);
                    console.log(`Сумма: ${amountUSD.toFixed(2)} USD`);
                    console.log(`Время: ${new Date(trade.T).toISOString().replace('T', ' ').slice(0, 19)}`);
                    console.log('-'.repeat(50));
                }
            }
        } catch (error) {
            console.error(`Ошибка обработки сообщения: ${error.message}`);
        }
    }

    onError(error) {
        console.error(`Ошибка: ${error.message}`);
    }

    onClose() {
        console.log('Соединение закрыто');
        if (!this.shutdown && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Попытка переподключения ${this.reconnectAttempts}/${this.maxReconnectAttempts} через ${this.reconnectDelay}ms...`);
            setTimeout(() => this.restart(), this.reconnectDelay);
        } else if (!this.shutdown) {
            console.error('Достигнут лимит попыток переподключения. Инициируется завершение работы...');
            this.shutdown();
        }
        // Если this.shutdown === true, ничего не делаем, так как закрытие инициировано shutdown
    }

    onOpen() {
        console.log(`Соединение открыто. Отслеживание крупных сделок для: ${this.symbols.join(', ')}`);
        this.reconnectAttempts = 0; // Сбрасываем счетчик при успешном подключении
    }

    async shutdown() {
        if (this.shutdown) {
            return; // Предотвращаем повторный вызов shutdown
        }
        console.log('Завершение работы...');
        this.shutdown = true; // Устанавливаем флаг
        if (this.ws) {
            this.ws.close(); // Закрываем соединение
            this.ws = null; // Очищаем ws, чтобы избежать дальнейших событий
        }
        process.exit(0);
    }

    run() {
        if (this.shutdown) {
            return; // Не запускаем новое соединение, если завершение уже инициировано
        }
        this.ws = new WebSocket(this.socketUrl);
        this.ws.on('open', () => this.onOpen());
        this.ws.on('message', (data) => this.onMessage(data));
        this.ws.on('error', (error) => this.onError(error));
        this.ws.on('close', () => this.onClose());
    }
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

if (process.argv[1] === __filename) {
    const symbols = ['btcusdt']; // Начальный список
    const indicator = new BinanceSpotLargeTrades(symbols, 10000);

    // Пример динамического добавления символов с задержкой
    indicator.run();

    setTimeout(() => {
        indicator.addSymbol('ethusdt'); // Добавляем ETH через 5 секунд
    }, 5000);

    setTimeout(() => {
        indicator.addSymbol('bnbusdt'); // Добавляем BNB через 10 секунд
    }, 10000);

    setTimeout(() => {
        indicator.addSymbol('omgusdt'); // Добавляем OMG через 15 секунд
    }, 15000);

    process.on('SIGINT', async () => {
        console.log('\nПолучен сигнал SIGINT (Ctrl+C). Завершаем работу...');
        await indicator.shutdown();
    });
}

export default BinanceSpotLargeTrades;