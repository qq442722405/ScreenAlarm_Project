import threading
import time
import mss
from ocr import read_number


class Monitor(threading.Thread):

    def __init__(self, region, low, high, ui):
        super().__init__()

        self.x, self.y, self.w, self.h = region
        self.low = low
        self.high = high
        self.ui = ui

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

                img = sct.grab(monitor)

                value = read_number(img)

                # ✔ 关键：过滤None
                if value is None:
                    time.sleep(1)
                    continue

                # UI更新（安全调用）
                try:
                    self.ui.update_value(value)
                except:
                    pass

                if value > self.high or value < self.low:
                    try:
                        self.ui.alarm_trigger(value)
                    except:
                        pass

                time.sleep(1)
