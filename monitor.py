import time
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
        self.interval_ms = 500
        self.get_row_enabled = None
        self.alarm_loop_enabled = True
        self.alarm_status = {}
        
    def set_interval(self, ms):
        self.interval_ms = max(100, ms)
    
    def set_alarm_loop(self, enabled):
        self.alarm_loop_enabled = enabled
    
    def stop(self):
        self.running = False
    
    def run(self):
        # 延迟加载重型库，确保主界面瞬间启动
        import cv2
        import numpy as np
        import mss
        import easyocr
        
        try:
            self.ocr_status.emit("正在检查模型...", False)
            # 开启自动下载模型
            self.reader = easyocr.Reader(['ch_sim', 'en'], download_enabled=True)
            self.ocr_status.emit("OCR引擎就绪", True)
        except Exception as e:
            self.ocr_status.emit(f"OCR初始化失败: {e}", False)
            return

        self.sct = mss.mss()
        interval_sec = self.interval_ms / 1000.0
        
        while self.running:
            for monitor in self.monitors:
                if not self.running: break
                if self.get_row_enabled and not self.get_row_enabled(monitor['row']):
                    continue
                
                try:
                    # 截图
                    monitor_area = {'top': monitor['y'], 'left': monitor['x'], 'width': monitor['width'], 'height': monitor['height']}
                    img = np.array(self.sct.grab(monitor_area))
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    
                    results = self.reader.readtext(img, detail=0)
                    
                    found_val = None
                    for res in results:
                        try:
                            # 清洗 OCR 字符
                            clean_res = res.replace('O', '0').replace('l', '1').replace('I', '1').replace('o', '0')
                            found_val = float(clean_res)
                            break
                        except: continue
                    
                    if found_val is not None:
                        self.value_updated.emit(monitor['row'], found_val)
                        lower, upper = monitor['lower'], monitor['upper']
                        
                        if found_val < lower or found_val > upper:
                            now = time.time()
                            last_time = self.alarm_status.get(monitor['row'], {}).get('last_alarm_time', 0)
                            
                            if not self.alarm_status.get(monitor['row'], {}).get('alarm', False):
                                self.alarm_status[monitor['row']] = {'alarm': True, 'last_alarm_time': now}
                                self.alarm_triggered.emit(monitor['row'], monitor['name'], found_val, lower, upper)
                            elif self.alarm_loop_enabled and (now - last_time > 10):
                                self.alarm_status[monitor['row']]['last_alarm_time'] = now
                                self.alarm_triggered.emit(monitor['row'], monitor['name'], found_val, lower, upper)
                        else:
                            self.alarm_status[monitor['row']] = {'alarm': False}
                            self.status_updated.emit(monitor['row'], 'normal')
                    else:
                        self.status_updated.emit(monitor['row'], 'error')
                except Exception as e:
                    print(f"Monitor error: {e}")
            
            time.sleep(interval_sec)
        
        if self.sct: self.sct.close()
