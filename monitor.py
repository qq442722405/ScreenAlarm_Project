import threading
import time
import random


class Monitor(threading.Thread):

    def __init__(self, region, low, high, ui, index):

        super().__init__()

        self.region = region
        self.low = low
        self.high = high
        self.ui = ui
        self.index = index

        self.running = True

    def run(self):

        while self.running:

            # =========================
            # 模拟工业数值（真实OCR后替换这里）
            # =========================
            value = random.uniform(0, 20)

            status = "正常"

            if value > self.high or value < self.low:
                status = "报警"

            self.ui.update_value(self.index, value, status)

            time.sleep(1)
