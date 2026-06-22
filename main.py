```python
import sys

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QLabel,
    QMessageBox,
    QInputDialog,
    QAbstractItemView
)

from PySide6.QtCore import Qt


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("ScreenAlarm Pro")
        self.resize(1000, 650)

        self.monitoring = False

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        title = QLabel("工业屏幕OCR报警系统")
        title.setAlignment(Qt.AlignCenter)
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

        self.table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()

        self.btn_add = QPushButton("添加监控点")
        btn_layout.addWidget(self.btn_add)

        self.btn_delete = QPushButton("删除监控点")
        btn_layout.addWidget(self.btn_delete)

        self.btn_start = QPushButton("开始监控")
        btn_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止监控")
        btn_layout.addWidget(self.btn_stop)

        layout.addLayout(btn_layout)

        self.status_label = QLabel("状态：未启动")
        layout.addWidget(self.status_label)

        self.btn_add.clicked.connect(
            self.add_monitor_point
        )

        self.btn_delete.clicked.connect(
            self.delete_monitor_point
        )

        self.btn_start.clicked.connect(
            self.start_monitor
        )

        self.btn_stop.clicked.connect(
            self.stop_monitor
        )

    def add_monitor_point(self):

        name, ok = QInputDialog.getText(
            self,
            "添加监控点",
            "请输入监控点名称："
        )

        if not ok:
            return

        name = name.strip()

        if not name:
            return

        low, ok = QInputDialog.getDouble(
            self,
            "下限",
            "请输入下限值：",
            0.0
        )

        if not ok:
            return

        high, ok = QInputDialog.getDouble(
            self,
            "上限",
            "请输入上限值：",
            100.0
        )

        if not ok:
            return

        row = self.table.rowCount()

        self.table.insertRow(row)

        self.table.setItem(
            row,
            0,
            QTableWidgetItem(name)
        )

        self.table.setItem(
            row,
            1,
            QTableWidgetItem("0.00")
        )

        self.table.setItem(
            row,
            2,
            QTableWidgetItem(str(low))
        )

        self.table.setItem(
            row,
            3,
            QTableWidgetItem(str(high))
        )

        self.table.setItem(
            row,
            4,
            QTableWidgetItem("未监控")
        )

        self.status_label.setText(
            f"状态：已添加监控点 [{name}]"
        )

    def delete_monitor_point(self):

        row = self.table.currentRow()

        if row < 0:
            QMessageBox.warning(
                self,
                "提示",
                "请先选择一行"
            )
            return

        self.table.removeRow(row)

        self.status_label.setText(
            "状态：监控点已删除"
        )

    def start_monitor(self):

        if self.monitoring:
            return

        if self.table.rowCount() == 0:
            QMessageBox.warning(
                self,
                "提示",
                "请先添加监控点"
            )
            return

        self.monitoring = True

        self.status_label.setText(
            "状态：监控运行中"
        )

        QMessageBox.information(
            self,
            "提示",
            "监控已启动\n\n下一版本接入OCR识别"
        )

    def stop_monitor(self):

        self.monitoring = False

        self.status_label.setText(
            "状态：监控已停止"
        )

        QMessageBox.information(
            self,
            "提示",
            "监控已停止"
        )


if __name__ == "__main__":

    app = QApplication(sys.argv)

    win = MainWindow()
    win.show()

    sys.exit(app.exec())
```
