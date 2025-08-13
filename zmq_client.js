import 'dotenv/config';
import zmq from 'zeromq';

class ZMQClient {
  constructor(addr) {
    this.addr = addr || process.env.AI_ZMQ_ADDR || "tcp://127.0.0.1:5555";
    this.sock = new zmq.Request();
    this.connected = false;
  }

  async connect() {
    if (this.connected) return;
    await this.sock.connect(this.addr);
    this.connected = true;
    console.log("🔗 ZMQ connected:", this.addr);
  }

  async send(payload) {
    if (!this.connected) await this.connect();
    await this.sock.send(JSON.stringify(payload));
    const [reply] = await this.sock.receive();
    const text = reply.toString();
    try {
      return JSON.parse(text);
    } catch {
      return { error: "Invalid JSON from server", raw: text };
    }
  }

  async sendTgData(symbol, features) {
    return this.send({ type: "trigger", symbol, features });
  }

  async sendMarket(symbol, features) {
    return this.send({ type: "market", symbol, features });
  }
}

const client = new ZMQClient();
export default client;
