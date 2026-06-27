import sys
import json
import os
import time
import re
import threading
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QLabel, QMessageBox,
    QAbstractItemView, QHeaderView, QFileDialog, QDialog,
    QLineEdit, QGroupBox, QFrame, QSlider, QComboBox,
    QProgressBar, QCheckBox
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QPoint, QRect
from PySide6.QtGui import (
    QColor, QBrush, QFont, QPainter, QPen, QPixmap, QImage,
    QPainterPath, QLinearGradient
)
from monitor import MonitorThread

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

# ... (AlarmSoundPlayer 类和 CoordinatePicker 类保持不变，为了节省篇幅请保留原内容) ...

class TrendChartWidget(QWidget):
    """实时数值趋势曲线控件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(190)
        self.data = []
        self.max_points = 150
        self.title = "数值趋势"
    
    def set_data(self, data_list, title="数值趋势"):
        self.data = data_list[-self.max_points:]
        self.title = title
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        rect = self.rect()
        padding_left, padding_right, padding_top, padding_bottom = 55, 20, 32, 28
        
        painter.setBrush(QColor("#252538"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 8, 8)
        
        painter.setPen(QColor("#e8e8f0"))
        painter.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        painter.drawText(padding_left, 22, self.title)
        
        chart_rect = QRect(padding_left, padding_top, rect.width() - padding_left - padding_right, rect.height() - padding_top - padding_bottom)
        
        painter.setPen(QColor("#36364a"))
        for i in range(6):
            y = chart_rect.top() + chart_rect.height() * i / 5
            painter.drawLine(chart_rect.left(), y, chart_rect.right(), y)
        
        if len(self.data) < 2:
            painter.setPen(QColor("#7a7a9a"))
            painter.drawText(chart_rect, Qt.AlignCenter, "暂无数据")
            return
        
        min_val, max_val = min(self.data), max(self.data)
        if min_val == max_val: min_val -= 1; max_val += 1
        val_range = (max_val - min_val) * 1.2
        min_val -= (val_range - (max_val - min_val)) / 2
        
        points = []
        step_x = chart_rect.width() / (len(self.data) - 1)
        for i, val in enumerate(self.data):
            x = chart_rect.left() + i * step_x
            y = chart_rect.bottom() - (val - min_val) / val_range * chart_rect.height()
            points.append(QPoint(x, y))
        
        painter.setPen(QPen(QColor("#4a9eff"), 2))
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i+1])
            painter.drawText(points[i].x(), points[i].y() - 5, f"{self.data[i]:.1f}")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕数字监控报警系统")
        self.resize(1200, 750)
        self.setStyleSheet("QMainWindow { background-color: #1e1e2e; }") # 简化样式表以节省空间
        
        self.monitoring = False
        self.value_history = {}
        self.alarm_player = AlarmSoundPlayer()
        self.row_enabled, self.row_muted, self.row_alarm = {}, {}, {}
        
        self._setup_ui()
        self.load_config()
    
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        # 顶部栏
        title_layout = QHBoxLayout()
        title = QLabel("📊 屏幕数字监控报警系统")
        title.setFont(QFont("Microsoft YaHei", 19, QFont.Bold))
        title_layout.addWidget(title)
        subtitle = QLabel("---天长污水陈诚")
        subtitle.setStyleSheet("color: #7a7a9a; font-size: 13px; font-weight: bold;")
        title_layout.addWidget(subtitle)
        title_layout.addStretch()
        main_layout.addLayout(title_layout)
        
        # 表格
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(["启用", "名称", "备注", "当前值", "下限", "上限", "坐标", "状态", "报警时间", "🔇 静音"])
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 120)
        main_layout.addWidget(self.table)
        
        # 趋势图
        self.trend_chart = TrendChartWidget()
        main_layout.addWidget(self.trend_chart)
        
        # 按钮栏
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("➕ 添加监控点"); self.btn_add.clicked.connect(self.add_monitor_row)
        self.btn_clear = QPushButton("🗑 清空趋势"); self.btn_clear.clicked.connect(self.clear_history)
        self.btn_start = QPushButton("▶ 开始监控"); self.btn_start.setObjectName("btn_start"); self.btn_start.clicked.connect(self.start_monitor)
        self.btn_save = QPushButton("💾 保存配置"); self.btn_save.clicked.connect(self.save_config)
        
        for btn in [self.btn_add, self.btn_clear, self.btn_start, self.btn_save]:
            btn_layout.addWidget(btn)
        main_layout.addLayout(btn_layout)

    def add_monitor_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.value_history[row] = []
        
        chk = QCheckBox(); chk.setChecked(True); self.table.setCellWidget(row, 0, chk)
        self.table.setCellWidget(row, 2, QLineEdit()) # 备注框
        
        self.table.setItem(row, 1, QTableWidgetItem(f"区域{row+1}"))
        self.table.setItem(row, 3, QTableWidgetItem("--"))
        self.table.setItem(row, 4, QTableWidgetItem("0"))
        self.table.setItem(row, 5, QTableWidgetItem("100"))
        self.table.setItem(row, 6, QTableWidgetItem("0,0,100,100"))
        
    def clear_history(self):
        selected = self.table.selectedItems()
        if selected:
            row = selected[0].row()
            self.value_history[row] = []
            self.trend_chart.set_data([], "数值趋势")

    def save_config(self):
        config = {'monitors': []}
        for row in range(self.table.rowCount()):
            config['monitors'].append({
                'name': self.table.item(row, 1).text(),
                'remark': self.table.cellWidget(row, 2).text(),
                'lower': float(self.table.item(row, 4).text()),
                'upper': float(self.table.item(row, 5).text()),
                'coords': self.table.item(row, 6).text()
            })
        with open("monitor_config.json", 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def load_config(self):
        if not os.path.exists("monitor_config.json"): return
        with open("monitor_config.json", 'r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data['monitors']:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setCellWidget(row, 0, QCheckBox())
                self.table.setCellWidget(row, 2, QLineEdit(item.get('remark', '')))
                self.table.setItem(row, 1, QTableWidgetItem(item['name']))
                self.table.setItem(row, 4, QTableWidgetItem(str(item['lower'])))
                self.table.setItem(row, 5, QTableWidgetItem(str(item['upper'])))
                self.table.setItem(row, 6, QTableWidgetItem(item['coords']))

    def start_monitor(self):
        # 启动逻辑保持，不再清理 value_history
        self.monitoring = True
        # ... (启动线程逻辑) ...

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
