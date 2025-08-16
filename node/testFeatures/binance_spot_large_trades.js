import WebSocket from 'ws';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

class BinanceSpotLargeTrades {
    constructor(symbols = ['btcusdt'], minAmountUSD = 10000) {
        if (!Array.isArray(symbols) || symbols.length === 0) {
            throw new Error('Symbols must be a non-empty array');
        }
        this.symbols = [];
        this.minAmountUSD = minAmountUSD;
        this.ws = null;
        this.socketUrl = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
        this.shutdown = false;
        this.validSymbols = new Set();
        this.cacheExpiration = 0;
        this.cacheDuration = 3600 * 1000; // 1 час
        // Инициализация символов
        this.initializeSymbols(symbols).then(() => {
            if (this.symbols.length > 0) {
                this.updateSocketUrl();
                this.run();
            } else {
                console.error('Нет валидных символов для подписки. Завершение работы.');
                this.shutdown();
            }
        });
    }

    async fetchExchangeInfo() {
        try {
            const response = await fetch('https://api.binance.com/api/v3/exchangeInfo');
            if (!response.ok) {
                throw new Error(`HTTP ошибка: ${response.status}`);
            }
            const data = await response.json();
            this.validSymbols = new Set(
                data.symbols
                    .filter(s => s.status === 'TRADING')
                    .map(s => s.symbol.toLowerCase())
            );
            this.cacheExpiration = Date.now() + this.cacheDuration;
            console.log(`Кэш символов обновлен. Всего активных пар: ${this.validSymbols.size}`);
        } catch (error) {
            console.error(`Ошибка при получении exchangeInfo: ${error.message}`);
            this.validSymbols = new Set();
            this.cacheExpiration = 0;
        }
    }

    async validateSymbol(symbol) {
        if (Date.now() > this.cacheExpiration) {
            await this.fetchExchangeInfo();
        }
        return this.validSymbols.has(symbol.toLowerCase());
    }

    async initializeSymbols(symbols) {
        await this.fetchExchangeInfo();
        for (const symbol of symbols) {
            const normalizedSymbol = symbol.toLowerCase();
            if (await this.validateSymbol(normalizedSymbol)) {
                this.symbols.push(normalizedSymbol);
            } else {
                console.warn(`Символ ${normalizedSymbol} невалиден или не торгуется. Пропущен.`);
            }
        }
    }

    updateSocketUrl() {
        if (this.symbols.length === 0) {
            this.socketUrl = null;
            return;
        }
        const streams = this.symbols.map(s => `${s}@aggTrade`).join('/');
        this.socketUrl = `wss://stream.binance.com:9443/stream?streams=${streams}`;
        console.log(`Обновлен socketUrl: ${this.socketUrl}`);
    }

    /**
     * @param {string} symbol - Символ для добавления в подписку
     */
    async addSymbol(symbol) {
        const normalizedSymbol = symbol.toLowerCase();
        if (this.symbols.includes(normalizedSymbol)) {
            console.log(`Символ ${normalizedSymbol} уже в подписке`);
            return false;
        }
        if (await this.validateSymbol(normalizedSymbol)) {
            this.symbols.push(normalizedSymbol);
            console.log(`Добавлен символ: ${normalizedSymbol}. Переподключение...`);
            this.restart();
            return true;
        } else {
            console.warn(`Символ ${normalizedSymbol} невалиден или не торгуется. Не добавлен.`);
            return false;
        }
    }

    restart() {
        if (this.shutdown || this.symbols.length === 0) {
            console.log('Переподключение отменено: завершение или пустой список символов');
            return;
        }
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.updateSocketUrl();
        setTimeout(() => this.run(), this.reconnectDelay); // Задержка перед новым подключением
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
        console.error(`Ошибка WebSocket: ${error.message}`);
        // Переподключение обрабатывается в onClose
    }

    onClose() {
        console.log('Соединение закрыто');
        if (!this.shutdown && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Попытка переподключения ${this.reconnectAttempts}/${this.maxReconnectAttempts} через ${this.reconnectDelay}ms...`);
            this.restart();
        } else if (!this.shutdown) {
            console.error('Достигнут лимит попыток переподключения. Инициируется завершение работы...');
            this.shutdown();
        }
    }

    onOpen() {
        console.log(`Соединение открыто. Отслеживание крупных сделок для: ${this.symbols.join(', ')}`);
        this.reconnectAttempts = 0;
    }

    async shutdown() {
        if (this.shutdown) {
            return;
        }
        console.log('Завершение работы...');
        this.shutdown = true;
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        process.exit(0);
    }

    run() {
        if (this.shutdown || this.symbols.length === 0 || !this.socketUrl) {
            console.log('Подключение отменено: завершение, пустой список символов или отсутствует socketUrl');
            return;
        }
        try {
            this.ws = new WebSocket(this.socketUrl);
            this.ws.on('open', this.onOpen.bind(this));
            this.ws.on('message', this.onMessage.bind(this));
            this.ws.on('error', this.onError.bind(this));
            this.ws.on('close', this.onClose.bind(this));
        } catch (error) {
            console.error(`Ошибка при создании WebSocket: ${error.message}`);
            this.onClose(); // Запускаем переподключение
        }
    }
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

if (process.argv[1] === __filename) {
    const symbols = ['btcusdt', 'ethusdt', 'invalidusdt'];
    const indicator = new BinanceSpotLargeTrades(symbols, 10000);

    setTimeout(() => {
        indicator.addSymbol('bnbusdt');
    }, 5000);

    setTimeout(() => {
        indicator.addSymbol('adausdt'); // Заменил omgusdt на существующую пару
    }, 10000);

    setTimeout(() => {
        indicator.addSymbol('xyzusdt');
    }, 15000);

    process.on('SIGINT', async () => {
        console.log('\nПолучен сигнал SIGINT (Ctrl+C). Завершаем работу...');
        await indicator.shutdown();
    });
}

export default BinanceSpotLargeTrades;