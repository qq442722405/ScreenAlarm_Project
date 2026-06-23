import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QMessageBox
)
from PySide6.QtGui import QIcon
from selector import ScreenSelector
from monitor import Monitor


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ScreenAlarm V4 Industrial")
        self.resize(1000, 650)

        # ✔ 图标（可换ico）
        self.setWindowIcon(QIcon("icon.ico"))

        self.monitors = []

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        self.label = QLabel("状态：未启动")
        layout.addWidget(self.label)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["区域", "当前值", "下限", "上限", "状态"]
        )
        layout.addWidget(self.table)

        self.btn_add = QPushButton("➕ 添加监控点")
        self.btn_start = QPushButton("▶ 启动监控")
        self.btn_stop = QPushButton("⏹ 停止全部")
        self.btn_clear = QPushButton("✔ 清除报警")

        layout.addWidget(self.btn_add)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_clear)

        self.btn_add.clicked.connect(self.add_region)
        self.btn_start.clicked.connect(self.start_all)
        self.btn_stop.clicked.connect(self.stop_all)
        self.btn_clear.clicked.connect(self.clear)

        self.low = 5
        self.high = 10

    def add_region(self):

        selector = ScreenSelector()

        while selector.isVisible():
            QApplication.processEvents()

        if selector.result:
            self.monitors.append({
                "region": selector.result,
                "value": 0,
                "status": "待启动"
            })

            self.refresh_table()

    def start_all(self):

        for i, m in enumerate(self.monitors):

            monitor = Monitor(
                m["region"],
                self.low,
                self.high,
                self,
                i
            )

            monitor.start()

            m["thread"] = monitor

        self.label.setText("运行中")

    def stop_all(self):

        for m in self.monitors:
            if "thread" in m:
                m["thread"].running = False

        self.label.setText("已停止")

    def clear(self):
        self.label.setText("报警已清除")

    def refresh_table(self):

        self.table.setRowCount(len(self.monitors))

        for i, m in enumerate(self.monitors):

            r = m["region"]

            self.table.setItem(i, 0, QTableWidgetItem(str(r)))
            self.table.setItem(i, 1, QTableWidgetItem(str(m.get("value", 0))))
            self.table.setItem(i, 2, QTableWidgetItem(str(self.low)))
            self.table.setItem(i, 3, QTableWidgetItem(str(self.high)))
            self.table.setItem(i, 4, QTableWidgetItem(m.get("status", "")))

    def update_value(self, index, value, status):

        if index < len(self.monitors):

            self.monitors[index]["value"] = value
            self.monitors[index]["status"] = status

            self.refresh_table()

            if value > self.high or value < self.low:
                QMessageBox.warning(self, "报警", f"{value}")
