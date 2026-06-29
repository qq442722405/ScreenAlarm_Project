def _preprocess_image(self, img_np, sensitivity):
    """优化预处理：对大尺寸图像不再放大，调整二值化参数"""
    try:
        sens = sensitivity
        clip_limit = 1.0 + (sens / 10.0) * 2.0
        # 动态计算块大小（与图像尺寸相关）
        h, w = img_np.shape[:2]
        # 如果图像宽高大于200像素，认为字体较大，不放大或缩小
        if max(h, w) > 200:
            scale = 1.0
        else:
            scale = 3.0  # 小图放大
        # 如果图像太大（>500），缩小以加快处理
        if max(h, w) > 500:
            scale = 0.5

        # 缩放
        if scale != 1.0:
            new_w = int(w * scale)
            new_h = int(h * scale)
            scaled = cv2.resize(img_np, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        else:
            scaled = img_np

        if len(scaled.shape) == 3:
            gray = cv2.cvtColor(scaled, cv2.COLOR_RGB2GRAY)
        else:
            gray = scaled

        # CLAHE 增强
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        if np.mean(enhanced) < 80:
            enhanced = 255 - enhanced
            enhanced = clahe.apply(enhanced)

        # 锐化
        kernel_sharpen = np.array([[-1,-1,-1],[-1,9,-1],[-1,-1,-1]])
        sharpened = cv2.filter2D(enhanced, -1, kernel_sharpen)

        # 自适应二值化：块大小根据图像尺寸调整
        if max(h, w) > 200:
            block_size = max(3, int(5 + (10 - sens) * 1.0))  # 减小块大小
            c_value = max(1, int(2 + (10 - sens) * 0.3))
        else:
            block_size = max(3, int(5 + (10 - sens) * 1.5))
            c_value = max(1, int(2 + (10 - sens) * 0.5))

        if block_size % 2 == 0:
            block_size += 1
        binary = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, block_size, c_value)
        kernel = np.ones((2,2), np.uint8)
        cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)
        rgb = cv2.cvtColor(cleaned, cv2.COLOR_GRAY2RGB)
        return rgb
    except Exception:
        return img_np
