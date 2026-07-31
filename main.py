import os
import sys
from PIL import Image
from paddleocr import PaddleOCR, draw_ocr

# =========================================================
# 1. 自动定位项目根目录与模型路径
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DET_MODEL_DIR = os.path.join(BASE_DIR, "models", "ch_PP-OCRv4_det_infer")
REC_MODEL_DIR = os.path.join(BASE_DIR, "models", "ch_PP-OCRv4_rec_infer")
CLS_MODEL_DIR = os.path.join(BASE_DIR, "models", "ch_ppocr_mobile_v2.0_cls_infer")

# =========================================================
# 2. 初始化 PaddleOCR 推理引擎
# =========================================================
print("🚀 正在加载本地 OCR 模型...")

ocr_engine = PaddleOCR(
    use_angle_cls=True,           # 开启方向分类器（自动纠正旋转/倒置文本）
    lang="ch",                    # 语言：中文
    det_model_dir=DET_MODEL_DIR,  # 本地检测模型路径
    rec_model_dir=REC_MODEL_DIR,  # 本地识别模型路径
    cls_model_dir=CLS_MODEL_DIR,  # 本地分类模型路径
    use_gpu=False,                 # 如果配置了 CUDA 及 paddlepaddle-gpu，可改为 True
    show_log=False                # 屏蔽底层繁琐的调试日志
)

print("✅ 模型加载完成！")

# =========================================================
# 3. 核心 OCR 处理函数
# =========================================================
def run_ocr(img_path: str, save_result_img: bool = True):
    """
    对单张图片执行 OCR 识别
    
    :param img_path: 输入图片的路径
    :param save_result_img: 是否保存画有文本框和识别结果的图片
    """
    if not os.path.exists(img_path):
        print(f"❌ 错误：找不到图片文件 -> {img_path}")
        return

    print(f"\n🔍 正在处理图片: {img_path}")
    
    # 执行识别
    result = ocr_engine.ocr(img_path, cls=True)

    # 判断是否有识别结果
    if not result or not result[0]:
        print("⚠️ 未在图片中检测到有效文本。")
        return

    ocr_res = result[0]
    print(f"✅ 识别成功！共找到 {len(ocr_res)} 处文本框:\n")
    print("-" * 65)
    
    boxes = []
    texts = []
    scores = []

    # 提取并打印识别结果
    for idx, line in enumerate(ocr_res, 1):
        box, (text, score) = line
        boxes.append(box)
        texts.append(text)
        scores.append(score)
        print(f"[{idx:02d}] 文本: {text:<25} | 置信度: {score:.2%}")

    print("-" * 65)

    # 保存可视化图片
    if save_result_img:
        output_dir = os.path.join(BASE_DIR, "output")
        os.makedirs(output_dir, exist_ok=True)
        
        image = Image.open(img_path).convert('RGB')
        # 绘制检测框与文字
        im_show = draw_ocr(image, boxes, texts, scores, font_path=None)
        im_show = Image.fromarray(im_show)
        
        img_name = os.path.basename(img_path)
        save_path = os.path.join(output_dir, f"res_{img_name}")
        im_show.save(save_path)
        print(f"🖼️ 可视化结果已保存至: {save_path}")

# =========================================================
# 4. 主入口
# =========================================================
if __name__ == "__main__":
    # 替换为你项目目录下的测试图片名称
    test_img_path = os.path.join(BASE_DIR, "test.jpg") 

    # 运行 OCR 流程
    run_ocr(test_img_path, save_result_img=True)
