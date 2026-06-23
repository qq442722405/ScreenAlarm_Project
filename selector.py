import threading
import time
from mss import mss
from PySide6.QtCore import Signal, QObject
from ocr import read_number
import datetime


class MonitorThread(threading.Thread):

    update_signal = Signal(float)
    alarm_signal = Signal(float, str)

    def __init__(self, region, low, high):
        super().__init__()

        self.x, self.y, self.w, self.h = region
        self.low = low
        self.high = high
        self.running = True

        self.last_value = None

    def run(self):

        with mss() as sct:

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

                    self.update_signal.emit(value)

                    # 报警逻辑
                    if value > self.high:
                        self.log(value, "高报警")
                        self.alarm_signal.emit(value, "高报警")

                    elif value < self.low:
                        self.log(value, "低报警")
                        self.alarm_signal.emit(value, "低报警")

                time.sleep(1)

    def log(self, value, status):

        with open("alarm_log.csv", "a", encoding="utf-8") as f:

            f.write(
                f"{datetime.datetime.now()},{value},{status}\n"
            )
