import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem,
                               QHeaderView, QLabel, QProgressBar, QCheckBox)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

# 导入你的后台监控线程
from monitor import MonitorThread 

class ModernMonitorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("智能OCR数值监控系统")
        self.resize(700, 450)
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f6fa; }
            QPushButton { padding: 8px 15px; border-radius: 4px; background-color: #4cd137; color: white; font-weight: bold; }
            QPushButton:hover { background-color: #44bd32; }
            QPushButton#btnStop { background-color: #e84118; }
            QPushButton#btnStop:hover { background-color: #c23616; }
            QPushButton#btnClear { background-color: #fbc531; color: #2f3640; }
            QTableWidget { border: 1px solid #dcdde1; border-radius: 4px; background-color: white; }
            QHeaderView::section { background-color: #2f3640; color: white; padding: 4px; font-weight: bold; }
        """)

        # 模拟你要监控的区域数据 (你可以根据实际需求修改这里的 x, y, width, height)
        self.monitors_config = [
            {'row': 0, 'name': '血量 (HP)', 'x': 100, 'y': 100, 'width': 150, 'height': 40, 'lower': 30.0, 'upper': 100.0},
            {'row': 1, 'name': '魔法 (MP)', 'x': 100, 'y': 150, 'width': 150, 'height': 40, 'lower': 20.0, 'upper': 100.0},
            {'row': 2, 'name': '特殊状态', 'x': 100, 'y': 200, 'width': 150, 'height': 40, 'lower': 0.0, 'upper': 50.0}
        ]

        self.thread = None
        self.row_enabled_states = {m['row']: True for m in self.monitors_config}

        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # === 1. 顶部控制面板 ===
        control_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ 开始监控")
        self.btn_stop = QPushButton("⏹ 停止监控")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setEnabled(False)
        self.btn_clear_alarm = QPushButton("消除当前警报")
        self.btn_clear_alarm.setObjectName("btnClear")

        self.btn_start.clicked.connect(self.start_monitoring)
        self.btn_stop.clicked.connect(self.stop_monitoring)
        self.btn_clear_alarm.clicked.connect(self.clear_alarms)

        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_stop)
        control_layout.addWidget(self.btn_clear_alarm)
        control_layout.addStretch()
        main_layout.addLayout(control_layout)

        # === 2. 核心数据表格 ===
        self.table = QTableWidget(len(self.monitors_config), 6)
        self.table.setHorizontalHeaderLabels(["启用", "监控项", "当前读取值", "最低阈值", "最高阈值", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers) # 禁止直接编辑表格内容

        for m in self.monitors_config:
            row = m['row']
            # 启用复选框
            chk = QCheckBox()
            chk.setChecked(True)
            chk.stateChanged.connect(lambda state, r=row: self.toggle_row(r, state))
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignCenter)
            chk_layout.setContentsMargins(0,0,0,0)
            
            self.table.setCellWidget(row, 0, chk_widget)
            self.table.setItem(row, 1, QTableWidgetItem(m['name']))
            self.table.setItem(row, 2, QTableWidgetItem("等待读取..."))
            self.table.setItem(row, 3, QTableWidgetItem(str(m['lower'])))
            self.table.setItem(row, 4, QTableWidgetItem(str(m['upper'])))
            self.table.setItem(row, 5, QTableWidgetItem("未运行"))

        main_layout.addWidget(self.table)

        # === 3. 底部状态栏与进度条 ===
        status_layout = QHBoxLayout()
        self.status_label = QLabel("系统就绪。请点击开始监控。")
        self.status_label.setStyleSheet("color: #7f8fa6; font-weight: bold;")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide() # 默认隐藏，需要下载时显示

        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.progress_bar)
        main_layout.addLayout(status_layout)

    # --- 界面交互逻辑 ---
    def toggle_row(self, row, state):
        self.row_enabled_states[row] = (state == Qt.Checked)

    def is_row_enabled(self, row):
        return self.row_enabled_states.get(row, True)

    def start_monitoring(self):
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_label.setText("正在初始化 OCR 引擎...")

        # 实例化你在 monitor.py 中写的线程
        self.thread = MonitorThread(self.monitors_config)
        
        # 绑定回调函数：你的线程需要一个回调来判断该行是否勾选
        self.thread.get_row_enabled = self.is_row_enabled

        # 连接你代码中抛出的信号
        self.thread.value_updated.connect(self.on_value_updated)
        self.thread.alarm_triggered.connect(self.on_alarm_triggered)
        self.thread.status_updated.connect(self.on_status_updated)
        self.thread.ocr_status.connect(self.on_ocr_status)
        self.thread.download_progress.connect(self.on_download_progress)

        self.thread.start()

    def stop_monitoring(self):
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait() # 等待线程安全退出
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_label.setText("监控已停止。")
        for i in range(self.table.rowCount()):
            self.table.setItem(i, 5, QTableWidgetItem("已停止"))
            self.table.item(i, 5).setBackground(QColor("white"))

    def clear_alarms(self):
        if self.thread:
            self.thread.reset_all_alarms()
        # 恢复界面颜色
        for i in range(self.table.rowCount()):
            if self.table.item(i, 5):
                self.table.item(i, 5).setBackground(QColor("white"))

    # --- 槽函数：处理线程发来的信号 ---
    def on_value_updated(self, row, value):
        item = self.table.item(row, 2)
        if item:
            item.setText(f"{value:.2f}")

    def on_alarm_triggered(self, row, name, value, lower, upper):
        item = self.table.item(row, 5)
        if item:
            item.setText("🚨 警报: 越界!")
            item.setBackground(QColor("#ff7979")) # 红色背景警告

    def on_status_updated(self, row, status):
        if row == -1: # 全局错误
            self.status_label.setText(f"错误: {status}")
            return
            
        item = self.table.item(row, 5)
        if not item:
            return
            
        if status == 'normal':
            item.setText("正常")
            item.setBackground(QColor("#badc58")) # 绿色背景
        elif status == 'disabled':
            item.setText("已禁用")
            item.setBackground(QColor("#dcdde1"))
        elif status == 'error':
            item.setText("读取失败")
            item.setBackground(QColor("#f6e58d"))
        elif status == '监控中':
            item.setText("监控中...")
            item.setBackground(QColor("white"))

    def on_ocr_status(self, msg, is_ready):
        self.status_label.setText(f"OCR状态: {msg}")
        if is_ready:
            self.progress_bar.hide()

    def on_download_progress(self, progress):
        if progress < 100:
            self.progress_bar.show()
            self.progress_bar.setValue(progress)
        else:
            self.progress_bar.hide()

if __name__ == "__main__":
    # 这是启动 GUI 的关键！必须要有 QApplication 和 exec()
    app = QApplication(sys.argv)
    window = ModernMonitorWindow()
    window.show()
    sys.exit(app.exec())
