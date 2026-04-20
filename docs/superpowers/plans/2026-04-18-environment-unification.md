# Cassandra 环境统一化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 Cassandra 项目的 Python 环境错位问题——统一到独立 Python 3.11 作为唯一运行解释器，并增加启动前自检、日志降噪和文档对齐。

**Architecture:** 分四层推进：(1) VS Code 配置层——将解释器指向 Python311；(2) 运行时自检层——app.py 启动时验证解释器和关键依赖；(3) 日志降噪层——对 SciSpacy/HTMLRenderer 重复警告做节流；(4) 文档层——README 和 .env.example 对齐显式解释器路径。

**Tech Stack:** Python 3.11.9 (独立安装), Flask, spaCy/SciSpacy, WeasyPrint, VS Code workspace settings

---

## 文件变更清单

| 操作 | 文件路径 | 职责 |
|------|----------|------|
| 修改 | `.vscode/settings.json` | 解释器指向 Python311 |
| 修改 | `.vscode/launch.json` | 调试配置显式指定 Python311 |
| 新建 | `scripts/check_env.py` | 独立环境自检脚本 |
| 修改 | `app.py` (行 2503-2523) | 启动入口增加环境自检调用 |
| 修改 | `src/tools/scispacy_ner_service.py` (行 203-209) | spacy 导入失败日志降噪 |
| 修改 | `src/engines/report_engine/renderers/html_renderer.py` (行 121-126) | HTMLRenderer 警告降级为单次 info |
| 修改 | `README.md` | 运行命令对齐显式解释器 |
| 修改 | `.env.example` | 补充 PYTHON_EXECUTABLE 说明 |

---

## Task 1: 修正 VS Code 解释器配置

**Files:**
- Modify: `.vscode/settings.json:3`
- Modify: `.vscode/launch.json:1-36`

- [ ] **Step 1: 修改 settings.json 解释器路径**

将 `python.defaultInterpreterPath` 从 Miniconda 改为独立 Python311：

```json
{
    "python.defaultInterpreterPath": "C:\\Users\\16830\\AppData\\Local\\Programs\\Python\\Python311\\python.exe",
    "python.condaPath": "F:\\miniconda\\Scripts\\conda.exe",
    "python.terminal.activateEnvironment": false,
    "python.terminal.activateEnvInCurrentTerminal": false,
    "python.analysis.extraPaths": [
        "${workspaceFolder}/src",
        "${workspaceFolder}/Harvest",
        "${workspaceFolder}/EvidenceEngine",
        "${workspaceFolder}/ForensicEngine"
    ],
    "python.envFile": "${workspaceFolder}/.env",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": false,
    "python.linting.flake8Enabled": true,
    "python.formatting.provider": "black",
    "terminal.integrated.env.windows": {
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8"
    },
    "terminal.integrated.env.linux": {
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8"
    },
    "terminal.integrated.env.osx": {
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8"
    },
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true
    },
    "[python]": {
        "editor.defaultFormatter": "ms-python.black-formatter",
        "editor.formatOnSave": false,
        "editor.codeActionsOnSave": {
            "source.organizeImports": "never"
        }
    }
}
```

关键变更：
- 第 3 行：`F:\\miniconda\\python.exe` → `C:\\Users\\16830\\AppData\\Local\\Programs\\Python\\Python311\\python.exe`
- 第 5-6 行：`activateEnvironment` 和 `activateEnvInCurrentTerminal` 改为 `false`（避免 Conda 自动激活覆盖解释器）

- [ ] **Step 2: 修改 launch.json 添加显式 pythonPath**

在两个调试配置中都添加 `python` 字段，确保调试时也使用 Python311：

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Cassandra: Run app.py",
            "type": "python",
            "request": "launch",
            "python": "C:\\Users\\16830\\AppData\\Local\\Programs\\Python\\Python311\\python.exe",
            "program": "${workspaceFolder}/app.py",
            "console": "integratedTerminal",
            "justMyCode": false,
            "env": {
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8"
            },
            "args": [],
            "cwd": "${workspaceFolder}"
        },
        {
            "name": "Cassandra: Debug app.py",
            "type": "python",
            "request": "launch",
            "python": "C:\\Users\\16830\\AppData\\Local\\Programs\\Python\\Python311\\python.exe",
            "program": "${workspaceFolder}/app.py",
            "console": "integratedTerminal",
            "justMyCode": false,
            "stopOnEntry": false,
            "env": {
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8"
            },
            "args": [],
            "cwd": "${workspaceFolder}"
        }
    ]
}
```

- [ ] **Step 3: 验证配置生效**

Run: 在 VS Code 中按 `Ctrl+Shift+P` → "Python: Select Interpreter"，确认列表中 Python311 已被选中。

然后在 VS Code 终端中执行：
```bash
python -c "import sys; print(sys.executable)"
```
Expected: `C:\Users\16830\AppData\Local\Programs\Python\Python311\python.exe`

- [ ] **Step 4: Commit**

```bash
git add .vscode/settings.json .vscode/launch.json
git commit -m "fix: unify VS Code interpreter to standalone Python 3.11"
```

---

## Task 2: 创建独立环境自检脚本

**Files:**
- Create: `scripts/check_env.py`

- [ ] **Step 1: 创建 scripts 目录**

```bash
mkdir -p scripts
```

- [ ] **Step 2: 编写 check_env.py**

```python
"""
Cassandra 启动前环境自检。
可独立运行，也可被 app.py 导入调用。
返回 (ok: bool, report: list[str])。
"""
import sys
import importlib


