import cv2
import numpy as np


def read_number(img):

    img = np.array(img)

    gray = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    gray = cv2.resize(gray, None, fx=2.5, fy=2.5)

    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    _, th = cv2.threshold(
        gray,
        120,
        255,
        cv2.THRESH_BINARY
    )

    # 提取轮廓
    contours, _ = cv2.findContours(
        th,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    chars = []

    for c in contours:

        x, y, w, h = cv2.boundingRect(c)

        if h < 10 or w < 3:
            continue

        roi = th[y:y+h, x:x+w]

        ratio = w / float(h)

        if 0.1 < ratio < 1.5:
            chars.append((x, roi))

    if not chars:
        return None

    chars = sorted(chars, key=lambda x: x[0])

    text = ""

    for _, roi in chars:

        h, w = roi.shape

        black = np.sum(roi == 0)
        total = h * w + 1

        if black / total > 0.5:
            text += "1"
        else:
            text += "0"

    try:
        return float(text)
    except:
        return None
