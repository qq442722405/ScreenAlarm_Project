import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from main_window import MainWindow


if __name__ == "__main__":

    app = QApplication(sys.argv)

    # ✔ 防止ICO路径错误导致EXE崩溃
    try:
        app.setWindowIcon(QIcon("icon.ico"))
    except:
        pass

    win = MainWindow()
    win.show()

    sys.exit(app.exec())
