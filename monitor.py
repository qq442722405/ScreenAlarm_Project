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

            # ✔ 先用模拟数据（保证程序稳定）
            value = round(random.uniform(0, 20), 2)

            self.ui.update_value(self.index, value)

            time.sleep(1)
