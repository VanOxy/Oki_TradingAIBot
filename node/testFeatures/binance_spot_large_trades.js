import WebSocket from 'ws';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

class BinanceSpotLargeTrades {
    constructor(symbols = [], minAmountUSD = 10000) {
        this.symbols = [];
        this.minAmountUSD = minAmountUSD;
        this.ws = null;
        this.socketUrl = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.baseReconnectDelay = 50; // Фиксированная задержка 50 мс
        this.shutdownFlag = false;
        this.validSymbols = new Set();
        this.cacheExpiration = 0;
        this.cacheDuration = 3600 * 1000; // 1 час
        this.tradeCache = new Map(); // Кэш для фильтрации дубликатов
        this.cacheTradeDuration = 5000; // 5 сек для кэша сделок
        this.restartPending = false; // Флаг для переподключения
        this.symbolQueue = []; // Очередь для символов
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
                    .filter(s => s.status === 'TRADING' && s.quoteAsset === 'USDT')
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
        this.socketUrl = `wss://stream.binance.com:443/stream?streams=${streams}`;
        console.log(`Обновлен socketUrl: ${this.socketUrl}`);
    }

    async addSymbol(symbol) {
        const normalizedSymbol = symbol.toLowerCase();
        if (this.symbols.includes(normalizedSymbol)) {
            console.log(`Символ ${normalizedSymbol} уже в подписке`);
            return false;
        }
        if (await this.validateSymbol(normalizedSymbol)) {
            this.symbolQueue.push(normalizedSymbol);
            console.log(`Символ ${normalizedSymbol} добавлен в очередь. Ожидание переподключения...`);
            await this.processSymbolQueue();
            return true;
        } else {
            console.warn(`Символ ${normalizedSymbol} невалиден или не торгуется. Не добавлен.`);
            return false;
        }
    }

    async processSymbolQueue() {
        if (this.restartPending || this.shutdownFlag || this.symbols.length === 0 && this.symbolQueue.length === 0) {
            return;
        }
        if (this.symbolQueue.length > 0) {
            const symbol = this.symbolQueue.shift();
            this.symbols.push(symbol);
            console.log(`Добавлен символ: ${symbol}. Переподключение...`);
            await this.restart();
        }
    }

    async restart() {
        if (this.shutdownFlag || this.symbols.length === 0 && this.symbolQueue.length === 0) {
            console.log('Переподключение отменено: завершение или пустой список символов');
            return;
        }
        if (this.restartPending) {
            console.log('Переподключение уже запланировано');
            return;
        }
        this.restartPending = true;
        if (this.ws && this.ws.readyState !== WebSocket.CLOSED) {
            await new Promise(resolve => {
                this.ws.on('close', () => {
                    this.ws = null;
                    resolve();
                });
                this.ws.close();
            });
        }
        setTimeout(() => {
            this.restartPending = false;
            this.run();
            this.processSymbolQueue(); // Обрабатываем очередь после переподключения
        }, this.baseReconnectDelay);
    }

    onMessage(message) {
        if (this.shutdownFlag) return; // Игнорировать сообщения после shutdown
        try {
            const msg = JSON.parse(message);
            const trade = msg.data;
            if (trade) {
                const amountUSD = parseFloat(trade.p) * parseFloat(trade.q);
                if (amountUSD >= this.minAmountUSD) {
                    const tradeKey = `${trade.s}:${trade.T}:${trade.p}:${trade.q}:${trade.m}:${trade.a}`;
                    if (!this.tradeCache.has(tradeKey)) {
                        this.tradeCache.set(tradeKey, Date.now());
                        // Очистка старых записей из кэша
                        const now = Date.now();
                        for (const [key, timestamp] of this.tradeCache) {
                            if (now - timestamp > this.cacheTradeDuration) {
                                this.tradeCache.delete(key);
                            }
                        }
                        console.log(`📈 Крупная сделка: ${trade.s}`);
                        console.log(`Сумма: ${amountUSD.toFixed(2)} USD`);
                        console.log(`Сторона: ${trade.m ? 'Sell' : 'Buy'}`);
                        console.log(`Объем: ${parseFloat(trade.q).toFixed(4)}`);
                        console.log(`Цена: ${parseFloat(trade.p).toFixed(2)} USD`);
                        console.log(`Время: ${new Date(trade.T).toISOString().replace('T', ' ').slice(0, 19)}`);
                        console.log('-'.repeat(50));
                    }
                }
            }
        } catch (error) {
            console.error(`Ошибка обработки сообщения: ${error.message}`);
        }
    }

    onError(error) {
        console.error(`Ошибка WebSocket: ${error.message}, код: ${error.code || 'неизвестно'}`);
        this.onClose();
    }

    onClose() {
        console.log('Соединение закрыто');
        if (!this.shutdownFlag && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Попытка переподключения ${this.reconnectAttempts}/${this.maxReconnectAttempts} через ${this.baseReconnectDelay}ms...`);
            this.restart();
        } else if (!this.shutdownFlag) {
            console.error('Достигнут лимит попыток переподключения. Инициируется завершение работы...');
            this.shutdown();
        }
    }

    onOpen() {
        console.log(`Соединение открыто. Отслеживание крупных сделок для: ${this.symbols.join(', ')}`);
        this.reconnectAttempts = 0;
    }

    async shutdown() {
        if (this.shutdownFlag) {
            return;
        }
        console.log('Завершение работы...');
        this.shutdownFlag = true;
        if (this.ws && this.ws.readyState !== WebSocket.CLOSED) {
            // Очистка всех обработчиков
            this.ws.removeAllListeners();
            await new Promise(resolve => {
                this.ws.on('close', resolve);
                this.ws.close();
            });
            this.ws = null;
        }
        process.exit(0);
    }

    run() {
        if (this.shutdownFlag || this.symbols.length === 0 && this.symbolQueue.length === 0) {
            console.log('Подключение отменено: завершение или пустой список символов');
            return;
        }
        if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CLOSING)) {
            console.log('Подключение уже активно, в процессе или закрывается');
            return;
        }
        setTimeout(() => {
            try {
                this.updateSocketUrl();
                this.ws = new WebSocket(this.socketUrl);
                this.ws.on('open', this.onOpen.bind(this));
                this.ws.on('message', this.onMessage.bind(this));
                this.ws.on('error', this.onError.bind(this));
                this.ws.on('close', this.onClose.bind(this));
            } catch (error) {
                console.error(`Ошибка при создании WebSocket: ${error.message}, код: ${error.code || 'неизвестно'}`);
                this.onClose();
            }
        }, 500); // Задержка 500 мс перед созданием WebSocket
    }
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

if (process.argv[1] === __filename) {
    const indicator = new BinanceSpotLargeTrades();

    setTimeout(async () => {
        await indicator.addSymbol('btcusdt');
    }, 8000);

    setTimeout(async () => {
        await indicator.addSymbol('ethusdt');
    }, 16000);

    setTimeout(async () => {
        await indicator.addSymbol('bnbusdt');
    }, 24000);

    setTimeout(async () => {
        await indicator.addSymbol('adausdt');
    }, 32000);

    setTimeout(async () => {
        await indicator.addSymbol('xyzusdt');
    }, 40000);

    process.on('SIGINT', async () => {
        console.log('\nПолучен сигнал SIGINT (Ctrl+C). Завершаем работу...');
        if (typeof indicator.shutdown === 'function') {
            await indicator.shutdown();
        } else {
            console.error('Ошибка: shutdown не является функцией');
            process.exit(1);
        }
    });
}

export default BinanceSpotLargeTrades;