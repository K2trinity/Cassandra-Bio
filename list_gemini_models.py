"""
查询 Google Gemini API 可用的模型列表
"""

import os
from config import settings

try:
    import google.generativeai as genai
    
    # 配置 API 密钥
    api_key = settings.GOOGLE_API_KEY or os.getenv('GOOGLE_API_KEY')
    
    if not api_key:
        print("❌ 错误: GOOGLE_API_KEY 未设置")
        print("请在 .env 文件中设置: GOOGLE_API_KEY=your_api_key")
        exit(1)
    
    genai.configure(api_key=api_key)
    
    print("=" * 80)
    print("🔍 查询 Google Gemini API 可用模型...")
    print("=" * 80)
    
    # 列出所有可用模型
    models = genai.list_models()
    
    print("\n📋 所有可用模型:")
    print("-" * 80)
    
    for model in models:
        # 检查是否支持 generateContent
        if 'generateContent' in model.supported_generation_methods:
            print(f"\n✅ {model.name}")
            print(f"   显示名称: {model.display_name}")
            print(f"   描述: {model.description}")
            print(f"   支持的方法: {', '.join(model.supported_generation_methods)}")
            print(f"   输入token限制: {model.input_token_limit:,}")
            print(f"   输出token限制: {model.output_token_limit:,}")
    
    print("\n" + "=" * 80)
    print("💡 建议使用的模型名称 (去掉 'models/' 前缀):")
    print("=" * 80)
    
    for model in models:
        if 'generateContent' in model.supported_generation_methods:
            model_name = model.name.replace('models/', '')
            print(f"   • {model_name}")
    
    print("\n" + "=" * 80)
    
except ImportError:
    print("❌ 错误: google-generativeai 未安装")
    print("请运行: pip install google-generativeai")
except Exception as e:
    print(f"❌ 错误: {e}")
    import traceback
    traceback.print_exc()
