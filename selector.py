from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRect, QPoint
from PySide6.QtGui import QPainter, QColor


class ScreenSelector(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint
        )

        self.setWindowState(Qt.WindowFullScreen)

        self.setAttribute(Qt.WA_TranslucentBackground)

        self.start = QPoint()
        self.end = QPoint()
        self.drawing = False

        self.result = None

        self.show()

    def paintEvent(self, e):

        p = QPainter(self)

        # ✔ 改为“浅遮罩”，不遮死屏幕
        p.fillRect(self.rect(), QColor(0, 0, 0, 60))

        # ✔ 提示文字
        p.setPen(QColor(255, 255, 255))
        p.drawText(50, 50, "拖动鼠标选择区域（ESC退出）")

        if self.drawing:

            r = QRect(self.start, self.end).normalized()

            p.fillRect(r, QColor(0, 255, 0, 60))
            p.setPen(QColor(0, 255, 0))
            p.drawRect(r)

    def mousePressEvent(self, e):
        self.start = e.position().toPoint()
        self.end = self.start
        self.drawing = True

    def mouseMoveEvent(self, e):
        self.end = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):

        self.drawing = False

        r = QRect(self.start, self.end).normalized()

        self.result = (r.x(), r.y(), r.width(), r.height())

        self.close()
