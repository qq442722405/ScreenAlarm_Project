import base64
import os

def generate_key():
    # 生成32字节随机密钥，并Base64编码为可打印字符串（32字符长度）
    key = base64.b64encode(os.urandom(24)).decode('utf-8')  # 24字节 -> 32字符Base64
    return key

if __name__ == "__main__":
    print("生成的32字节密钥（Base64）：")
    key = generate_key()
    print(key)
    print("\n请将此密钥复制到 main.py 和 license_generator_web.py 中的 SECRET_KEY 变量。")
