import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem,
    QInputDialog, QTextEdit, QMessageBox
)

from monitor import Monitor


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ScreenAlarm V6 工业稳定版")
        self.resize(1100, 750)

        self.monitors = []

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        # 状态
        self.status = QLabel("状态：未启动")
        layout.addWidget(self.status)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "区域", "备注", "当前值", "下限", "上限", "状态"
        ])
        layout.addWidget(self.table)

        # 日志
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)

        # 按钮
        self.btn_add = QPushButton("➕ 添加监控（一次性输入）")
        self.btn_start = QPushButton("▶ 开始监控")
        self.btn_stop = QPushButton("⏹ 停止监控")
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
    # 一次性输入（重点）
    # =========================
    def add_region(self):

        x1, ok1 = QInputDialog.getInt(self, "输入", "左上X")
        y1, ok2 = QInputDialog.getInt(self, "输入", "左上Y")
        x2, ok3 = QInputDialog.getInt(self, "输入", "右下X")
        y2, ok4 = QInputDialog.getInt(self, "输入", "右下Y")

        if not (ok1 and ok2 and ok3 and ok4):
            return

        low, ok5 = QInputDialog.getDouble(self, "下限", "报警下限", 5)
        high, ok6 = QInputDialog.getDouble(self, "上限", "报警上限", 10)

        if not (ok5 and ok6):
            return

        text, ok7 = QInputDialog.getText(self, "备注", "输入备注（如：压力/流量/温度）")

        if not ok7:
            text = ""

        region = (x1, y1, x2 - x1, y2 - y1)

        self.monitors.append({
            "region": region,
            "low": low,
            "high": high,
            "remark": text,
            "value": 0,
            "status": "正常",
            "thread": None,
            "last_value": None  # ✔ 用于稳定滤波
        })

        self.refresh_table()

    # =========================
    # 启动监控
    # =========================
    def start_monitor(self):

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

        self.status.setText("状态：运行中")

    # =========================
    # 停止
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
    # UI更新（带滤波）
    # =========================
    def update_value(self, index, value, status):

        if index >= len(self.monitors):
            return

        m = self.monitors[index]

        # =========================
        # ✔ 滤波（解决跳数）
        # =========================
        if m["last_value"] is None:
            m["last_value"] = value
        else:
            value = (m["last_value"] * 0.7) + (value * 0.3)
            m["last_value"] = value

        m["value"] = round(value, 2)
        m["status"] = status

        # 日志
        if status == "报警":
            self.log_box.append(f"⚠ {m['remark']} 区域{index} 值={m['value']}")

        self.refresh_table()

    # =========================
    # 表格刷新
    # =========================
    def refresh_table(self):

        self.table.setRowCount(len(self.monitors))

        for i, m in enumerate(self.monitors):

            self.table.setItem(i, 0, QTableWidgetItem(str(m["region"])))
            self.table.setItem(i, 1, QTableWidgetItem(m["remark"]))
            self.table.setItem(i, 2, QTableWidgetItem(str(m["value"])))
            self.table.setItem(i, 3, QTableWidgetItem(str(m["low"])))
            self.table.setItem(i, 4, QTableWidgetItem(str(m["high"])))
            self.table.setItem(i, 5, QTableWidgetItem(m["status"]))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
