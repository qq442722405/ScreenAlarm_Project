import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton, QLabel,
    QMessageBox, QTableWidget, QTableWidgetItem
)
from monitor import Monitor


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ScreenAlarm V3")
        self.resize(900, 600)

        self.region = None
        self.monitor = None
        self.alarm = False

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        self.label = QLabel("状态：未设置区域")
        layout.addWidget(self.label)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["当前值", "下限", "上限"])
        layout.addWidget(self.table)

        self.btn_region = QPushButton("选择监控区域")
        self.btn_start = QPushButton("开始监控")
        self.btn_stop = QPushButton("停止监控")
        self.btn_clear = QPushButton("消除报警")

        layout.addWidget(self.btn_region)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_clear)

        self.btn_region.clicked.connect(self.select_region)
        self.btn_start.clicked.connect(self.start)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_clear.clicked.connect(self.clear_alarm)

        self.low = 5
        self.high = 10

    def select_region(self):

        from selector import ScreenSelector

        self.selector = ScreenSelector()

        while self.selector.isVisible():
            QApplication.processEvents()

        self.region = self.selector.result

        if self.region:
            self.label.setText(f"区域：{self.region}")

    def start(self):

        if not self.region:
            QMessageBox.warning(self, "提示", "请先选择区域")
            return

        self.monitor = Monitor(self.region, self.low, self.high, self)
        self.monitor.start()

        self.label.setText("状态：监控中")

    def stop(self):

        if self.monitor:
            self.monitor.running = False

        self.label.setText("状态：已停止")

    def clear_alarm(self):
        self.alarm = False
        self.label.setText("状态：报警已清除")

    def update_value(self, value):

        self.table.setRowCount(1)

        self.table.setItem(0, 0, QTableWidgetItem(str(value)))
        self.table.setItem(0, 1, QTableWidgetItem(str(self.low)))
        self.table.setItem(0, 2, QTableWidgetItem(str(self.high)))

        if value > self.high or value < self.low:
            self.table.setItem(0, 0, QTableWidgetItem(f"⚠ {value}"))

    def alarm_trigger(self, value):

        self.alarm = True

        QMessageBox.warning(self, "报警", f"数值异常：{value}")
