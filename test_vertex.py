import os
import sys
from dotenv import load_dotenv

# 加载 .env 环境变量
load_dotenv(override=True)

# 显式配置刚才生成的 credentials 路径
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"C:\Users\16830\AppData\Roaming\gcloud\application_default_credentials.json"

# 将当前目录添加到 PYTHONPATH，以便能导入 src 模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.llms.gemini_client import GeminiClient

def main():
    print("=== Testing Vertex AI Gemini Client ===")
    try:
        # 使用配置好的 GeminiClient，它内部默认通过 ADC 认证去调用 Vertex AI
        client = GeminiClient(model_name="gemini-2.5-flash") # 使用一个小模型快速测试
        
        print("\n[Configuration]")
        info = client.get_model_info()
        for k, v in info.items():
            print(f"- {k}: {v}")
            
        print("\n[Task] 向模型发送测试 Prompt: '请随机说一个关于生物化学的冷笑话'")
        
        # 调用生成接口
        response = client.generate_content("请随机说一个关于生物化学的冷笑话")
        
        print("\n[Response]")
        print(response)
        
        print("\n=== 测试成功完成 ===")
        print("提醒: 你可以通过去 Google Cloud Platform (GCP) 的控制台：")
        print("1. 查看 Billing (结算) 页面，确认是否产生了消耗")
        print("2. 查看 Vertex AI -> API 监控指标，确认是否有 API 调用记录，以判断是否走的是 Vertex AI 卡内额度。")
    except Exception as e:
        print(f"\n[Error] {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()