REQUIRED_PACKAGES = {
    "flask": "flask",
    "langgraph": "langgraph",
    "loguru": "loguru",
    "pydantic_settings": "pydantic-settings",
}

OPTIONAL_PACKAGES = {
    "spacy": "spacy",
    "weasyprint": "weasyprint",
}

EXPECTED_PYTHON = (3, 11)


def run_check() -> tuple[bool, list[str]]:
    report: list[str] = []
    ok = True

    report.append(f"Python executable : {sys.executable}")
    report.append(f"Python version    : {sys.version.split()[0]}")

    if sys.version_info[:2] != EXPECTED_PYTHON:
        report.append(
            f"⚠ Expected Python {EXPECTED_PYTHON[0]}.{EXPECTED_PYTHON[1]}, "
            f"got {sys.version_info[0]}.{sys.version_info[1]}"
        )
        ok = False

    for mod, pip_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(mod)
            report.append(f"  ✓ {pip_name}")
        except ImportError:
            report.append(f"  ✗ {pip_name}  (MISSING — pip install {pip_name})")
            ok = False

    for mod, pip_name in OPTIONAL_PACKAGES.items():
        try:
            importlib.import_module(mod)
            report.append(f"  ✓ {pip_name} (optional)")
        except ImportError:
            report.append(f"  ~ {pip_name} (optional, not installed)")

    return ok, report


if __name__ == "__main__":
    ok, lines = run_check()
    header = "✅ Environment OK" if ok else "❌ Environment has issues"
    print(f"\n{'='*60}")
    print(f"  Cassandra Environment Check — {header}")
    print(f"{'='*60}")
    for line in lines:
        print(f"  {line}")
    print(f"{'='*60}\n")
    sys.exit(0 if ok else 1)
```

- [ ] **Step 3: 运行自检脚本验证**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" scripts/check_env.py
```
Expected: 输出 `✅ Environment OK`，Python 版本显示 3.11.x，所有 REQUIRED 包显示 ✓。

- [ ] **Step 4: 用 Miniconda 运行验证它能检测到问题**

Run:
```bash
"F:/miniconda/python.exe" scripts/check_env.py
```
Expected: 输出 `❌ Environment has issues`，Python 版本显示 3.13.x 并报 ⚠ 版本不匹配。

- [ ] **Step 5: Commit**

```bash
git add scripts/check_env.py
git commit -m "feat: add standalone environment check script"
```

---

## Task 3: app.py 启动入口集成环境自检

**Files:**
- Modify: `app.py:2503-2523`

- [ ] **Step 1: 在 app.py 入口添加自检调用**

将 `app.py` 的 `if __name__ == '__main__':` 块替换为：

```python
if __name__ == '__main__':
    # ── Environment sanity check ──────────────────────────────────
    from scripts.check_env import run_check
    _env_ok, _env_lines = run_check()
    for _line in _env_lines:
        logger.info(_line)
    if not _env_ok:
        logger.error("❌ Environment check failed. Fix issues above before starting.")
        sys.exit(1)

    logger.info("="*80)
    logger.info("🧬 Cassandra - Biomedical Research Workflow Platform")
    logger.info("="*80)
    logger.info(f"🌐 Server: http://0.0.0.0:{config.PORT}")
    logger.info(f"📊 Neo4j Available: {NEO4J_AVAILABLE}")
    logger.info(f"🔬 LangGraph Workflow: ✅ Loaded")
    logger.info("="*80)

    # Create required directories
    Path("final_reports").mkdir(exist_ok=True)
    Path("uploads").mkdir(exist_ok=True)

    # Start Flask-SocketIO server
    socketio.run(
        app,
        host=config.HOST,
        port=config.PORT,
        debug=False,
        allow_unsafe_werkzeug=True
    )
```

