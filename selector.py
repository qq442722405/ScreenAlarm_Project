import sys
from PySide6.QtWidgets import QApplication, QWidget, QLabel
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont


class ScreenSelector(QWidget):
    area_selected = Signal(int, int, int, int)
    
    def __init__(self):
        super().__init__()
        screens = QApplication.screens()
        total_rect = QRect(0, 0, 0, 0)
        for s in screens:
            rect = s.geometry()
            total_rect = total_rect.united(rect)
        self.setGeometry(total_rect)
        self.setWindowTitle("选择监控区域")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | 
            Qt.FramelessWindowHint | 
            Qt.Tool |
            Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        
        self.is_selecting = False
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.selection_rect = QRect()
        
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
        
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(50, self._ensure_active)
        QTimer.singleShot(200, self._ensure_active)
        self.setCursor(Qt.CrossCursor)
    
    def _ensure_active(self):
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        self.grabMouse()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        mask_color = QColor(0, 0, 0, 150)
        painter.fillRect(self.rect(), mask_color)
        
        if self.is_selecting or not self.selection_rect.isNull():
            if self.is_selecting:
                rect = self._get_current_rect()
            else:
                rect = self.selection_rect
            if not rect.isNull() and rect.width() > 5 and rect.height() > 5:
                painter.setCompositionMode(QPainter.CompositionMode_Clear)
                painter.fillRect(rect, Qt.transparent)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                pen = QPen(QColor(0, 255, 136), 3)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.drawRect(rect)
                corner_size = 15
                painter.setPen(QPen(QColor(0, 255, 136), 3))
                painter.drawLine(rect.topLeft(), rect.topLeft() + QPoint(corner_size, 0))
                painter.drawLine(rect.topLeft(), rect.topLeft() + QPoint(0, corner_size))
                painter.drawLine(rect.topRight(), rect.topRight() + QPoint(-corner_size, 0))
                painter.drawLine(rect.topRight(), rect.topRight() + QPoint(0, corner_size))
                painter.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPoint(corner_size, 0))
                painter.drawLine(rect.bottomLeft(), rect.bottomLeft() + QPoint(0, -corner_size))
                painter.drawLine(rect.bottomRight(), rect.bottomRight() + QPoint(-corner_size, 0))
                painter.drawLine(rect.bottomRight(), rect.bottomRight() + QPoint(0, -corner_size))
                info_text = f"📍 {rect.width()} × {rect.height()} px"
                painter.setPen(Qt.white)
                painter.setFont(QFont("Arial", 14, QFont.Bold))
                text_y = rect.y() - 15 if rect.y() > 40 else rect.y() + rect.height() + 30
                painter.drawText(rect.x() + 10, text_y, info_text)
        else:
            painter.setPen(Qt.white)
            painter.setFont(QFont("Arial", 20, QFont.Bold))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "🖱 按住鼠标左键并拖拽，选择要监控的区域\n\n按 ESC 取消选择"
            )
    
    def _get_current_rect(self):
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
            self.setCursor(Qt.CrossCursor)
    
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
                self.setCursor(Qt.ArrowCursor)
                self.area_selected.emit(
                    rect.x(), rect.y(),
                    rect.width(), rect.height()
                )
                self.close()
            else:
                self.selection_rect = QRect()
                self.update()
                self.setCursor(Qt.CrossCursor)
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.area_selected.emit(0, 0, 0, 0)
            self.close()
    
    def closeEvent(self, event):
        self.releaseMouse()
        self.setCursor(Qt.ArrowCursor)
        event.accept()
