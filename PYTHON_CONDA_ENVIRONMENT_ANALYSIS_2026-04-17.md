# Cassandra Python 与 Conda 环境全面分析总结

生成时间：2026-04-17
适用项目：Cassandra

## 1. 问题背景

近期运行日志出现以下关键现象：

- 大量重复错误：spacy / scispacy not installed
- HTMLRenderer 警告：未配置任何 LLM API，图表 API 修复功能不可用
- PDF 高级渲染降级：WeasyPrint/Pango dependency check failed

这些日志容易被误判为“依赖没装”，但实际属于“运行解释器与已安装依赖不在同一环境”的典型问题。

## 2. 一句话结论

本次问题的根因是环境错位：

- VS Code/Pylance 当前解释器是 Python311（依赖齐全）
- 实际运行 app.py 的进程是 Miniconda base（依赖不全）
- 因此运行时持续报 spacy/scispacy 缺失

## 3. 关键证据

### 3.1 当前运行进程解释器

已确认运行 app.py 的 Python 进程为：

- F:\miniconda\python.exe app.py

说明应用实际跑在 Miniconda base，而不是 Python311。

### 3.2 Shell 默认命令映射

终端命令解析结果：

- python -> F:\miniconda\python.exe
- pip -> F:\miniconda\Scripts\pip.exe

PATH 前序由 Miniconda 主导，导致直接输入 python 会优先命中 base 环境。

### 3.3 VS Code 当前解释器

VS Code Python 环境查询显示当前解释器为：

- C:\Users\16830\AppData\Local\Programs\Python\Python311\python.exe

这与终端默认 python 不一致，形成“编辑器一个环境、运行另一个环境”的错位。

### 3.4 三套环境核心依赖对比

环境 A：Miniconda base

- Python 3.13.11
- spacy: False
- scispacy: False
- weasyprint: False
- flask/langgraph: True

环境 B：Conda cassandra311

- Python 3.11.15
- spacy: False
- scispacy: False
- weasyprint: False
- flask/langgraph: False（未完整装好）

环境 C：独立 Python311

- Python 3.11.9
- spacy: True
- scispacy: True
- SciSpacy 模型可加载（en_ner_bionlp13cg_md）
- weasyprint: True
- flask/langgraph: True

结论：当前最可用的是独立 Python311。

### 3.5 为什么日志会重复刷出

在目标归一化与文本处理流程中，SciSpacy 的 fallback 调用频次较高。
当运行时环境缺少 spacy 时，每次触发都会报同一错误，形成连续刷屏。

## 4. 关于 HTMLRenderer 警告的判断

该警告并非纯环境故障，当前代码策略本身就会触发。

原因：

- 图表修复函数工厂当前返回空列表
- 因此 HTMLRenderer 初始化时会记录“未配置任何 LLM API”警告

这属于“可预期降级提示”，并不等价于主流程崩溃。

## 5. 关于 pip 安装提示为何“总是出现”

日志提示“Run: pip install spacy scispacy”本身没有错，但在你当前实际运行路径下有两个现实问题：

1) 你看到提示时应用跑在 Miniconda base
- 若你把包装到 Python311，运行进程仍在 base，则错误仍会出现

2) Miniconda base 是 Python 3.13
- spaCy 相关链路在该环境下存在编译与兼容风险
- 实测 dry-run 已出现构建依赖失败（thinc/blis 构建失败）

所以“反复提示安装”的本质并不是你没装过，而是装在了另一个解释器，且当前运行环境对这套包还不友好。

## 6. 配置层状态补充

已做不泄露密钥的键存在性检查，结果如下：

- GOOGLE_CLOUD_PROJECT: 已设置
- GOOGLE_CLOUD_LOCATION: 已设置
- TAVILY_API_KEY: 已设置
- OPENAI_API_KEY: 未设置
- ANTHROPIC_API_KEY: 未设置
- GEMINI_API_KEY: 未设置
- SCISPACY_MODEL_NAME: 未显式设置（代码有默认值）
- SCISPACY_MODEL_VERSION: 未显式设置（代码有默认值）

说明：

- SciSpacy 模型名与版本即便未在 .env 显式配置，仍可使用 config.py 默认值
- HTMLRenderer 的“未配置任何 LLM API”在当前实现下仍可能出现，即使已有 Vertex/Google 配置

## 7. 风险评估

当前风险等级：中

主要风险点：

- 运行环境不一致导致结果不可复现
- 团队成员按 README 直接执行 python app.py 时，可能因 PATH 差异得到不同结果
- Conda cassandra311 目前并非可直接运行的完整环境

## 8. 推荐修复方案

### 方案 A（推荐，最快恢复稳定）

统一使用独立 Python311 作为唯一运行解释器。

执行建议：

1. 安装依赖
- C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pip install -r requirements.txt

2. 启动应用
- C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe app.py

3. 运行测试
- C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe -m pytest tests

### 方案 B（Conda 统一化）

若必须使用 Conda，则统一迁移到 cassandra311 并补齐全部依赖。

执行建议：

1. 激活环境
- conda activate cassandra311

2. 安装依赖
- python -m pip install -r requirements.txt

3. 专项补齐
- python -m pip install spacy==3.7.5 scispacy==0.5.5

4. 启动与验证
- python app.py
- python -m pytest tests

### 方案 C（组织级治理）

- 固定工作区默认解释器到项目唯一 Python
- 约束所有启动脚本使用明确解释器路径
- 在 CI 加入启动前环境体检（检查 sys.executable、spacy/scispacy/weasyprint）

## 9. 建议的长期规范

1) 单项目单解释器
- 明确写入项目文档与脚本，避免使用裸 python 命令

2) 启动前自检
- 启动时打印解释器路径与关键依赖存在性

3) 日志降噪
- 对同类依赖缺失错误增加节流或只首报，避免日志刷屏

4) 文档对齐
- README 中运行命令改为显式解释器或先激活受控环境

## 10. 最终结论

这次异常本质是环境治理问题，不是业务代码逻辑故障：

- SciSpacy 报错由运行解释器错位触发
- HTMLRenderer LLM 警告为当前实现下的预期降级提示
- 若统一到 Python 3.11 且保持解释器一致，问题可稳定消失
