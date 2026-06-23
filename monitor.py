import threading
import time
import mss
from ocr import read_number
import datetime


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

                if value is not None:

                    self.ui.update_value(value)

                    if value > self.high or value < self.low:

                        self.ui.alarm_trigger(value)

                        self.log(value)

                time.sleep(1)

    def log(self, value):

        with open("alarm_log.csv", "a", encoding="utf-8") as f:

            f.write(
                f"{datetime.datetime.now()},{value}\n"
            )
