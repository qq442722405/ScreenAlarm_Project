import sys, os, json, time, re, threading, ctypes, socket, urllib.request
from io import BytesIO
from datetime import datetime
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
import mss
import numpy as np
import cv2

# ==================== 9. 全局控制面板 ====================
class GlobalControlPanel(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.boxes = []
        self.monitoring = False
        self.is_editing = False
        self.is_collapsed = False
        self.boxes_panel_hidden = False
        self.reader = None
        self.config_file = "monitor_config.json"
        self.users_file = "users_config.json"
        
        self.users = self.load_users()
        self.alarm_player = AlarmSoundPlayer()
        self.grille_thread = None
        self.monitor_thread = None
        self.web_thread = None

        self.curr_monitor_cd = 0.0
        self.curr_grille_cd = 0.0

        self.ocr_params = {'scale': 3.0, 'clahe': 2.0, 'thresh_block': 11, 'thresh_c': 2}
        self._drag_pos = None

        self.f12_listener = GlobalF12Listener()
        self.f12_listener.f12_triggered.connect(self._on_f12_pressed)
        self.f12_listener.start()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        self.setMaximumWidth(520)

        self.setStyleSheet("""
            QWidget { border-radius: 6px; }
            QLabel { color: #e0e0e0; font-size: 11px; font-weight: bold; background: transparent; border: none; }
            QPushButton { 
                background-color: rgba(43, 45, 66, 0.6); 
                color: #ffffff; 
                border: 1px solid rgba(255, 255, 255, 0.2); 
                border-radius: 4px; 
                padding: 0px 8px; 
                height: 26px;
                font-size: 11px; 
                font-weight: bold; 
            }
            QPushButton:hover { background-color: rgba(61, 64, 91, 0.8); }
            QPushButton:pressed { background-color: rgba(26, 27, 38, 0.9); }
            QDoubleSpinBox, QSpinBox { 
                background-color: rgba(26, 26, 38, 0.8); 
                color: #00ff8c; 
                border: 1px solid rgba(255, 255, 255, 0.2); 
                border-radius: 4px; 
                font-size: 11px; 
                font-weight: bold; 
                padding: 0px 2px;
                height: 26px;
            }
            QCheckBox { color: #00ff8c; font-size: 11px; font-weight: bold; background: transparent; border: none; }
            QCheckBox::indicator { width: 14px; height: 14px; border-radius: 3px; border: 1px solid #00ff8c; background: rgba(26, 26, 38, 0.8); }
            QCheckBox::indicator:checked { background: #00ff8c; }
        """)

        # ---------- 第 1 排：识别监控配置栏 ----------
        self.row1_card = QFrame()
        self.row1_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        self.row1_layout = QHBoxLayout(self.row1_card)
        self.row1_layout.setContentsMargins(8, 5, 8, 5)
        self.row1_layout.setSpacing(6)

        self.row1_layout.addWidget(QLabel("⏱ 识别间隔(秒):"))
        self.spin_interval = CleanDoubleSpinBox()
        self.spin_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_interval.setAlignment(Qt.AlignCenter)
        self.spin_interval.setFixedSize(42, 26)
        self.spin_interval.setRange(0.1, 10.0)
        self.spin_interval.setValue(1.0)
        self.spin_interval.setSingleStep(0.5)
        self.spin_interval.valueChanged.connect(self._on_interval_changed)
        self.row1_layout.addWidget(self.spin_interval)

        self.row1_layout.addWidget(QLabel("📊 记录数:"))
        self.spin_count = QSpinBox()
        self.spin_count.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_count.setAlignment(Qt.AlignCenter)
        self.spin_count.setFixedSize(40, 26)
        self.spin_count.setRange(5, 200)
        self.spin_count.setValue(30)
        self.spin_count.valueChanged.connect(self._on_count_changed)
        self.row1_layout.addWidget(self.spin_count)

        self.row1_layout.addWidget(QLabel("📝 记录间隔(分):"))
        self.spin_log_interval = CleanDoubleSpinBox()
        self.spin_log_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_log_interval.setAlignment(Qt.AlignCenter)
        self.spin_log_interval.setFixedSize(42, 26)
        self.spin_log_interval.setRange(0.0, 1440.0)
        self.spin_log_interval.setValue(1.0)
        self.spin_log_interval.setSingleStep(0.5)
        self.spin_log_interval.valueChanged.connect(self._on_log_interval_changed)
        self.row1_layout.addWidget(self.spin_log_interval)

        self.btn_ocr_adjust = QPushButton("⚙️ 识别调整")
        self.btn_ocr_adjust.setFixedHeight(26)
        self.btn_ocr_adjust.clicked.connect(self._open_ocr_adjust_dialog)
        self.row1_layout.addWidget(self.btn_ocr_adjust)

        main_layout.addWidget(self.row1_card)

        # ---------- 第 2 排：核心操作栏 ----------
        self.row2_card = QFrame()
        self.row2_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        row2_layout = QHBoxLayout(self.row2_card)
        row2_layout.setContentsMargins(8, 5, 8, 5)
        row2_layout.setSpacing(6)

        self.btn_monitor = QPushButton("▶ 开始监控")
        self.btn_monitor.setFixedHeight(26)
        self.btn_monitor.clicked.connect(self._toggle_monitor)
        row2_layout.addWidget(self.btn_monitor)

        self.btn_grille_start = QPushButton("▶ 开始操作")
        self.btn_grille_start.setFixedHeight(26)
        self.btn_grille_start.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")
        self.btn_grille_start.clicked.connect(self._toggle_grille)
        row2_layout.addWidget(self.btn_grille_start)

        self.btn_exit = QPushButton("❌ 退出")
        self.btn_exit.setFixedHeight(26)
        self.btn_exit.clicked.connect(self.close_app)
        row2_layout.addWidget(self.btn_exit)

        self.row2_extra_container = QWidget()
        row2_extra_layout = QHBoxLayout(self.row2_extra_container)
        row2_extra_layout.setContentsMargins(0, 0, 0, 0)
        row2_extra_layout.setSpacing(6)

        self.btn_toggle_hide = QPushButton("👁 隐藏")
        self.btn_toggle_hide.setFixedHeight(26)
        self.btn_toggle_hide.setStyleSheet("background-color: rgba(255,255,255,0.12); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 0px 8px; font-size: 11px; font-weight: bold;")
        self.btn_toggle_hide.clicked.connect(self._toggle_hide_boxes)
        row2_extra_layout.addWidget(self.btn_toggle_hide)

        self.btn_edit = QPushButton("⚙️ 调整窗口")
        self.btn_edit.setFixedSize(90, 26)
        self.btn_edit.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.12); color: #ffffff; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 0px 4px; font-size: 11px; font-weight: bold; } QPushButton:hover { background-color: rgba(61, 64, 91, 0.8); }")
        self.btn_edit.clicked.connect(self._toggle_edit)
        row2_extra_layout.addWidget(self.btn_edit)

        self.widget_edit_tools = QWidget()
        self.widget_edit_tools.setFixedSize(90, 26)
        edit_tools_layout = QHBoxLayout(self.widget_edit_tools)
        edit_tools_layout.setContentsMargins(0, 0, 0, 0)
        edit_tools_layout.setSpacing(4)

        self.btn_finish = QPushButton("✅ 完成")
        self.btn_finish.setFixedSize(60, 26)
        self.btn_finish.setStyleSheet("QPushButton { background-color: #e6b84d; color: black; border-radius: 4px; padding: 0px 4px; font-size: 11px; font-weight: bold; }")
        self.btn_finish.clicked.connect(self._toggle_edit)

        self.btn_add = QPushButton("➕")
        self.btn_add.setFixedSize(26, 26)
        self.btn_add.setStyleSheet("QPushButton { background-color: #00a86b; color: white; border-radius: 4px; padding: 0px 0px; font-size: 11px; font-weight: bold; }")
        self.btn_add.clicked.connect(self._add_box_picker)

        edit_tools_layout.addWidget(self.btn_finish)
        edit_tools_layout.addWidget(self.btn_add)
        self.widget_edit_tools.setVisible(False)

        row2_extra_layout.addWidget(self.widget_edit_tools)
        row2_layout.addWidget(self.row2_extra_container)

        self.spacer_widget = QWidget()
        self.spacer_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row2_layout.addWidget(self.spacer_widget)

        self.btn_collapse = QPushButton("◀")
        self.btn_collapse.setFixedSize(26, 26)
        self.btn_collapse.clicked.connect(self._toggle_collapse)
        row2_layout.addWidget(self.btn_collapse)

        main_layout.addWidget(self.row2_card)

        # ---------- 第 3 排：网络服务按钮与细格栅 (需求一) ----------
        self.grille_card = QFrame()
        self.grille_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        row3_layout = QHBoxLayout(self.grille_card)
        row3_layout.setContentsMargins(8, 5, 8, 5)
        row3_layout.setSpacing(6)

        self.chk_grille = QCheckBox("细格栅")
        self.chk_grille.toggled.connect(self.save_config)
        row3_layout.addWidget(self.chk_grille)

        row3_layout.addWidget(QLabel("执行间隔(分):"))
        self.spin_grille_interval = CleanDoubleSpinBox()
        self.spin_grille_interval.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.spin_grille_interval.setAlignment(Qt.AlignCenter)
        self.spin_grille_interval.setFixedSize(48, 24)
        self.spin_grille_interval.setRange(0.1, 1440.0)
        self.spin_grille_interval.setValue(2.0)
        self.spin_grille_interval.setSingleStep(0.5)
        self.spin_grille_interval.valueChanged.connect(self._on_grille_interval_changed)
        row3_layout.addWidget(self.spin_grille_interval)

        self.lbl_grille_countdown = QLabel("⏳ --")
        self.lbl_grille_countdown.setStyleSheet("color: #ffcc00; font-weight: bold; padding-left: 4px;")
        row3_layout.addWidget(self.lbl_grille_countdown)

        row3_layout.addSpacing(10)

        # 改为按钮弹出网络服务界面 (需求一)
        self.btn_web_service = QPushButton("🌐 网页服务")
        self.btn_web_service.setFixedHeight(26)
        self.btn_web_service.clicked.connect(self._open_web_service_dialog)
        row3_layout.addWidget(self.btn_web_service)

        row3_layout.addStretch()
        main_layout.addWidget(self.grille_card)

        self._update_button_styles()
        self.adjustSize()
        self._position_top_right()

        self._init_ocr()
        self.load_config()

    def load_users(self):
        """读取用户字典，默认账户 admin / admin"""
        if os.path.exists(self.users_file):
            try:
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data:
                        return data
            except Exception:
                pass
        return {"admin": "admin"}

    def save_users(self):
        """保存用户字典"""
        try:
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存用户配置失败:", e)

    # ---------- 需求五：配置文件实时保存 ----------
    def save_config(self):
        """实时保存所有选框和全局参数配置"""
        try:
            data = {
                'interval': self.spin_interval.value(),
                'count': self.spin_count.value(),
                'log_interval': self.spin_log_interval.value(),
                'grille_interval': self.spin_grille_interval.value(),
                'use_grille': self.chk_grille.isChecked(),
                'ocr_params': self.ocr_params,
                'boxes': []
            }
            for b in self.boxes:
                data['boxes'].append({
                    'id': b.box_id,
                    'x': b.capture_x,
                    'y': b.capture_y,
                    'w': b.capture_w,
                    'h': b.capture_h,
                    'name': b.name,
                    'lower': b.lower,
                    'mid_val': b.mid_val,
                    'upper': b.upper,
                    'decimal_places': b.decimal_places,
                    'is_muted': b.is_muted
                })
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存配置文件失败:", e)

    def load_config(self):
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            return
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.spin_interval.setValue(data.get('interval', 1.0))
            self.spin_count.setValue(data.get('count', 30))
            self.spin_log_interval.setValue(data.get('log_interval', 1.0))
            self.spin_grille_interval.setValue(data.get('grille_interval', 2.0))
            self.chk_grille.setChecked(data.get('use_grille', False))

            if 'ocr_params' in data:
                self.ocr_params = data['ocr_params']

            for b_data in data.get('boxes', []):
                box = self.create_box(
                    x=b_data.get('x', 100),
                    y=b_data.get('y', 100),
                    w=b_data.get('w', 150),
                    h=b_data.get('h', 40),
                    name=b_data.get('name', '区域'),
                    lower=b_data.get('lower', 0.0),
                    mid_val=b_data.get('mid_val', 50.0),
                    upper=b_data.get('upper', 100.0),
                    decimal_places=b_data.get('decimal_places', 0),
                    box_id=b_data.get('id')
                )
                if b_data.get('is_muted', False):
                    box._toggle_mute()
        except Exception as e:
            print("读取配置文件失败:", e)

    def _open_web_service_dialog(self):
        """打开网页服务设置与二维码弹窗 (需求一)"""
        dlg = WebServiceDialog(self, parent=self)
        dlg.exec()

    def start_web_service_with_ip(self, host_ip):
        if not FLASK_AVAILABLE:
            return
        if self.web_thread:
            self.stop_web_service()
        self.web_thread = WebServerThread(self, host='0.0.0.0', port=5000)
        self.web_thread.action_requested.connect(self._handle_web_action)
        self.web_thread.start()
        self.save_config()

    def stop_web_service(self):
        if self.web_thread:
            self.web_thread.stop()
            self.web_thread = None
        self.save_config()

    def _handle_web_action(self, action, box_id, data):
        if action == 'toggle_monitor':
            self._toggle_monitor()
            return
        if action == 'toggle_grille':
            self._toggle_grille()
            return

        target_box = next((b for b in self.boxes if b.box_id == box_id), None)
        if not target_box:
            return

        if action == 'set_limits':
            if 'lower' in data:
                target_box.spin_lower.setValue(float(data['lower']))
            if 'mid_val' in data:
                target_box.spin_mid.setValue(float(data['mid_val']))
            if 'upper' in data:
                target_box.spin_upper.setValue(float(data['upper']))
        elif action == 'clear_alarm':
            target_box._on_clear_alarm()
        elif action == 'toggle_mute':
            target_box._toggle_mute()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _on_f12_pressed(self):
        QTimer.singleShot(0, self._toggle_monitor)

    def _init_ocr(self):
        try:
            import ddddocr
            self.reader = ddddocr.DdddOcr(show_ad=False)
        except Exception as e:
            print("ddddocr 初始化失败:", e)
            self.reader = None

    def _position_top_right(self):
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            self.move(screen_geo.width() - self.width() - 20, 20)

    def _update_button_styles(self):
        if self.monitoring:
            self.btn_monitor.setText("⏹ 停止监控 (F12)")
            self.btn_monitor.setStyleSheet("background-color: #b03a3a; color: white; font-weight: bold;")
        else:
            self.btn_monitor.setText("▶ 开始监控 (F12)")
            self.btn_monitor.setStyleSheet("background-color: #2e9a58; color: white; font-weight: bold;")

        if self.grille_thread and self.grille_thread.isRunning():
            self.btn_grille_start.setText("⏹ 停止操作")
            self.btn_grille_start.setStyleSheet("background-color: #cc3333; color: white; font-weight: bold;")
        else:
            self.btn_grille_start.setText("▶ 开始操作")
            self.btn_grille_start.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold;")

    def _on_interval_changed(self, val):
        if self.monitor_thread:
            self.monitor_thread.update_params(interval=val)
        self.save_config()

    def _on_count_changed(self, val):
        for b in self.boxes:
            b.set_max_log_count(val)
        self.save_config()

    def _on_log_interval_changed(self, val):
        for b in self.boxes:
            b.log_interval_min = val
        self.save_config()

    def _on_grille_interval_changed(self, val):
        if self.grille_thread:
            self.grille_thread.set_interval(val)
        self.save_config()

    def _open_ocr_adjust_dialog(self):
        dlg = OCRAdjustDialog(self.ocr_params, reader=self.reader, parent=self)
        if dlg.exec() == QDialog.Accepted:
            self.ocr_params = dlg.get_params()
            if self.monitor_thread:
                self.monitor_thread.update_params(ocr_params=self.ocr_params)
            self.save_config()

    def _toggle_monitor(self):
        if self.monitoring:
            self.monitoring = False
            if self.monitor_thread:
                self.monitor_thread.stop()
                self.monitor_thread = None
            self.alarm_player.stop()
        else:
            if not self.boxes:
                return
            self.monitoring = True
            screen = QApplication.primaryScreen()
            scale = screen.devicePixelRatio() if screen else 1.0

            self.monitor_thread = MonitorThread(
                boxes=self.boxes,
                interval=self.spin_interval.value(),
                ocr_params=self.ocr_params,
                scale=scale
            )
            self.monitor_thread.set_reader(self.reader)
            self.monitor_thread.value_updated.connect(self._on_value_updated)
            self.monitor_thread.countdown_tick.connect(self._on_monitor_cd_tick)
            self.monitor_thread.start()

        self._update_button_styles()

    def _on_monitor_cd_tick(self, rem_sec):
        self.curr_monitor_cd = rem_sec

    def _toggle_grille(self):
        if self.grille_thread and self.grille_thread.isRunning():
            self.grille_thread.stop()
            self.grille_thread = None
            self.lbl_grille_countdown.setText("⏳ --")
        else:
            if not self.chk_grille.isChecked():
                return
            interval = self.spin_grille_interval.value()
            self.grille_thread = FineGrilleThread(cycle_interval_min=interval)
            self.grille_thread.countdown_tick.connect(self._on_grille_cd_tick)
            self.grille_thread.start()

        self._update_button_styles()

    def _on_grille_cd_tick(self, rem_sec):
        self.curr_grille_cd = rem_sec
        m = int(rem_sec) // 60
        s = int(rem_sec) % 60
        self.lbl_grille_countdown.setText(f"⏳ {m:02d}:{s:02d}")

    def _on_value_updated(self, box, now_str, val, raw_str):
        if box not in self.boxes:
            return

        box.update_result_display(val, raw_str)
        box.add_log_val(now_str, val, raw_str)

        if val is not None:
            if val > box.upper or val < box.lower:
                if not box.user_cleared_alarm or (box.last_alarm_val is not None and abs(val - box.last_alarm_val) > 1e-4):
                    box.user_cleared_alarm = False
                    box.last_alarm_val = val
                    box.set_alarm_state(True)
            else:
                box.user_cleared_alarm = False
                box.last_alarm_val = None
                box.set_alarm_state(False)

        has_any_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if has_any_alarm:
            self.alarm_player.play()
        else:
            self.alarm_player.stop()

    def create_box(self, x=100, y=100, w=150, h=40, name="区域", lower=0.0, mid_val=50.0, upper=100.0, decimal_places=0, box_id=None):
        if box_id is None:
            box_id = int(time.time() * 1000) % 1000000

        box = OverlayRegionWidget(box_id, x, y, w, h, name, lower, mid_val, upper, decimal_places)
        box.log_interval_min = self.spin_log_interval.value()
        box.set_max_log_count(self.spin_count.value())
        box.delete_requested.connect(self._delete_box)
        box.alarm_cleared.connect(self._on_box_alarm_cleared)
        box.config_changed.connect(self.save_config)
        box.set_edit_mode(self.is_editing)
        box.set_panel_hidden(self.boxes_panel_hidden)
        box.show()

        self.boxes.append(box)
        self.save_config()
        return box

    def _add_box_picker(self):
        self.hide()
        for b in self.boxes: b.hide()
        time.sleep(0.2)

        self.picker = CoordinatePicker()

        def on_picked(x, y, w, h):
            self.show()
            for b in self.boxes: b.show()
            if w > 0 and h > 0:
                name_idx = len(self.boxes) + 1
                self.create_box(x, y, w, h, name=f"区域{name_idx}")

        self.picker.coord_selected.connect(on_picked)
        self.picker.showFullScreen()

    def _delete_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self.save_config()

        has_any_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if not has_any_alarm:
            self.alarm_player.stop()

    def _on_box_alarm_cleared(self):
        has_any_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if not has_any_alarm:
            self.alarm_player.stop()

    def _toggle_edit(self):
        self.is_editing = not self.is_editing
        for b in self.boxes:
            b.set_edit_mode(self.is_editing)

        if self.is_editing:
            self.btn_edit.setVisible(False)
            self.widget_edit_tools.setVisible(True)
        else:
            self.btn_edit.setVisible(True)
            self.widget_edit_tools.setVisible(False)
            self.save_config()

    def _toggle_hide_boxes(self):
        self.boxes_panel_hidden = not self.boxes_panel_hidden
        for b in self.boxes:
            b.set_panel_hidden(self.boxes_panel_hidden)
        if self.boxes_panel_hidden:
            self.btn_toggle_hide.setText("👁 显示")
            self.btn_toggle_hide.setStyleSheet("background-color: rgba(255,255,255,0.12); color: #aaa; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 0px 8px; font-size: 11px; font-weight: bold;")
        else:
            self.btn_toggle_hide.setText("👁 隐藏")
            self.btn_toggle_hide.setStyleSheet("background-color: rgba(255,255,255,0.12); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 0px 8px; font-size: 11px; font-weight: bold;")

    def _toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed
        if self.is_collapsed:
            self.row1_card.setVisible(False)
            self.grille_card.setVisible(False)
            self.row2_extra_container.setVisible(False)
            self.btn_collapse.setText("▶")
        else:
            self.row1_card.setVisible(True)
            self.grille_card.setVisible(True)
            self.row2_extra_container.setVisible(True)
            self.btn_collapse.setText("◀")
        self.adjustSize()

    def close_app(self):
        self.save_config()
        self.save_users()
        if self.f12_listener: self.f12_listener.stop()
        if self.monitor_thread: self.monitor_thread.stop()
        if self.grille_thread: self.grille_thread.stop()
        if self.web_thread: self.web_thread.stop()
        self.alarm_player.stop()

        for b in self.boxes: b.close()
        self.close()
        QApplication.quit()



