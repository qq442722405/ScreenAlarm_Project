import time
import re
import os
import sys
from PySide6.QtCore import QThread, Signal

class MonitorThread(QThread):
    value_updated = Signal(int, float)
    alarm_triggered = Signal(int, str, float, float, float)
    status_updated = Signal(int, str)
    ocr_status = Signal(str, bool)
    download_progress = Signal(int)
    
    def __init__(self, monitors):
        super().__init__()
        self.monitors = monitors
        self.running = True
        self.sct = None
        self.reader = None
        self.ocr_ready = False
        self.interval_ms = 500
        self.get_row_enabled = None
        self.alarm_loop_enabled = True
        
        self.alarm_status = {}
        self.manual_clear = False
        
    def set_interval(self, ms):
        self.interval_ms = max(100, ms)
    
    def set_alarm_loop(self, enabled):
        self.alarm_loop_enabled = enabled
    
    def stop(self):
        self.running = False
    
    def reset_row_alarm(self, row):
        if row in self.alarm_status:
            self.alarm_status[row]['alarm'] = False
            self.alarm_status[row]['count'] = 0
            self.alarm_status[row]['last_alarm_time'] = 0
    
    def reset_all_alarms(self):
        self.manual_clear = True
        for row in self.alarm_status:
            self.alarm_status[row]['alarm'] = False
            self.alarm_status[row]['count'] = 0
        for row in self.alarm_status:
            self.status_updated.emit(row, 'normal')
    
    def _is_enabled(self, row):
        if self.get_row_enabled:
            try:
                return self.get_row_enabled(row)
            except:
                return True
        return True
    
    def _init_ocr(self):
        # 延迟加载，解决启动慢
        import easyocr
        
        try:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            
            model_dir = os.path.join(base_dir, 'ocr_models')
            if not os.path.exists(model_dir):
                os.makedirs(model_dir, exist_ok=True)
            
            self.ocr_status.emit("正在下载/加载模型...", False)
            self.reader = easyocr.Reader(
                ['ch_sim', 'en'],
                gpu=False,
                model_storage_directory=model_dir,
                download_enabled=True, # 自动下载
                verbose=False
            )
            
            if self.reader is not None:
                self.ocr_ready = True
                self.ocr_status.emit("就绪 ✅", True)
                return True
            return False
        except Exception as e:
            self.ocr_status.emit(f"加载失败: {str(e)[:50]}", False)
            return False

    def run(self):
        import cv2
        import numpy as np
        import mss
        from PIL import Image
        
        if not self._init_ocr():
            return
            
        self.sct = mss.mss()
        interval_sec = self.interval_ms / 1000.0
        
        while self.running:
            for monitor in self.monitors:
                if not self.running: break
                if not self._is_enabled(monitor['row']): continue
                
                try:
                    # 获取屏幕区域
                    rect = {'top': monitor['y'], 'left': monitor['x'], 
                            'width': monitor['width'], 'height': monitor['height']}
                    
                    # 预处理
                    img = np.array(self.sct.grab(rect))
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    
                    # OCR 识别
                    results = self.reader.readtext(img, detail=0)
                    text = "".join(results)
                    # 清洗数据 (简单正则提取数字)
                    nums = re.findall(r"\d+\.?\d*", text.replace('O', '0').replace('l', '1').replace('I', '1'))
                    
                    if nums:
                        val = float(nums[0])
                        self.value_updated.emit(monitor['row'], val)
                        
                        # 报警逻辑
                        lower, upper = float(monitor.get('lower', 0)), float(monitor.get('upper', 100))
                        if val < lower or val > upper:
                            now = time.time()
                            last_t = self.alarm_status.get(monitor['row'], {}).get('last_alarm_time', 0)
                            if not self.alarm_status.get(monitor['row'], {}).get('alarm', False) or (self.alarm_loop_enabled and now - last_t > 10):
                                self.alarm_status[monitor['row']] = {'alarm': True, 'last_alarm_time': now, 'count': 0}
                                self.alarm_triggered.emit(monitor['row'], monitor['name'], val, lower, upper)
                        else:
                            if not self.manual_clear:
                                self.alarm_status[monitor['row']] = {'alarm': False, 'count': 0}
                                self.status_updated.emit(monitor['row'], 'normal')
                    else:
                        self.status_updated.emit(monitor['row'], 'error')
                        
                except Exception as e:
                    print(f"Monitor error: {e}")
            
            time.sleep(interval_sec)
        
        if self.sct: self.sct.close()
