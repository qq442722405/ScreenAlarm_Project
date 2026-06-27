import sys
import json
import os
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QCheckBox, QHeaderView
)
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen
from monitor import MonitorThread

class TrendChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.data = []
    
    def set_data(self, data_list):
        self.data = data_list[-50:] # 显示最近50个点
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#252538"))
        painter.drawRoundedRect(self.rect(), 8, 8)
        if not self.data: return
        
        painter.setPen(QPen(QColor("#4a9eff"), 2))
        h, w = self.height(), self.width()
        max_v, min_v = max(self.data), min(self.data)
        range_v = (max_v - min_v) if max_v != min_v else 1
        
        points = []
        for i, val in enumerate(self.data):
            x = 40 + i * ((w - 80) / len(self.data))
            y = h - 40 - ((val - min_v) / range_v * (h - 80))
            points.append((x, y))
        
        for i in range(len(points)-1):
            painter.drawLine(points[i][0], points[i][1], points[i+1][0], points[i+1][1])
            
        painter.setPen(Qt.white)
        painter.drawText(int(points[-1][0]), int(points[-1][1])-10, f"{self.data[-1]:.2f}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("---天长污水陈诚")
        self.resize(1300, 800)
        self.value_history = {} 
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        layout.addWidget(QLabel("---天长污水陈诚", font=QFont("Arial", 16, QFont.Bold)))
        
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "值", "下限", "上限", "坐标", "状态", "时间", "静音", "备注"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        
        btn_layout = QHBoxLayout()
        self.btn_clear = QPushButton("🧹 清空数据")
        self.btn_clear.clicked.connect(self._on_clear_clicked)
        self.btn_add = QPushButton("➕ 添加监控")
        self.btn_save = QPushButton("💾 保存配置")
        self.btn_start = QPushButton("▶ 开始监控")
        self.btn_stop = QPushButton("⏹ 停止监控")
        
        for btn in [self.btn_clear, self.btn_add, self.btn_save, self.btn_start, self.btn_stop]:
            btn_layout.addWidget(btn)
        layout.addLayout(btn_layout)
        
        self.trend = TrendChartWidget()
        layout.addWidget(self.trend)

    def _on_clear_clicked(self):
        self.table.setRowCount(0)
        self.value_history.clear()

    def add_row(self, name="新监控", lower=0, upper=100, coord="0,0,100,50", remark=""):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        # 优化 CheckBox 尺寸
        for col in [0, 8]:
            cb = QCheckBox()
            cb.setStyleSheet("QCheckBox::indicator { width: 16px; height: 16px; }")
            container = QWidget()
            l = QHBoxLayout(container)
            l.addWidget(cb)
            l.setAlignment(Qt.AlignCenter)
            l.setContentsMargins(0,0,0,0)
            self.table.setCellWidget(row, col, container)
        
        self.table.setItem(row, 1, QTableWidgetItem(name))
        self.table.setItem(row, 2, QTableWidgetItem("--"))
        self.table.setItem(row, 3, QTableWidgetItem(str(lower)))
        self.table.setItem(row, 4, QTableWidgetItem(str(upper)))
        self.table.setItem(row, 5, QTableWidgetItem(coord))
        self.table.setItem(row, 9, QTableWidgetItem(remark)) # 备注列

    def save_config(self):
        data = []
        for r in range(self.table.rowCount()):
            data.append({
                "name": self.table.item(r, 1).text(),
                "lower": self.table.item(r, 3).text(),
                "upper": self.table.item(r, 4).text(),
                "coord": self.table.item(r, 5).text(),
                "remark": self.table.item(r, 9).text()
            })
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def load_config(self):
        if not os.path.exists("config.json"): return
        with open("config.json", "r", encoding="utf-8") as f:
            for item in json.load(f):
                self.add_row(item['name'], item['lower'], item['upper'], item['coord'], item['remark'])

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
