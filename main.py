import sys

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLabel
)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ScreenAlarm Pro")
        self.resize(900, 600)

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        title = QLabel("工业屏幕OCR报警系统")
        layout.addWidget(title)

        self.table = QTableWidget()
        self.table.setColumnCount(5)

        self.table.setHorizontalHeaderLabels([
            "名称",
            "当前值",
            "下限",
            "上限",
            "状态"
        ])

        layout.addWidget(self.table)

        self.btn_add = QPushButton("添加监控点")
        layout.addWidget(self.btn_add)

        self.btn_start = QPushButton("开始监控")
        layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止监控")
        layout.addWidget(self.btn_stop)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    win = MainWindow()
    win.show()

    sys.exit(app.exec())