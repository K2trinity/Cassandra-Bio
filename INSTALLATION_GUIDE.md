# Bio-Short-Seller 安装指南

## Step 1: 环境准备

### 选项 A: 从零开始（推荐）

```powershell
# 1. 创建新的 Python 虚拟环境
python -m venv venv_biomedical

# 2. 激活虚拟环境
.\venv_biomedical\Scripts\Activate.ps1

# 3. 升级 pip
python -m pip install --upgrade pip

# 4. 安装新依赖（轻量级！）
pip install -r requirements.txt

# 5. 验证 Gemini SDK 安装
python -c "import google.generativeai; print('✅ Gemini SDK ready')"
```

### 选项 B: 现有环境清理

```powershell
# ⚠️ 警告：这将卸载所有本地 ML 依赖

# 1. 卸载旧的重量级包
pip uninstall torch torchvision torchaudio transformers sentence-transformers -y
pip uninstall scikit-learn xgboost jieba xhshow -y

# 2. 安装新依赖
pip install -r requirements.txt
```

---

## Step 2: 配置 API 密钥

### 1. 获取 Google API 密钥

访问 [Google AI Studio](https://ai.google.dev/) 并：
1. 点击 "Get API Key"
2. 创建新项目（或选择现有项目）
3. 复制 API 密钥

### 2. 配置环境变量

```powershell
# 复制模板
Copy-Item .env.example .env

# 编辑 .env 文件
notepad .env
```

**最小配置内容：**
```bash
GOOGLE_API_KEY=AIzaSy...your_actual_key_here
HOST=0.0.0.0
PORT=5000
```

---

## Step 3: 验证安装

创建测试脚本 `test_installation.py`：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 Bio-Short-Seller 安装是否正确"""

import os
import sys
from dotenv import load_dotenv

def test_imports():
    """测试核心依赖导入"""
    print("🔍 测试核心依赖...")
    
    try:
        import google.generativeai as genai
        print("✅ google-generativeai")
    except ImportError as e:
        print(f"❌ google-generativeai: {e}")
        return False
    
    try:
        import langgraph
        print("✅ langgraph")
    except ImportError as e:
        print(f"⚠️ langgraph: {e} (可选)")
    
    try:
        import Bio
        print("✅ biopython")
    except ImportError as e:
        print(f"⚠️ biopython: {e} (Step 2 需要)")
    
    try:
        import fitz  # PyMuPDF
        print("✅ pymupdf")
    except ImportError as e:
        print(f"⚠️ pymupdf: {e} (Step 3/4 需要)")
    
    return True


def test_gemini_clients():
    """测试 Gemini 客户端加载"""
    print("\n🔍 测试 Gemini 客户端...")
    
    try:
        from ReportEngine.llms import GeminiClient as ReportGemini
        print("✅ ReportEngine.GeminiClient")
    except Exception as e:
        print(f"❌ ReportEngine: {e}")
        return False
    
    try:
        from QueryEngine.llms import GeminiClient as QueryGemini
        print("✅ QueryEngine.GeminiClient")
    except Exception as e:
        print(f"❌ QueryEngine: {e}")
        return False
    
    try:
        from MediaEngine.llms import GeminiClient as MediaGemini
        print("✅ MediaEngine.GeminiClient")
    except Exception as e:
        print(f"❌ MediaEngine: {e}")
        return False
    
    try:
        from InsightEngine.llms import GeminiClient as EvidenceGemini
        print("✅ EvidenceEngine.GeminiClient")
    except Exception as e:
        print(f"❌ EvidenceEngine: {e}")
        return False
    
    return True


def test_api_connection():
    """测试 Gemini API 连接"""
    print("\n🔍 测试 Gemini API 连接...")
    
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    
    if not api_key:
        print("❌ 未找到 GOOGLE_API_KEY，请配置 .env 文件")
        print("   提示：复制 .env.example 为 .env 并填入您的 API 密钥")
        return False
    
    try:
        from QueryEngine.llms import GeminiClient
        
        client = GeminiClient(
            api_key=api_key,
            model_name="gemini-1.5-flash",
        )
        
        # 简单测试查询
        response = client.generate(
            "What is the chemical formula of aspirin? Answer in 10 words or less.",
            max_output_tokens=50,
        )
        
        if response and len(response) > 0:
            print(f"✅ API 连接成功！响应: {response[:100]}...")
            return True
        else:
            print("❌ API 返回空响应")
            return False
            
    except Exception as e:
        print(f"❌ API 连接失败: {e}")
        print("   可能原因：")
        print("   1. API 密钥无效")
        print("   2. 网络连接问题")
        print("   3. API 配额不足")
        return False


def main():
    print("=" * 60)
    print("  Bio-Short-Seller 安装验证")
    print("=" * 60)
    
    # 运行所有测试
    imports_ok = test_imports()
    if not imports_ok:
        print("\n⚠️ 核心依赖缺失，请运行: pip install -r requirements.txt")
        sys.exit(1)
    
    clients_ok = test_gemini_clients()
    if not clients_ok:
        print("\n⚠️ Gemini 客户端加载失败，请检查代码完整性")
        sys.exit(1)
    
    api_ok = test_api_connection()
    
    print("\n" + "=" * 60)
    if api_ok:
        print("🎉 所有测试通过！Bio-Short-Seller 已准备就绪")
        print("\n下一步：等待指令开始 Step 2 (QueryEngine Transformation)")
    else:
        print("⚠️ 部分测试未通过，请检查上述错误信息")
    print("=" * 60)


if __name__ == "__main__":
    main()
```

运行验证：
```powershell
python test_installation.py
```

---

## 预期输出

```
============================================================
  Bio-Short-Seller 安装验证
============================================================
🔍 测试核心依赖...
✅ google-generativeai
✅ langgraph
✅ biopython
✅ pymupdf

🔍 测试 Gemini 客户端...
✅ ReportEngine.GeminiClient
✅ QueryEngine.GeminiClient
✅ MediaEngine.GeminiClient
✅ EvidenceEngine.GeminiClient

🔍 测试 Gemini API 连接...
✅ API 连接成功！响应: C9H8O4...

============================================================
🎉 所有测试通过！Bio-Short-Seller 已准备就绪

下一步：等待指令开始 Step 2 (QueryEngine Transformation)
============================================================
```

---

## 故障排除

### 问题：`ModuleNotFoundError: No module named 'google.generativeai'`

**解决方案：**
```powershell
pip install google-generativeai
```

### 问题：API 返回 403 错误

**可能原因：**
1. API 密钥无效或过期
2. 未启用 Gemini API（需在 Google Cloud Console 启用）
3. 地区限制（某些地区可能无法访问）

**解决方案：**
- 检查 API 密钥是否正确复制
- 访问 [Google AI Studio](https://ai.google.dev/) 确认密钥有效
- 尝试使用 VPN（如在受限地区）

### 问题：导入 `retry_helper` 失败

这是正常的！`retry_helper` 是项目内部模块，`gemini_client.py` 已包含回退逻辑。

---

## 依赖体积对比

| Before (本地模型) | After (Gemini) |
|-------------------|----------------|
| ~2.6GB            | ~50MB          |
| 需要 GPU          | 仅需 CPU       |
| 离线推理          | 云端 API       |

---

**准备就绪后，等待指令开始 Step 2！**
