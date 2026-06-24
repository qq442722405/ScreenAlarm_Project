from PySide6.QtWidgets import QWidget, QLabel
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont


class ScreenSelector(QWidget):
    area_selected = Signal(int, int, int, int)
    
    def __init__(self):
        super().__init__()
        from PySide6.QtWidgets import QApplication
        screens = QApplication.screens()
        total_rect = QRect(0, 0, 0, 0)
        for s in screens:
            total_rect = total_rect.united(s.geometry())
        
        self.setGeometry(total_rect)
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setMouseTracking(True)
        
        self.is_selecting = False
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.selection_rect = QRect()
        
        self.label = QLabel("按住左键拖拽选择区域，松开确认 | ESC取消", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                background: rgba(0,0,0,180);
                padding: 12px 24px;
                border-radius: 12px;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        self.label.adjustSize()
        self.label.move(
            (self.width() - self.label.width()) // 2,
            self.height() - self.label.height() - 50
        )
        
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(100, self._ensure_active)
        self.setCursor(Qt.CrossCursor)
    
    def _ensure_active(self):
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        
        if self.is_selecting or not self.selection_rect.isNull():
            rect = self.selection_rect if not self.is_selecting else self._get_current_rect()
            if rect.width() > 5 and rect.height() > 5:
                painter.setCompositionMode(QPainter.CompositionMode_Clear)
                painter.fillRect(rect, Qt.transparent)
                painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                
                pen = QPen(QColor(0, 255, 136), 2)
                pen.setStyle(Qt.DashLine)
                painter.setPen(pen)
                painter.drawRect(rect)
                
                painter.setPen(QPen(QColor(0, 255, 136), 2))
                size = 10
                for p in [rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()]:
                    painter.drawLine(p, p + QPoint(size, 0) if p.x() == rect.left() else p + QPoint(-size, 0))
                    painter.drawLine(p, p + QPoint(0, size) if p.y() == rect.top() else p + QPoint(0, -size))
                
                painter.setPen(Qt.white)
                painter.setFont(QFont("Arial", 12))
                painter.drawText(
                    rect.x() + 10,
                    rect.y() - 10 if rect.y() > 30 else rect.y() + rect.height() + 20,
                    f"{rect.width()} × {rect.height()}"
                )
        else:
            painter.setPen(Qt.white)
            painter.setFont(QFont("Arial", 18))
            painter.drawText(
                self.rect(),
                Qt.AlignCenter,
                "按住鼠标左键并拖拽选择监控区域\n\n按 ESC 取消"
            )
    
    def _get_current_rect(self):
        if not self.is_selecting:
            return self.selection_rect
        x = min(self.start_point.x(), self.end_point.x())
        y = min(self.start_point.y(), self.end_point.y())
        return QRect(x, y, abs(self.end_point.x() - self.start_point.x()), abs(self.end_point.y() - self.start_point.y()))
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_selecting = True
            self.start_point = event.position().toPoint()
            self.end_point = self.start_point
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
                self.area_selected.emit(rect.x(), rect.y(), rect.width(), rect.height())
                self.close()
            else:
                self.update()
    
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.area_selected.emit(0, 0, 0, 0)
            self.close()
    
    def closeEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        event.accept()
