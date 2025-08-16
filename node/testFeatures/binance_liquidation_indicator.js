import WebSocket from 'ws';
import { fileURLToPath } from 'url';
import { dirname } from 'path';
//import fs from 'fs/promises';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

class BinanceLiquidationIndicator {
    constructor() {
        this.socketUrl = 'wss://fstream.binance.com/ws/!forceOrder@arr';
        this.data = [];
        this.ws = null;
    }

    onMessage(message) {
        try {
            const msg = JSON.parse(message);
            if (msg.e === 'forceOrder') {
                const order = msg.o;
                const liquidation = {
                    symbol: order.s,
                    side: order.S,
                    orderType: order.o,
                    quantity: parseFloat(order.q),
                    price: parseFloat(order.p),
                    averagePrice: parseFloat(order.ap),
                    amountUSD: parseFloat(order.q) * parseFloat(order.ap),
                    timestamp: new Date(order.T).toISOString().replace('T', ' ').slice(0, 19),
                    status: order.X
                };
                this.data.push(liquidation);
                this.printLiquidation(liquidation);
            }
        } catch (error) {
            console.error(`Ошибка обработки сообщения: ${error.message}`);
        }
    }

    printLiquidation(liq) {
        const direction = liq.side === 'BUY' ? 'Shorts liquidated' : 'Longs liquidated';
        console.log(`📊 Ликвидация: ${liq.symbol}`);
        console.log(`Сторона: ${liq.side} (${direction})`);
        console.log(`Объем: ${liq.quantity.toFixed(4)}`);
        console.log(`Цена: ${liq.price.toFixed(2)} USD`);
        console.log(`Сумма: ${liq.amountUSD.toFixed(2)} USD`);
        console.log(`Время: ${liq.timestamp}`);
        console.log('-'.repeat(50));
    }

    getData() {
        return this.data;
    }

    onError(error) {
        console.error(`Ошибка: ${error.message}`);
    }

    onClose() {
        console.log('Соединение закрыто');
    }

    onOpen() {
        console.log('Соединение открыто. Отслеживание ликвидаций...');
    }

    async shutdown() {
        console.log('Завершение работы...');
        // Сохранение данных в файл перед завершением
        try {
            //await fs.writeFile('liquidations.json', JSON.stringify(this.data, null, 2));
            console.log('Данные сохранены в liquidations.json');
        } catch (error) {
            console.error(`Ошибка сохранения данных: ${error.message}`);
        }
        // Закрытие WebSocket
        if (this.ws) {
            this.ws.close();
        }
        process.exit(0);
    }

    run() {
        this.ws = new WebSocket(this.socketUrl);
        this.ws.on('open', () => this.onOpen());
        this.ws.on('message', (data) => this.onMessage(data));
        this.ws.on('error', (error) => this.onError(error));
        this.ws.on('close', () => this.onClose());
    }
}


if (process.argv[1] === __filename) {
    const indicator = new BinanceLiquidationIndicator();
    indicator.run();

    // Обработка SIGINT (Ctrl+C)
    process.on('SIGINT', async () => {
        console.log('\nПолучен сигнал SIGINT (Ctrl+C). Завершаем работу...');
        await indicator.shutdown();
    });
}

export default BinanceLiquidationIndicator;