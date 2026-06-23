from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QPoint, Signal
from PySide6.QtGui import QPainter, QColor


class ScreenSelector(QWidget):

    area_selected = Signal(int, int, int, int)

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )

        self.setWindowState(Qt.WindowFullScreen)

        self.setAttribute(Qt.WA_TranslucentBackground)

        self.start = QPoint()
        self.end = QPoint()
        self.drawing = False

        self.show()

    def paintEvent(self, event):

        painter = QPainter(self)

        # 半透明黑遮罩
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        if self.drawing:
            rect = QRect(self.start, self.end).normalized()

            # 绿色框（最稳定画法）
            painter.fillRect(rect, QColor(0, 255, 0, 80))

            painter.setPen(QColor(0, 255, 0))
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start = event.position().toPoint()
            self.end = self.start
            self.drawing = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.drawing:
            self.end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.drawing:
            self.drawing = False

            rect = QRect(self.start, self.end).normalized()

            self.area_selected.emit(
                rect.x(),
                rect.y(),
                rect.width(),
                rect.height()
            )

            self.close()
