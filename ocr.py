import cv2
import numpy as np
from paddleocr import PaddleOCR

ocr = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)


def read_number(img):

    img = np.array(img)

    gray = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    gray = cv2.resize(gray, None, fx=2, fy=2)

    _, th = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)

    result = ocr.ocr(th, cls=False)

    try:
        text = result[0][0][1][0]
        return float(text)
    except:
        return None
