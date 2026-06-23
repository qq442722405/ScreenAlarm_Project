import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QPushButton, QLabel,
    QMessageBox
)
from PySide6.QtCore import Qt
from selector import ScreenSelector


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ScreenAlarm V2")
        self.resize(800, 400)

        self.region = None

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        self.label = QLabel("未选择区域")
        layout.addWidget(self.label)

        self.btn = QPushButton("选择监控区域")
        self.btn.clicked.connect(self.select_region)
        layout.addWidget(self.btn)

    def select_region(self):

        # ⭐关键：直接阻塞执行，不用signal
        self.selector = ScreenSelector()
        self.selector.show()

        # 等待窗口关闭
        self.selector.raise_()
        self.selector.activateWindow()

        # 等待关闭
        while self.selector.isVisible():
            QApplication.processEvents()

        # 获取结果
        if self.selector.result:

            self.region = self.selector.result

            x, y, w, h = self.region

            self.label.setText(f"区域: {x},{y},{w},{h}")

            QMessageBox.information(
                self,
                "成功",
                f"已设置区域\n{x},{y},{w},{h}"
            )

        else:
            QMessageBox.warning(
                self,
                "取消",
                "未选择区域"
            )


if __name__ == "__main__":

    app = QApplication(sys.argv)

    win = MainWindow()
    win.show()

    sys.exit(app.exec())
