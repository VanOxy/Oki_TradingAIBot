import 'dotenv/config';
import zmq from 'zeromq';

class ZMQClient {
  constructor(addr) {
    this.addr = addr || process.env.AI_ZMQ_ADDR || "tcp://127.0.0.1:5555";
    this.sock = new zmq.Request();
    this.connected = false;
    this._chain = Promise.resolve(); // очередь
  }

  async connect() {
    if (this.connected) return;
    await this.sock.connect(this.addr);
    this.connected = true;
    console.log("🔗 ZMQ connected:", this.addr);
  }

  async send(payload) {
    if (!this.connected) await this.connect();
    this._chain = this._chain.then(async () => {
      await this.sock.send(JSON.stringify(payload));
      const [reply] = await this.sock.receive();
      const text =  Buffer.from(reply).toString();
      try { return JSON.parse(text); } catch { return { error: "Invalid JSON from server", raw: text }; }
    });
    return this._chain;
  }

  //   const data = {
  //     token: token,
  //     exchange: exchange,
  //     openInterest: openInterest,
  //     volume: volume,
  //     trades8h: trades8h,
  //     oiChange4h: oiChange4h,
  //     coinChange24h: coinChange24h,
  //     tradesCount8h: tradesCount8h,
  // };
  async sendTgData(data) {
    return this.send({ type: 'tg', ...data });
  }

  // describe data structure here --> later
  async sendMarket(data) {
    return this.send({ type: 'bnn_market', ...data });
  }
}

export default new ZMQClient();
