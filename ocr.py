import cv2
import numpy as np


def clean_number(text):

    # 保留数字和小数点
    allowed = "0123456789."

    result = ""

    for c in text:
        if c in allowed:
            result += c

    return result


def read_number(img):

    img = np.array(img)

    # BGRA → GRAY
    gray = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    # 放大（工业屏很重要）
    gray = cv2.resize(gray, None, fx=2.5, fy=2.5)

    # 降噪
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # 二值化（关键）
    _, th = cv2.threshold(
        gray,
        120,
        255,
        cv2.THRESH_BINARY_INV
    )

    # 形态学去噪
    kernel = np.ones((2, 2), np.uint8)
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, kernel)

    # OCR替代：轮廓检测数字块
    contours, _ = cv2.findContours(
        th,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    candidates = []

    for cnt in contours:

        x, y, w, h = cv2.boundingRect(cnt)

        # 过滤噪点
        if w < 5 or h < 10:
            continue

        roi = th[y:y+h, x:x+w]

        # 简单规则判断（数字特征）
        ratio = w / float(h)

        if 0.2 < ratio < 1.5:

            mean_val = cv2.mean(roi)[0]

            if mean_val > 10:

                candidates.append((x, roi))

    # 如果没有识别到
    if not candidates:
        return None

    # 按x排序（从左到右）
    candidates = sorted(candidates, key=lambda x: x[0])

    # 拼接（简化版数字识别）
    text = ""

    for _, roi in candidates:

        # 计算“像素形状”
        h, w = roi.shape

        if h < 10:
            continue

        # 简单规则分类（工业简化识别）
        black_ratio = np.sum(roi == 0) / (h * w + 1)

        if black_ratio > 0.6:
            text += "1"
        else:
            text += "0"

    text = clean_number(text)

    try:
        return float(text)
    except:
        return None
