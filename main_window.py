from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QLabel, QTableWidget,
    QTableWidgetItem, QMessageBox
)

from selector import ScreenSelector
from monitor import Monitor


class MainWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.setWindowTitle("ScreenAlarm V4.1 Industrial")
        self.resize(1000, 650)

        self.region_list = []

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        self.label = QLabel("状态：未启动")
        layout.addWidget(self.label)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["区域", "值", "下限", "上限"])
        layout.addWidget(self.table)

        self.btn_add = QPushButton("➕ 添加监控区域")
        self.btn_start = QPushButton("▶ 启动监控")
        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_clear = QPushButton("✔ 清除报警")

        layout.addWidget(self.btn_add)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_clear)

        self.btn_add.clicked.connect(self.add_region)
        self.btn_start.clicked.connect(self.start_all)
        self.btn_stop.clicked.connect(self.stop_all)

        self.low = 5
        self.high = 10

    # =========================
    # 添加区域（关键修复）
    # =========================
    def add_region(self):

        selector = ScreenSelector()
        selector.show()

        # ✔ 不用 while卡死（EXE崩溃源头）
        selector.exec_ = None

        # 等待关闭（安全方式）
        while selector.isVisible():
            QApplication.processEvents()

        if selector.result:

            self.region_list.append({
                "region": selector.result,
                "value": 0,
                "thread": None
            })

            self.refresh()

    # =========================
    # 启动
    # =========================
    def start_all(self):

        for i, r in enumerate(self.region_list):

            if r["thread"]:
                continue

            t = Monitor(r["region"], self.low, self.high, self, i)
            t.start()

            r["thread"] = t

        self.label.setText("运行中")

    # =========================
    # 停止
    # =========================
    def stop_all(self):

        for r in self.region_list:
            if r["thread"]:
                r["thread"].running = False

        self.label.setText("已停止")

    # =========================
    # UI刷新
    # =========================
    def refresh(self):

        self.table.setRowCount(len(self.region_list))

        for i, r in enumerate(self.region_list):

            self.table.setItem(i, 0, QTableWidgetItem(str(r["region"])))
            self.table.setItem(i, 1, QTableWidgetItem(str(r.get("value", 0))))
            self.table.setItem(i, 2, QTableWidgetItem(str(self.low)))
            self.table.setItem(i, 3, QTableWidgetItem(str(self.high)))

    # =========================
    # 更新值
    # =========================
    def update_value(self, index, value):

        if index < len(self.region_list):

            self.region_list[index]["value"] = value

            self.refresh()

            if value > self.high or value < self.low:
                self.label.setText(f"⚠ 报警：{value}")

                QMessageBox.warning(self, "报警", str(value))
