import sys
import json
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QMessageBox,
    QHeaderView, QTableWidgetSelectionRange, QCheckBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QRect
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen, QPainterPath
from monitor import MonitorThread

class TrendChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.data = []
        self.title = "数值趋势"
    
    def set_data(self, data_list, title):
        self.data = data_list[-100:]
        self.title = title
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#252538"))
        painter.drawRoundedRect(self.rect(), 8, 8)
        
        if not self.data: return
        
        # 绘图逻辑简化：绘制曲线并标记最后一个点的数值
        painter.setPen(QPen(QColor("#4a9eff"), 2))
        h, w = self.height(), self.width()
        max_v, min_v = max(self.data), min(self.data)
        range_v = (max_v - min_v) if max_v != min_v else 1
        
        points = []
        for i, val in enumerate(self.data):
            x = i * (w / len(self.data))
            y = h - ((val - min_v) / range_v * (h * 0.7)) - 30
            points.append((x, y))
        
        for i in range(len(points)-1):
            painter.drawLine(points[i][0], points[i][1], points[i+1][0], points[i+1][1])
            
        # 标记最新数值
        painter.setPen(Qt.white)
        painter.drawText(int(points[-1][0]), int(points[-1][1])-10, f"{self.data[-1]:.2f}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("---天长污水陈诚")
        self.resize(1300, 800)
        self.value_history = {} # 持久存储，不再随停止清空
        self.remarks = {}
        self._setup_ui()
        self.load_config()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # 顶部标题
        layout.addWidget(QLabel("---天长污水陈诚", font=QFont("Arial", 16, QFont.Bold)))
        
        # 表格：增加备注列
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "值", "下限", "上限", "坐标", "状态", "时间", "静音", "备注"])
        layout.addWidget(self.table)
        
        # 按钮栏
        btn_layout = QHBoxLayout()
        self.btn_clear = QPushButton("🧹 清空数据")
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        self.btn_add = QPushButton("➕ 添加监控")
        self.btn_start = QPushButton("▶ 开始")
        self.btn_stop = QPushButton("⏹ 停止")
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_add)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        layout.addLayout(btn_layout)
        
        self.trend = TrendChartWidget()
        layout.addWidget(self.trend)

    def _on_clear_clicked(self):
        self.table.setRowCount(0)
        self.value_history.clear()
        self.remarks.clear()

    # 此处省略逻辑：在 add_monitor_row 时创建 CheckBox
    def create_small_checkbox(self):
        cb = QCheckBox()
        cb.setFixedSize(30, 30) # 缩小尺寸
        return cb

    def save_config(self):
        # 遍历 table 获取数据，包含备注列
        config = []
        for r in range(self.table.rowCount()):
            config.append({
                "name": self.table.item(r, 1).text(),
                "remark": self.table.item(r, 9).text() if self.table.item(r, 9) else ""
            })
        with open("config.json", "w") as f:
            json.dump(config, f)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