- [ ] **Step 2: 确保 scripts 目录可被导入**

创建 `scripts/__init__.py`（空文件）：

```bash
touch scripts/__init__.py
```

- [ ] **Step 3: 验证启动自检生效**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -c "
import sys; sys.path.insert(0, '.')
from scripts.check_env import run_check
ok, lines = run_check()
for l in lines: print(l)
print('OK' if ok else 'FAIL')
"
```
Expected: 输出所有依赖状态，最后一行 `OK`。

- [ ] **Step 4: Commit**

```bash
git add app.py scripts/__init__.py
git commit -m "feat: integrate environment check into app.py startup"
```

---

## Task 4: SciSpacy 导入失败日志降噪

**Files:**
- Modify: `src/tools/scispacy_ner_service.py:161-167` (添加类属性)
- Modify: `src/tools/scispacy_ner_service.py:203-209` (修改 import 错误处理)

- [ ] **Step 1: 在 SciSpacyNERService 类中添加警告节流标志**

在 `src/tools/scispacy_ner_service.py` 的 `__init__` 方法中添加标志：

找到现有代码（约第 164-167 行）：
```python
    def __init__(self) -> None:
        self._nlp: Any = None
        self._model_name: str = "en_ner_bionlp13cg_md"  # overridden by config if available
        self._model_version: str = "0.5.4"
```

替换为：
```python
    def __init__(self) -> None:
        self._nlp: Any = None
        self._model_name: str = "en_ner_bionlp13cg_md"
        self._model_version: str = "0.5.4"
        self._import_error_logged: bool = False
```

- [ ] **Step 2: 修改 _ensure_loaded 中的 ImportError 处理**

找到现有代码（约第 203-209 行）：
```python
        try:
            import spacy
        except ImportError:
            logger.error(
                "❌ spacy / scispacy not installed. Run: pip install spacy scispacy"
            )
            raise
```

替换为：
```python
        try:
            import spacy
        except ImportError:
            if not self._import_error_logged:
                logger.error(
                    "❌ spacy / scispacy not installed. Run: pip install spacy scispacy"
                )
                self._import_error_logged = True
            raise
```

- [ ] **Step 3: 验证降噪效果**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -c "
from src.tools.scispacy_ner_service import SciSpacyNERService
svc = SciSpacyNERService.get_instance()
# 如果 spacy 已安装，这会正常加载；如果未安装，只会报一次错
try:
    svc.extract_entities('test EGFR mutation')
    print('SciSpacy loaded OK')
except ImportError:
    print('ImportError raised (expected if spacy not installed)')
except Exception as e:
    print(f'Other error: {e}')
"
```
Expected: 如果 spacy 已安装，输出 `SciSpacy loaded OK`。如果未安装，只输出一次 ❌ 错误。

- [ ] **Step 4: Commit**

```bash
git add src/tools/scispacy_ner_service.py
git commit -m "fix: throttle repeated spacy import-error log to once"
```

---

## Task 5: HTMLRenderer 警告降级

**Files:**
- Modify: `src/engines/report_engine/renderers/html_renderer.py:121-126`

- [ ] **Step 1: 将 HTMLRenderer LLM 警告从 warning 降为 info**

找到现有代码（约第 121-126 行）：
```python
        # 打印LLM修复函数状态
        self._llm_repair_count = len(llm_repair_fns)
        if not llm_repair_fns:
            logger.warning("HTMLRenderer: 未配置任何LLM API，图表API修复功能不可用")
        else:
            logger.info(f"HTMLRenderer: 已配置 {len(llm_repair_fns)} 个LLM修复函数")
```

替换为：
```python
        self._llm_repair_count = len(llm_repair_fns)
        if not llm_repair_fns:
            logger.info("HTMLRenderer: 图表API修复未启用（无LLM配置，属预期降级）")
        else:
            logger.info(f"HTMLRenderer: 已配置 {len(llm_repair_fns)} 个LLM修复函数")
```

变更说明：
- `logger.warning` → `logger.info`：因为这是预期降级，不是异常
- 消息文案加了"属预期降级"，避免被误判为故障
- 删除了中文注释行（代码自解释）

- [ ] **Step 2: 验证日志级别变更**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -c "
import sys; sys.path.insert(0, '.')
from loguru import logger
logger.remove()
logger.add(sys.stderr, level='DEBUG')
from src.engines.report_engine.renderers.html_renderer import HTMLRenderer
r = HTMLRenderer()
print(f'LLM repair count: {r._llm_repair_count}')
"
```
Expected: 日志中出现 `INFO` 级别的"图表API修复未启用"，而非 `WARNING`。

- [ ] **Step 3: Commit**

```bash
git add src/engines/report_engine/renderers/html_renderer.py
git commit -m "fix: downgrade HTMLRenderer LLM warning to info (expected degradation)"
```

---

## Task 6: 文档对齐——README 和 .env.example

**Files:**
- Modify: `README.md:29-74`
- Modify: `.env.example`

- [ ] **Step 1: 更新 README.md Quick Start 部分**

找到现有的 Quick Start 部分（约第 29-74 行）：
```markdown
## Quick Start

