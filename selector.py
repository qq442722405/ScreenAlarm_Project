import sys
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QFont


class ScreenSelector(QWidget):
    """屏幕区域选择器 - 鼠标拖拽框选"""
    area_selected = Signal(int, int, int, int)  # x, y, width, height
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("选择监控区域")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setStyleSheet("background: transparent;")
        
        # 获取屏幕尺寸
        screen = QApplication.primaryScreen()
        self.screen_rect = screen.geometry()
        self.setGeometry(self.screen_rect)
        
        # 选择状态
        self.is_selecting = False
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.selection_rect = QRect()
        
        # 显示提示
        self.setMouseTracking(True)
        
        # 说明标签
        self.label = QLabel("🖱 按住左键拖拽选择区域，松开确认  |  按 ESC 取消", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                background: rgba(0, 0, 0, 180);
                padding: 12px 24px;
                border-radius: 12px;
                font-size: 16px;
                font-weight: bold;
                border: 1px solid rgba(255,255,255,0.2);
            }
        """)
        self.label.adjustSize()
        self.label.move(
            (self.width() - self.label.width()) // 2,
            self.height() - self.label.height() - 50
        )
    
    def paintEvent(self, event):
        """绘制选择框"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制半透明遮罩
        if self.is_selecting or not self.selection_rect.isNull():
            # 遮罩颜色
            mask_color = QColor(0, 0, 0, 120)
            painter.fillRect(self.rect(), mask_color)
            
            # 高亮选择区域
            rect = self.selection_rect if not self.is_selecting else self._get_current_rect()
            if not rect.isNull() and rect.width() > 5 and rect.height() > 5:
                # 清除遮罩区域
                painter.setCompositionMode(QPainter.CompositionMode_Clear)
                painter.fillRect(rect, Qt.transparent)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                
                # 绘制边框
                pen = QPen(QColor(0, 255, 136), 3)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.drawRect(rect)
                
                # 绘制角落标记
                corner_size = 12
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
                info_text = f"{rect.width()} × {rect.height()}"
                painter.setPen(Qt.white)
                painter.setFont(QFont("Arial", 14, QFont.Bold))
                painter.drawText(
                    rect.x() + 10,
                    rect.y() - 12 if rect.y() > 30 else rect.y() + rect.height() + 25,
                    info_text
                )
        else:
            # 初始状态，显示半透明提示
            painter.fillRect(self.rect(), QColor(0, 0, 0, 80))
            painter.setPen(Qt.white)
            painter.setFont(QFont("Arial", 18, QFont.Bold))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "按住鼠标左键并拖拽，选择要监控的屏幕区域\n\n按 ESC 取消选择"
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
        if event.button() == Qt.LeftButton:
            self.is_selecting = True
            self.start_point = event.position().toPoint()
            self.end_point = self.start_point
            self.selection_rect = QRect()
            self.update()
    
    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_point = event.position().toPoint()
            self.update()
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            rect = self._get_current_rect()
            
            if rect.width() > 20 and rect.height() > 20:
                self.selection_rect = rect
                self.update()
                
                # 发送选择结果
                self.area_selected.emit(
                    rect.x(), rect.y(),
                    rect.width(), rect.height()
                )
                self.close()
            else:
                # 区域太小，重置
                self.selection_rect = QRect()
                self.update()
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.area_selected.emit(0, 0, 0, 0)  # 发送空值表示取消
            self.close()
    
    def closeEvent(self, event):
        # 确保发送取消信号
        if self.selection_rect.isNull():
            self.area_selected.emit(0, 0, 0, 0)
        event.accept()