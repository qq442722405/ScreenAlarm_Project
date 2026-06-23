import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem,
    QMessageBox
)
from monitor import MonitorThread


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ScreenAlarm V2")
        self.resize(900, 600)

        self.monitor = None
        self.alarm_state = False

        self.region = None

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        self.status = QLabel("状态：未启动")
        layout.addWidget(self.status)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["当前值", "下限", "上限", "状态"]
        )
        layout.addWidget(self.table)

        self.btn_set = QPushButton("设置监控区域(先运行框选)")
        self.btn_start = QPushButton("开始监控")
        self.btn_stop = QPushButton("停止监控")
        self.btn_clear = QPushButton("消除报警")

        layout.addWidget(self.btn_set)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_clear)

        self.btn_set.clicked.connect(self.set_region)
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_clear.clicked.connect(self.clear_alarm)

        # 默认测试数据
        self.low = 5.0
        self.high = 10.0

    def set_region(self):
        from selector import ScreenSelector

        self.selector = ScreenSelector()
        self.selector.area_selected.connect(self.save_region)
        self.selector.show()

    def save_region(self, x, y, w, h):
        self.region = (x, y, w, h)
        self.status.setText(f"区域：{self.region}")

    def start(self):

        if not self.region:
            QMessageBox.warning(self, "提示", "请先选择区域")
            return

        self.monitor = MonitorThread(self.region, self.low, self.high)
        self.monitor.update_signal.connect(self.update_value)
        self.monitor.alarm_signal.connect(self.alarm)
        self.monitor.start()

        self.status.setText("状态：监控中")

    def stop(self):

        if self.monitor:
            self.monitor.running = False

        self.status.setText("状态：已停止")

    def clear_alarm(self):
        self.alarm_state = False
        self.status.setText("状态：报警已清除")

    def update_value(self, value):

        self.table.setRowCount(1)

        self.table.setItem(0, 0, QTableWidgetItem(str(value)))
        self.table.setItem(0, 1, QTableWidgetItem(str(self.low)))
        self.table.setItem(0, 2, QTableWidgetItem(str(self.high)))

        if not self.alarm_state:
            self.table.setItem(0, 3, QTableWidgetItem("正常"))

    def alarm(self, value, msg):

        self.alarm_state = True

        self.table.setItem(0, 3, QTableWidgetItem(msg))

        self.status.setText(f"报警：{msg} 值={value}")

        QMessageBox.warning(self, "报警", f"{msg}\n当前值：{value}")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    win = MainWindow()
    win.show()

    sys.exit(app.exec())
