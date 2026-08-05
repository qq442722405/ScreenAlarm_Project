import sys
from PySide6.QtWidgets import QApplication
# 模块化导入
from core.controller import GlobalControlPanel

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    panel = GlobalControlPanel()
    panel.show()
    sys.exit(app.exec())
