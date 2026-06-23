import cv2
import numpy as np


def read_number(img):

    img = np.array(img)

    gray = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    gray = cv2.resize(gray, None, fx=2.5, fy=2.5)

    _, th = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY)

    contours, _ = cv2.findContours(
        th,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    chars = []

    for c in contours:

        x, y, w, h = cv2.boundingRect(c)

        if h < 10:
            continue

        chars.append((x, w / (h + 1)))

    # ✔ 没识别到直接返回 None（关键修复）
    if len(chars) < 3:
        return None

    # ❌ 防止误识别为 0
    value = len(chars)

    return float(value)
