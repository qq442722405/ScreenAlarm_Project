import threading
import time
import mss


class Monitor(threading.Thread):

    def __init__(self, region, low, high, ui, index):

        super().__init__()

        self.x, self.y, self.w, self.h = region
        self.low = low
        self.high = high
        self.ui = ui
        self.index = index

        self.running = True

    def run(self):

        with mss.mss() as sct:

            monitor = {
                "left": self.x,
                "top": self.y,
                "width": self.w,
                "height": self.h
            }

            while self.running:

                # ✔ 这里先模拟（避免OCR错误影响结构）
                value = self.mock_value()

                status = "正常"

                if value > self.high or value < self.low:
                    status = "报警"
                    self.ui.update_value(self.index, value, status)
                else:
                    self.ui.update_value(self.index, value, status)

                time.sleep(1)

    def mock_value(self):
        import random
        return round(random.uniform(0, 20), 2)
