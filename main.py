# 在 AddMonitorDialog 的 __init__ 方法中，修改坐标部分：

# 区域坐标 - 添加"选择区域"按钮
coord_group = QGroupBox("📐 屏幕区域")
coord_layout = QGridLayout()

# X, Y
self.x_edit = QSpinBox()
self.x_edit.setRange(0, 9999)
self.x_edit.setValue(100)
coord_layout.addWidget(QLabel("X:"), 0, 0)
coord_layout.addWidget(self.x_edit, 0, 1)

self.y_edit = QSpinBox()
self.y_edit.setRange(0, 9999)
self.y_edit.setValue(100)
coord_layout.addWidget(QLabel("Y:"), 0, 2)
coord_layout.addWidget(self.y_edit, 0, 3)

# 宽度, 高度
self.w_edit = QSpinBox()
self.w_edit.setRange(10, 9999)
self.w_edit.setValue(150)
coord_layout.addWidget(QLabel("宽度:"), 1, 0)
coord_layout.addWidget(self.w_edit, 1, 1)

self.h_edit = QSpinBox()
self.h_edit.setRange(10, 9999)
self.h_edit.setValue(60)
coord_layout.addWidget(QLabel("高度:"), 1, 2)
coord_layout.addWidget(self.h_edit, 1, 3)

# 选择区域按钮（占满一行）
self.btn_select_area = QPushButton("🖱 在屏幕上框选区域")
self.btn_select_area.setStyleSheet("""
    QPushButton {
        background-color: #89b4fa;
        color: #1e1e2e;
        padding: 8px;
        font-weight: bold;
    }
    QPushButton:hover {
        background-color: #74c7ec;
    }
""")
self.btn_select_area.clicked.connect(self.select_screen_area)
coord_layout.addWidget(self.btn_select_area, 2, 0, 1, 4)

coord_group.setLayout(coord_layout)
layout.addRow(coord_group)
