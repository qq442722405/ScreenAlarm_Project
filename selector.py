from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPainter, QColor


class ScreenSelector(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowState(Qt.WindowFullScreen)

        # ✔ 关键：允许看到屏幕
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self.start = QPoint()
        self.end = QPoint()
        self.drawing = False

        self.result = None

        self.show()

    def paintEvent(self, e):

        p = QPainter(self)

        # ✔ 超轻遮罩（几乎透明）
        p.fillRect(self.rect(), QColor(0, 0, 0, 30))

        if self.drawing:

            r = QRect(self.start, self.end).normalized()

            p.fillRect(r, QColor(0, 255, 0, 60))
            p.setPen(QColor(0, 255, 0))
            p.drawRect(r)

    def mousePressEvent(self, e):
        self.start = e.position().toPoint()
        self.drawing = True

    def mouseMoveEvent(self, e):
        self.end = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):

        self.drawing = False

        r = QRect(self.start, self.end).normalized()

        self.result = (r.x(), r.y(), r.width(), r.height())

        self.close()
