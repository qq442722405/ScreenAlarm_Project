import sys
from PySide6.QtWidgets import QApplication, QWidget, QLabel
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont


class ScreenSelector(QWidget):
    """屏幕区域选择器 - 鼠标拖拽框选"""
    area_selected = Signal(int, int, int, int)  # x, y, width, height
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("选择监控区域")
        
        # 关键修复：设置窗口标志，确保在最上层并捕获鼠标
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | 
            Qt.FramelessWindowHint | 
            Qt.Tool
        )
        self.setStyleSheet("background: transparent;")
        
        # 设置透明背景
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        
        # 获取所有屏幕的总尺寸
        screens = QApplication.screens()
        total_rect = QRect(0, 0, 0, 0)
        for s in screens:
            rect = s.geometry()
            total_rect = total_rect.united(rect)
        
        self.setGeometry(total_rect)
        self.showFullScreen()
        
        # 选择状态
        self.is_selecting = False
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.selection_rect = QRect()
        
        # 设置鼠标追踪
        self.setMouseTracking(True)
        
        # 确保窗口获得焦点
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        
        # 说明标签
        self.label = QLabel("🖱 按住左键拖拽选择区域，松开确认  |  按 ESC 取消", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                background: rgba(0, 0, 0, 200);
                padding: 16px 32px;
                border-radius: 16px;
                font-size: 18px;
                font-weight: bold;
                border: 2px solid rgba(255,255,255,0.3);
            }
        """)
        self.label.adjustSize()
        self.label.move(
            (self.width() - self.label.width()) // 2,
            self.height() - self.label.height() - 80
        )
        
        # 使用定时器确保窗口始终在最前
        QTimer.singleShot(100, self._ensure_top)
    
    def _ensure_top(self):
        """确保窗口在最上层"""
        self.raise_()
        self.activateWindow()
    
    def paintEvent(self, event):
        """绘制选择框"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 半透明遮罩
        mask_color = QColor(0, 0, 0, 150)
        painter.fillRect(self.rect(), mask_color)
        
        if self.is_selecting or not self.selection_rect.isNull():
            # 获取当前选择区域
            rect = self.selection_rect if not self.is_selecting else self._get_current_rect()
            
            if not rect.isNull() and rect.width() > 5 and rect.height() > 5:
                # 清除选中区域的遮罩（显示原始画面）
                painter.setCompositionMode(QPainter.CompositionMode_Clear)
                painter.fillRect(rect, Qt.transparent)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                
                # 绘制高亮边框
                pen = QPen(QColor(0, 255, 136), 3)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.drawRect(rect)
                
                # 绘制角落标记
                corner_size = 15
                painter.setPen(QPen(QColor(0, 255, 136), 3))
                
                # 左上角
                painter.drawLine(rect.topLeft(), rect.topLeft() + QPoint(corner_size, 0))
                painter.drawLine(rect.topLeft(), rect.topLeft() + QPoint(0, corner_size))
                # 右上角
                painter.drawLine(rect.topRight(), rect.topRight() + QPoint(-corner_size, 0))
                painter.drawLine(rect.topRight(), rect.topRight() + QPoint(0, corner_size))
                # 左下角
                painter.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPoint(corner_size, 0))
                painter.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPoint(0, -corner_size))
                # 右下角
                painter.drawLine(rect.bottomRight(), rect.bottomRight() + QPoint(-corner_size, 0))
                painter.drawLine(rect.bottomRight(), rect.bottomRight() + QPoint(0, -corner_size))
                
                # 显示尺寸信息
                info_text = f"📍 {rect.width()} × {rect.height()} px"
                painter.setPen(Qt.white)
                painter.setFont(QFont("Arial", 14, QFont.Bold))
                
                # 计算文字位置（在框上方或下方）
                text_y = rect.y() - 15 if rect.y() > 40 else rect.y() + rect.height() + 30
                painter.drawText(rect.x() + 10, text_y, info_text)
                
        else:
            # 初始状态，显示提示文字
            painter.setPen(Qt.white)
            painter.setFont(QFont("Arial", 20, QFont.Bold))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "🖱 按住鼠标左键并拖拽，选择要监控的区域\n\n按 ESC 取消选择"
            )
    
    def _get_current_rect(self):
        """获取当前选择的矩形"""
        if not self.is_selecting:
            return self.selection_rect
        
        x = min(self.start_point.x(), self.end_point.x())
        y = min(self.start_point.y(), self.end_point.y())
        w = abs(self.end_point.x() - self.start_point.x())
        h = abs(self.end_point.y() - self.start_point.y())
        return QRect(x, y, w, h)
    
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self.is_selecting = True
            self.start_point = event.position().toPoint()
            self.end_point = self.start_point
            self.selection_rect = QRect()
            self.update()
            self.setCursor(Qt.CrossCursor)
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件"""
        if self.is_selecting:
            self.end_point = event.position().toPoint()
            self.update()
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            rect = self._get_current_rect()
            
            if rect.width() > 20 and rect.height() > 20:
                self.selection_rect = rect
                self.update()
                self.setCursor(Qt.ArrowCursor)
                
                # 延迟发送信号，让用户看到选择结果
                QTimer.singleShot(300, self._confirm_selection)
            else:
                self.selection_rect = QRect()
                self.update()
                self.setCursor(Qt.ArrowCursor)
    
    def _confirm_selection(self):
        """确认选择并关闭窗口"""
        if not self.selection_rect.isNull():
            self.area_selected.emit(
                self.selection_rect.x(),
                self.selection_rect.y(),
                self.selection_rect.width(),
                self.selection_rect.height()
            )
        self.close()
    
    def keyPressEvent(self, event):
        """键盘事件 - ESC取消"""
        if event.key() == Qt.Key_Escape:
            self.area_selected.emit(0, 0, 0, 0)
            self.close()
    
    def showEvent(self, event):
        """窗口显示时确保在最上层"""
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        self.setCursor(Qt.CrossCursor)
    
    def closeEvent(self, event):
        """关闭事件"""
        self.setCursor(Qt.ArrowCursor)
        event.accept()
