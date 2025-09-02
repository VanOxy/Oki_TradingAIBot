ENDPOINT = "tcp://127.0.0.1:5555"

# окна/лимиты
KLINE_WINDOW = 72
TG_WINDOW = 10
MAX_TOKENS = 80

# тайминги ожиданий
STEP_TIMEOUT_SEC = 30          # для mock; в проде поставишь 330-360
POLL_INTERVAL_MS = 100
MAX_PUMP_MSGS = 1000           # максимум сообщений за один pump
