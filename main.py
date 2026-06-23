import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton, QLabel,
    QMessageBox, QTableWidget, QTableWidgetItem
)

from selector import ScreenSelector
from monitor import Monitor


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ScreenAlarm Industrial V3.2")
        self.resize(900, 600)

        self.region = None
        self.monitor = None
        self.alarm_state = False

        # ===== UI =====
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        self.label = QLabel("状态：未选择监控区域")
        layout.addWidget(self.label)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["当前值", "下限", "上限"])
        layout.addWidget(self.table)

        # 按钮
        self.btn_select = QPushButton("① 选择监控区域")
        self.btn_start = QPushButton("② 开始监控")
        self.btn_stop = QPushButton("③ 停止监控")
        self.btn_clear = QPushButton("④ 消除报警")

        layout.addWidget(self.btn_select)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_clear)

        # 绑定事件
        self.btn_select.clicked.connect(self.select_region)
        self.btn_start.clicked.connect(self.start_monitor)
        self.btn_stop.clicked.connect(self.stop_monitor)
        self.btn_clear.clicked.connect(self.clear_alarm)

        # 阈值（你可以后面做成UI输入）
        self.low = 5.0
        self.high = 10.0

    # =========================
    # 选择区域
    # =========================
    def select_region(self):

        selector = ScreenSelector()

        # 等待窗口关闭（工业稳定写法）
        while selector.isVisible():
            QApplication.processEvents()

        self.region = selector.result

        if self.region:
            x, y, w, h = self.region
            self.label.setText(f"区域：X={x}, Y={y}, W={w}, H={h}")
        else:
            QMessageBox.warning(self, "提示", "未选择区域")

    # =========================
    # 启动监控
    # =========================
    def start_monitor(self):

        if not self.region:
            QMessageBox.warning(self, "错误", "请先选择监控区域")
            return

        if self.monitor:
            self.monitor.running = False

        self.monitor = Monitor(
            self.region,
            self.low,
            self.high,
            self
        )

        self.monitor.start()

        self.label.setText("状态：监控运行中")

    # =========================
    # 停止监控
    # =========================
    def stop_monitor(self):

        if self.monitor:
            self.monitor.running = False

        self.label.setText("状态：已停止")

    # =========================
    # 清除报警
    # =========================
    def clear_alarm(self):

        self.alarm_state = False
        self.label.setText("状态：报警已清除")

    # =========================
    # UI更新（线程调用）
    # =========================
    def update_value(self, value):

        self.table.setRowCount(1)

        self.table.setItem(0, 0, QTableWidgetItem(str(value)))
        self.table.setItem(0, 1, QTableWidgetItem(str(self.low)))
        self.table.setItem(0, 2, QTableWidgetItem(str(self.high)))

        # 超限高亮
        if value > self.high or value < self.low:
            self.table.item(0, 0).setText(f"⚠ {value}")

    # =========================
    # 报警触发
    # =========================
    def alarm_trigger(self, value):

        if self.alarm_state:
            return

        self.alarm_state = True

        self.label.setText(f"⚠ 报警：{value}")

        # 非阻塞弹窗（避免卡死）
        msg = QMessageBox(self)
        msg.setWindowTitle("报警")
        msg.setText(f"数值异常：{value}")
        msg.setStandardButtons(QMessageBox.Ok)
        msg.show()


# =========================
# 主入口
# =========================
if __name__ == "__main__":

    app = QApplication(sys.argv)

    win = MainWindow()
    win.show()

    sys.exit(app.exec())
