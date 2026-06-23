import sys
from PySide6.QtWidgets import QApplication, QWidget, QLabel
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QFont


class ScreenSelector(QWidget):

    area_selected = Signal(int, int, int, int)

    def __init__(self):
        super().__init__()

        # ======================
        # 全屏覆盖所有屏幕
        # ======================
        screens = QApplication.screens()
        total_rect = QRect(0, 0, 0, 0)

        for s in screens:
            total_rect = total_rect.united(s.geometry())

        self.setGeometry(total_rect)

        self.setWindowTitle("选择监控区域")

        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.Tool
        )

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)

        # ======================
        # 强制激活窗口（EXE关键修复）
        # ======================
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

        self.setWindowState(Qt.WindowFullScreen | Qt.WindowActive)

        QTimer.singleShot(100, self._force_focus)

        # ======================
        # 状态变量
        # ======================
        self.is_selecting = False
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.selection_rect = QRect()

        # ======================
        # 提示文字
        # ======================
        self.label = QLabel("🖱 拖动鼠标选择区域，ESC取消", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                background: rgba(0,0,0,180);
                padding: 10px;
                font-size: 16px;
                border-radius: 8px;
            }
        """)
        self.label.adjustSize()

        self.label.move(
            (self.width() - self.label.width()) // 2,
            self.height() - 80
        )

        self.setCursor(Qt.CrossCursor)

    # ======================
    # 强制前置
    # ======================
    def _force_focus(self):
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)

    # ======================
    # 绘制遮罩 + 框选
    # ======================
    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 半透明遮罩
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))

        rect = self._get_current_rect()

        if not rect.isNull():

            # ======================
            # ⚠ 修复点：不要用 CompositionMode_Clear
            # EXE环境会失效
            # ======================
            painter.fillRect(rect, QColor(0, 255, 136, 60))

            pen = QPen(QColor(0, 255, 136), 3)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(rect)

            # 坐标信息
            painter.setPen(Qt.white)
            painter.setFont(QFont("Arial", 12))
            painter.drawText(
                rect.x(),
                rect.y() - 10,
                f"{rect.width()}x{rect.height()}"
            )

    # ======================
    # 当前框选区域
    # ======================
    def _get_current_rect(self):

        if not self.is_selecting:
            return self.selection_rect

        x = min(self.start_point.x(), self.end_point.x())
        y = min(self.start_point.y(), self.end_point.y())
        w = abs(self.start_point.x() - self.end_point.x())
        h = abs(self.start_point.y() - self.end_point.y())

        return QRect(x, y, w, h)

    # ======================
    # 鼠标事件
    # ======================
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

            if rect.width() > 10 and rect.height() > 10:

                self.selection_rect = rect
                self.update()

                self.area_selected.emit(
                    rect.x(),
                    rect.y(),
                    rect.width(),
                    rect.height()
                )

            self.close()

    # ======================
    # ESC取消
    # ======================
    def keyPressEvent(self, event):

        if event.key() == Qt.Key_Escape:
            self.area_selected.emit(0, 0, 0, 0)
            self.close()

    def closeEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        event.accept()
