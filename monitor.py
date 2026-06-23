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

            # 模拟工业数值（后续可接OCR）
            value = round(random.uniform(0, 20), 2)

            status = "正常"

            if value > self.high or value < self.low:
                status = "报警"

            self.ui.update_value(self.index, value, status)

            time.sleep(1)
