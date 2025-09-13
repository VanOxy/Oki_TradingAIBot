# быстрый тест, что тик бежит
from time import sleep
from stream_buffer import Buffers
buf = Buffers(attach_endpoint="tcp://127.0.0.1:5555")
last = None
while True:
    buf.pump(timeout_ms=200, max_msgs=1000)
    ts = buf.last_kline_ts("HUMAUSDT")
    if ts and ts != last:
        print("new kline ts:", ts)
        last = ts
    sleep(3)