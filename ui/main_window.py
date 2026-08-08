# -*- coding: utf-8 -*-
# 模块化拆分文件：从原主程序提取，后续可独立维护

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
        self.record_file = "记录.txt"
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
        
        # 【修改项 1】设置识别间隔范围与默认值为 10 秒
        self.spin_interval.setRange(0.1, 3600.0)
        self.spin_interval.setValue(10.0)
        
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

        # ---------- 第 3 排：Web 服务扩展 ----------
        self.grille_card = QFrame()
        self.grille_card.setStyleSheet("QFrame { background-color: rgba(0, 0, 0, 0.8); border: 1px solid rgba(255, 255, 255, 0.2); border-radius: 6px; }")
        row3_layout = QHBoxLayout(self.grille_card)
        row3_layout.setContentsMargins(8, 5, 8, 5)
        row3_layout.setSpacing(6)

        self.chk_grille = QCheckBox("细格栅")
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

        self.chk_web = QCheckBox("🌐 网页服务")
        self.chk_web.toggled.connect(self._toggle_web_service)
        row3_layout.addWidget(self.chk_web)

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

    def _toggle_web_service(self, checked):
        if checked:
            if not FLASK_AVAILABLE:
                self.chk_web.setChecked(False)
                return

            self.web_thread = WebServerThread(self, host='0.0.0.0', port=5000)
            self.web_thread.action_requested.connect(self._handle_web_action)
            self.web_thread.start()
        else:
            if self.web_thread:
                self.web_thread.stop()
                self.web_thread = None

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

    def _open_ocr_adjust_dialog(self):
        dialog = OCRAdjustDialog(self.ocr_params, reader=self.reader, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.ocr_params = dialog.get_params()
            if hasattr(self, 'monitor_thread') and self.monitor_thread:
                self.monitor_thread.update_params(ocr_params=self.ocr_params)

    def _update_button_styles(self):
        if self.is_collapsed:
            self.btn_collapse.setText("▶")
        else:
            self.btn_collapse.setText("◀")

        self.btn_collapse.setStyleSheet("background-color: rgba(255,255,255,0.1); color: #00ff8c; font-weight: bold; border-radius: 4px;")
        self.btn_monitor.setStyleSheet(f"background-color: {'#b03a3a' if self.monitoring else '#2e9a58'}; color: white; font-weight: bold; height: 26px;")
        self.btn_exit.setStyleSheet("background-color: rgba(255, 255, 255, 0.15); color: white; font-weight: bold; height: 26px;")

    def _toggle_collapse(self):
        self.is_collapsed = not self.is_collapsed

        self.row1_card.setVisible(not self.is_collapsed)
        self.grille_card.setVisible(not self.is_collapsed)
        self.row2_extra_container.setVisible(not self.is_collapsed)
        self.spacer_widget.setVisible(not self.is_collapsed)

        self._update_button_styles()
        self.adjustSize()

    def _toggle_hide_boxes(self):
        self.boxes_panel_hidden = not self.boxes_panel_hidden
        for box in self.boxes:
            box.set_panel_hidden(self.boxes_panel_hidden)

        self.btn_toggle_hide.setText("👁 显示" if self.boxes_panel_hidden else "👁 隐藏")
        self.btn_toggle_hide.setStyleSheet("background-color: #e65100; color: white;" if self.boxes_panel_hidden else "background-color: rgba(255,255,255,0.12); color: #00ff8c; border: 1px solid rgba(255,255,255,0.2); border-radius: 4px; padding: 0px 8px; font-size: 11px; font-weight: bold;")

    def _on_f12_pressed(self):
        if self.grille_thread and self.grille_thread.isRunning():
            self.stop_grille()

    def _on_grille_interval_changed(self, val):
        if self.grille_thread and self.grille_thread.isRunning():
            self.grille_thread.set_interval(val)

    def _toggle_grille(self):
        if self.grille_thread and self.grille_thread.isRunning():
            self.stop_grille()
        else:
            if not self.chk_grille.isChecked():
                return
            self.start_grille()

    def start_grille(self):
        self.grille_thread = FineGrilleThread(cycle_interval_min=self.spin_grille_interval.value())
        self.grille_thread.countdown_tick.connect(self._on_grille_countdown_tick)
        self.grille_thread.start()
        self.btn_grille_start.setText("⏹ 停止操作(F12)")
        self.btn_grille_start.setStyleSheet("background-color: #cc3333; color: white; font-weight: bold; height: 26px;")

    def stop_grille(self):
        if self.grille_thread:
            thread = self.grille_thread
            self.grille_thread = None
            thread.stop()
            thread.quit()
            if not thread.wait(1000):
                thread.terminate()
                thread.wait()
        self.curr_grille_cd = 0.0
        self.lbl_grille_countdown.setText("⏳ --")
        self.btn_grille_start.setText("▶ 开始操作")
        self.btn_grille_start.setStyleSheet("background-color: #0088cc; color: white; font-weight: bold; height: 26px;")

    def _on_grille_countdown_tick(self, rem_sec):
        self.curr_grille_cd = rem_sec
        m, s = divmod(int(rem_sec), 60)
        self.lbl_grille_countdown.setText(f"⏳ {m:02d}:{s:02d}")

    def _position_top_right(self):
        screen_geo = QApplication.primaryScreen().geometry()
        self.move(screen_geo.width() - self.width() - 20, 20)

    def _init_ocr(self):
        class OCRLoader(QThread):
            loaded = Signal(object)
            def run(self):
                try:
                    import ddddocr
                    ocr = ddddocr.DdddOcr(show_ad=False)
                    self.loaded.emit(ocr)
                except Exception as e:
                    print("OCR init error:", e)
                    self.loaded.emit(None)

        self.loader = OCRLoader()
        self.loader.loaded.connect(self._on_ocr_loaded)
        self.loader.start()

    def _on_ocr_loaded(self, reader):
        self.reader = reader
        if self.monitor_thread:
            self.monitor_thread.set_reader(reader)

    def _on_interval_changed(self, val):
        if self.monitor_thread:
            self.monitor_thread.update_params(interval=val)

    def _on_count_changed(self, val):
        for box in self.boxes:
            box.set_max_log_count(val)

    def _on_log_interval_changed(self, val):
        for box in self.boxes:
            box.log_interval_min = val

    def _toggle_edit(self):
        self.is_editing = not self.is_editing
        self.btn_edit.setVisible(not self.is_editing)
        self.widget_edit_tools.setVisible(self.is_editing)
        for box in self.boxes:
            box.set_edit_mode(self.is_editing)
        if not self.is_editing:
            self.save_config()

    def _add_box_picker(self):
        self.picker = CoordinatePicker()
        def on_picked(x, y, w, h):
            if w > 0 and h > 0:
                box = self.add_box(x, y, w, h)
                box.set_edit_mode(True)
                self.save_config()
        self.picker.coord_selected.connect(on_picked)
        self.picker.showFullScreen()

    def add_box(self, x, y, w, h, name="区域", lower=0.0, mid_val=50.0, upper=100.0, decimal_places=0):
        box_id = len(self.boxes) + 1
        box = OverlayRegionWidget(box_id, x, y, w, h, name, lower, mid_val, upper, decimal_places)
        box.log_interval_min = self.spin_log_interval.value()
        box.set_max_log_count(self.spin_count.value())
        box.delete_requested.connect(self._delete_box)
        box.alarm_cleared.connect(self._check_global_alarm_state)
        box.mute_toggled.connect(self._check_global_alarm_state)
        box.show()
        self.boxes.append(box)
        return box

    def _delete_box(self, box):
        if box in self.boxes:
            self.boxes.remove(box)
            box.close()
            self._check_global_alarm_state()
            self.save_config()

    def _toggle_monitor(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        if not self.boxes: return
        self.monitoring = True
        self.btn_monitor.setText("⏹ 停止监控")
        self._update_button_styles()

        screen = QApplication.primaryScreen()
        scale = screen.devicePixelRatio() if screen else 1.0

        self.monitor_thread = MonitorThread(self.boxes, interval=self.spin_interval.value(), ocr_params=self.ocr_params, scale=scale)
        if self.reader:
            self.monitor_thread.set_reader(self.reader)
        self.monitor_thread.value_updated.connect(self._on_value_updated)
        self.monitor_thread.countdown_tick.connect(self._on_monitor_countdown_tick)
        self.monitor_thread.start()

    def stop_monitor(self):
        self.monitoring = False
        if self.monitor_thread:
            thread = self.monitor_thread
            self.monitor_thread = None
            thread.stop()
            thread.quit()
            if not thread.wait(1000):
                thread.terminate()
                thread.wait()
        self.curr_monitor_cd = 0.0
        self.btn_monitor.setText("▶ 开始监控")
        self._update_button_styles()
        self.alarm_player.stop()

    def _on_monitor_countdown_tick(self, rem_sec):
        self.curr_monitor_cd = rem_sec

    def _on_value_updated(self, box, time_str, val, raw_text):
        if not self.monitoring: return
        box.update_result_display(val, raw_text)
        box.add_log_val(time_str, val, raw_text)

        if val is not None:
            if val > box.upper or val < box.lower:
                if not box.user_cleared_alarm:
                    box.set_alarm_state(True)
            else:
                box.user_cleared_alarm = False
                box.set_alarm_state(False)

        self._check_global_alarm_state()

    def _check_global_alarm_state(self):
        has_alarm = any(b.is_alarm and not b.is_muted for b in self.boxes)
        if has_alarm:
            self.alarm_player.play()
        else:
            self.alarm_player.stop()

    def save_record(self, value):
        try:
            with open(self.record_file, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now()} {value}\n")
        except Exception:
            pass

    def save_config(self):
        data = {
            "interval": self.spin_interval.value(),
            "count": self.spin_count.value(),
            "log_interval": self.spin_log_interval.value(),
            "ocr_params": self.ocr_params,
            "window": {"x": self.x(), "y": self.y()},
            "grille_interval": self.spin_grille_interval.value(),
            "grille_enable": self.chk_grille.isChecked(),
            "web_service": self.chk_web.isChecked(),
            "boxes": []
        }
        for b in self.boxes:
            data["boxes"].append({
                "x": b.capture_x, "y": b.capture_y, "w": b.capture_w, "h": b.capture_h,
                "name": b.name, "lower": b.lower, "mid_val": getattr(b, 'mid_val', 50.0),
                "upper": b.upper, "decimal_places": b.decimal_places
            })
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("保存配置失败:", e)

    def load_config(self):
        if not os.path.exists(self.config_file): return
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.spin_interval.setValue(data.get("interval", 10.0))
            self.spin_count.setValue(data.get("count", 30))
            self.spin_log_interval.setValue(data.get("log_interval", 1.0))
            self.spin_grille_interval.setValue(data.get("grille_interval", 2.0))
            self.chk_web.setChecked(data.get("web_service", False))
            self.chk_grille.setChecked(data.get("grille_enable", False))
            self.ocr_params = data.get("ocr_params", self.ocr_params)

            win = data.get("window", {})
            if "x" in win and "y" in win:
                self.move(win["x"], win["y"])

            for item in data.get("boxes", []):
                self.add_box(
                    item["x"], item["y"], item["w"], item["h"],
                    item.get("name", "区域"),
                    item.get("lower", 0.0),
                    item.get("mid_val", 50.0),
                    item.get("upper", 100.0),
                    item.get("decimal_places", 0)
                )
        except Exception as e:
            print("加载配置失败:", e)

    def closeEvent(self, event):
        self.save_config()
        event.accept()

    def close_app(self):
        self.stop_grille()
        self.stop_monitor()
        if self.web_thread:
            self.web_thread.stop()
        if self.f12_listener:
            self.f12_listener.stop()
            self.f12_listener.quit()
            self.f12_listener.wait()
        self.save_config()
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    panel = GlobalControlPanel()
    panel.show()
    sys.exit(app.exec())