### 1) Prerequisites

- Python 3.9+
- Google Cloud project with Vertex AI enabled
- `gcloud` CLI configured for ADC

### 2) Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3) Configure

```bash
copy .env.example .env
```

Set at least:

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`

Authenticate locally:

```bash
gcloud auth application-default login
```

### 4) Run

Web app:

```bash
python app.py
```

CLI run:

```bash
python main.py "summarize latest progress on EGFR inhibitors in NSCLC"
```
```

替换为：
```markdown
## Quick Start

### 1) Prerequisites

- Python 3.11（推荐使用独立安装版，不要使用 Conda base）
- Google Cloud project with Vertex AI enabled
- `gcloud` CLI configured for ADC

### 2) Install

```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pip install -r requirements.txt
```

> **注意：** 请始终使用显式解释器路径，避免裸 `python` 命令（可能命中 Conda base 而非 Python311）。

### 3) Environment Check

```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" scripts/check_env.py
```

确认输出 `✅ Environment OK` 后再继续。

### 4) Configure

```bash
copy .env.example .env
```

Set at least:

- `GOOGLE_CLOUD_PROJECT`
- `GOOGLE_CLOUD_LOCATION`

Authenticate locally:

```bash
gcloud auth application-default login
```

### 5) Run

Web app:

```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" app.py
```

CLI run:

```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" main.py "summarize latest progress on EGFR inhibitors in NSCLC"
```
```

- [ ] **Step 2: 更新 README.md Testing 部分**

找到现有的 Testing 部分（约第 121-134 行）：
```markdown
## Testing

Run full tests:

```bash
pytest tests
```

Run selected integrity checks:

```bash
python -m pytest tests/test_dataflow_integrity.py
python -m pytest tests/test_report_engine_sanitization.py
```
```

替换为：
```markdown
## Testing

Run full tests:

```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests
```

Run selected integrity checks:

```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_dataflow_integrity.py
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_report_engine_sanitization.py
```
```

- [ ] **Step 3: 在 .env.example 顶部添加解释器说明**

在 `.env.example` 文件顶部（第 1 行之前）插入：

```bash
# ========================================
#   Cassandra Configuration
#   All Intelligence -> Google Gemini
# ========================================
#
# ⚠ 重要：本项目统一使用独立 Python 3.11 解释器
# 推荐路径: C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe
# 请勿使用 Conda base (Python 3.13) 运行本项目
#
```

同时将原有第 1-4 行的旧标题替换掉：
```bash
# ========================================
#   Bio-Short-Seller Configuration
#   All Intelligence -> Google Gemini
# ========================================
```

- [ ] **Step 4: 验证文档一致性**

手动检查：
1. README.md 中所有 `python` 命令都使用了显式路径
2. .env.example 顶部有解释器说明
3. 没有残留的裸 `python` 或 `pip` 命令

Run:
```bash
grep -n "^python \|^pip " README.md
```
Expected: 无输出（所有命令都已改为显式路径）。

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example
git commit -m "docs: align README and .env.example to explicit Python 3.11 interpreter"
```

---

## Task 7: 端到端验证

**Files:**
- 无新文件变更，纯验证步骤

- [ ] **Step 1: 运行环境自检**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" scripts/check_env.py
```
Expected: `✅ Environment OK`

- [ ] **Step 2: 运行测试套件**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" -m pytest tests/test_dataflow_integrity.py tests/test_report_engine_sanitization.py -v
```
Expected: 所有测试 PASSED。

- [ ] **Step 3: 启动应用验证无刷屏日志**

Run:
```bash
"C:/Users/16830/AppData/Local/Programs/Python/Python311/python.exe" app.py
```
Expected:
- 启动时打印环境自检结果（Python 3.11.x，所有依赖 ✓）
- 无重复 `❌ spacy / scispacy not installed` 刷屏
- HTMLRenderer 行显示 `INFO`（非 `WARNING`）
- 正常显示 `🧬 Cassandra - Biomedical Research Workflow Platform`

按 `Ctrl+C` 停止服务器。

- [ ] **Step 4: 最终 Commit（如有遗漏修复）**

```bash
git add -A
git status
# 如果有变更：
git commit -m "fix: final adjustments from end-to-end verification"
```
