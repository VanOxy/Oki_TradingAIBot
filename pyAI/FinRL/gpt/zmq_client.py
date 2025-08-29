import zmq
import time
import pandas as pd
from finrl.meta.env_stock_trading.env_stocktrading import StockTradingEnv
from datetime import datetime

context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://localhost:5555")
socket.setsockopt_string(zmq.SUBSCRIBE, "")

print("Клиент запущен. Ожидание цен с DQN...")
time.sleep(1)

# Создаём минимальный DataFrame с датой как индексом
current_date = datetime.now().strftime('%Y-%m-%d')
initial_data = pd.DataFrame({
    "date": [current_date],
    "tic": ["BTC-USD"],
    "close": [10000]
})
env = StockTradingEnv(df=initial_data, stock_dim=1, num_stock_shares=[0],
                      hmax=1000, initial_amount=10000,
                      buy_cost_pct=0.001, sell_cost_pct=0.001,
                      reward_scaling=1e-4, state_space=4,
                      action_space=3, tech_indicator_list=[])

while True:
    message = socket.recv_string()
    print(f"Получено: {message}")
    price = float(message.split(": ")[1])
    # Обновляем состояние
    state = [price, price * 0.95, price * 1.05, 10000]  # [цена, мин, макс, капитал]
    action = env.get_random_action()  # Случайное действие
    if action == 1:
        print(f"Решение DQN: Купить! Цена: {price:.2f}")
    elif action == 2:
        print(f"Решение DQN: Продать! Цена: {price:.2f}")
    else:
        print(f"Решение DQN: Держать. Цена: {price:.2f}")