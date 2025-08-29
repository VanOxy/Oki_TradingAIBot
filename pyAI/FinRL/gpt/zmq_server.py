import zmq
import time
import yfinance as yf

context = zmq.Context()
socket = context.socket(zmq.PUB)
socket.bind("tcp://*:5555")

print("Сервер запущен. Отправка цен BTC-USD...")
stock = yf.Ticker("BTC-USD")
while True:
    data = stock.history(period="1d")
    if not data.empty:
        price = data["Close"].iloc[-1]
        message = f"Price: {price:.2f}"
        socket.send_string(message)
        print(f"Отправлено: {message}")
    time.sleep(30)