import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem,
    QTextEdit, QMessageBox, QInputDialog
)

from selector import ScreenSelector
from monitor import Monitor


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("工业屏幕监控系统 V1")
        self.resize(1000, 700)

        self.monitors = []

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        # 状态
        self.status = QLabel("状态：未启动")
        layout.addWidget(self.status)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["区域", "当前值", "下限", "上限", "状态"]
        )
        layout.addWidget(self.table)

        # 日志框
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        # 按钮
        self.btn_add = QPushButton("➕ 添加监视区域")
        self.btn_start = QPushButton("▶ 开始监视")
        self.btn_stop = QPushButton("⏹ 停止监视")
        self.btn_clear = QPushButton("✔ 清除报警")

        layout.addWidget(self.btn_add)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_clear)

        self.btn_add.clicked.connect(self.add_region)
        self.btn_start.clicked.connect(self.start_monitor)
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_clear.clicked.connect(self.clear_alarm)

    # =========================
    # 添加监视区域
    # =========================
    def add_region(self):

        selector = ScreenSelector()

        selector.exec()

        if selector.result:

            x, y, w, h = selector.result

            low, ok1 = QInputDialog.getDouble(self, "下限", "输入下限", 5)
            high, ok2 = QInputDialog.getDouble(self, "上限", "输入上限", 10)

            if not ok1 or not ok2:
                return

            self.monitors.append({
                "region": (x, y, w, h),
                "low": low,
                "high": high,
                "value": 0,
                "status": "正常",
                "thread": None
            })

            self.refresh_table()

    # =========================
    # 开始监视
    # =========================
    def start_monitor(self):

        if not self.monitors:
            QMessageBox.warning(self, "提示", "请先添加监视区域")
            return

        for i, m in enumerate(self.monitors):

            if m["thread"] is None:

                t = Monitor(
                    m["region"],
                    m["low"],
                    m["high"],
                    self,
                    i
                )

                m["thread"] = t
                t.start()

        self.status.setText("状态：监视中")

    # =========================
    # 停止监视
    # =========================
    def stop_monitor(self):

        for m in self.monitors:
            if m["thread"]:
                m["thread"].running = False

        self.status.setText("状态：已停止")

    # =========================
    # 清除报警
    # =========================
    def clear_alarm(self):
        self.status.setText("状态：报警已清除")

    # =========================
    # 更新数据（线程调用）
    # =========================
    def update_value(self, index, value, status):

        if index >= len(self.monitors):
            return

        self.monitors[index]["value"] = value
        self.monitors[index]["status"] = status

        self.refresh_table()

        if status == "报警":
            self.log_box.append(f"⚠ 报警 区域{index} 数值={value}")

    # =========================
    # 表格刷新
    # =========================
    def refresh_table(self):

        self.table.setRowCount(len(self.monitors))

        for i, m in enumerate(self.monitors):

            self.table.setItem(i, 0, QTableWidgetItem(str(m["region"])))
            self.table.setItem(i, 1, QTableWidgetItem(str(m["value"])))
            self.table.setItem(i, 2, QTableWidgetItem(str(m["low"])))
            self.table.setItem(i, 3, QTableWidgetItem(str(m["high"])))
            self.table.setItem(i, 4, QTableWidgetItem(str(m["status"])))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
