import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from selector import ScreenSelector


def on_selected(x, y, w, h):
    QMessageBox.information(
        None,
        "选择结果",
        f"X:{x}\nY:{y}\nW:{w}\nH:{h}"
    )


if __name__ == "__main__":
    app = QApplication(sys.argv)

    selector = ScreenSelector()
    selector.area_selected.connect(on_selected)
    selector.show()

    sys.exit(app.exec())
