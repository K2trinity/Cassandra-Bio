# Python 环境配置指南 - VSCode + Miniconda

## 📊 当前环境状态

### 你正在使用的环境
```
环境类型: Miniconda base 环境
Python版本: 3.13.11
Python路径: F:\miniconda\python.exe
虚拟环境: F:\miniconda (base)
```

### 检测到的Conda环境列表
```
1. base (当前激活) - F:\miniconda
2. everything         - F:\anaconda\envs\everything  
3. alibaseline        - F:\anaconda\envs\alibaseline
4. dlhw               - F:\anaconda\envs\dlhw
5. neurofly           - F:\anaconda\envs\neurofly
6. widefield_imaging  - F:\anaconda\envs\widefield_imaging
```

⚠️ **问题发现**: 你有**两个Conda安装**：
- `F:\miniconda` (Miniconda)
- `F:\anaconda` (Anaconda)

---

## 🔧 为什么VSCode看不到新环境？

### 原因分析

1. **VSCode Python扩展未刷新**
   - VSCode需要手动刷新才能检测新环境

2. **Conda环境路径不在搜索范围**
   - VSCode默认只扫描特定位置的环境

3. **VSCode设置未配置Conda路径**
   - 需要告诉VSCode去哪里找Conda

---

## ✅ 解决方案（3种方法）

### 方法1: 手动刷新Python解释器 ⭐ 推荐

1. 按 `Ctrl + Shift + P` 打开命令面板
2. 输入 `Python: Select Interpreter`
3. 点击右上角的 **刷新图标** 🔄
4. 等待VSCode重新扫描环境（可能需要10-30秒）
5. 在列表中选择你想要的环境

### 方法2: 配置VSCode设置

创建工作区配置文件来明确指定Conda路径：

```json
// .vscode/settings.json
{
    "python.defaultInterpreterPath": "F:\\anaconda\\envs\\everything\\python.exe",
    "python.condaPath": "F:\\miniconda\\Scripts\\conda.exe",
    "python.terminal.activateEnvironment": true,
    "python.terminal.activateEnvInCurrentTerminal": true
}
```

### 方法3: 使用Conda命令手动激活

在VSCode终端中：

```powershell
# 激活特定环境
conda activate everything

# 验证环境
python --version
python -c "import sys; print(sys.executable)"
```

---

## 🎯 推荐：为Cassandra项目创建专用环境

### 创建新环境（推荐）

```powershell
# 创建名为cassandra的新环境（Python 3.11最稳定）
conda create -n cassandra python=3.11 -y

# 激活环境
conda activate cassandra

# 安装项目依赖
pip install -r requirements.txt

# 验证安装
python -c "import google.genai; print('Gemini SDK installed')"
```

### 在VSCode中选择新环境

1. 创建完环境后，重启VSCode或刷新解释器列表
2. 按 `Ctrl + Shift + P` → `Python: Select Interpreter`
3. 选择 `cassandra (F:\miniconda\envs\cassandra\python.exe)`

---

## 🔍 诊断命令

### 检查当前环境

```powershell
# 显示当前Python信息
python --version
python -c "import sys; print(f'Path: {sys.executable}')"

# 列出所有Conda环境
conda env list

# 检查已安装的包
pip list | Select-String -Pattern "google|neo4j|redis"
```

### 检查VSCode Python扩展

```powershell
# 查看VSCode识别的Python路径
code --list-extensions | Select-String python
```

---

## 📝 配置文件模板

创建 `.vscode/settings.json`：

```json
{
    "python.defaultInterpreterPath": "${workspaceFolder}/.venv/Scripts/python.exe",
    "python.condaPath": "F:\\miniconda\\Scripts\\conda.exe",
    "python.terminal.activateEnvironment": true,
    "python.terminal.activateEnvInCurrentTerminal": true,
    "python.analysis.extraPaths": [
        "${workspaceFolder}/src",
        "${workspaceFolder}/BioHarvestEngine",
        "${workspaceFolder}/EvidenceEngine",
        "${workspaceFolder}/ForensicEngine"
    ],
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": false,
    "python.linting.flake8Enabled": true,
    "python.formatting.provider": "black",
    "[python]": {
        "editor.defaultFormatter": "ms-python.black-formatter",
        "editor.formatOnSave": true,
        "editor.codeActionsOnSave": {
            "source.organizeImports": true
        }
    }
}
```

---

## 🚀 快速修复步骤

### 立即让VSCode识别你的环境

```powershell
# 1. 在终端执行
conda activate everything

# 2. 重新加载VSCode窗口
# 按 Ctrl+Shift+P → "Developer: Reload Window"

# 3. 验证环境
python -c "import sys; print(sys.executable)"
```

### 如果还是不行

```powershell
# 重新安装VSCode Python扩展
code --uninstall-extension ms-python.python
code --install-extension ms-python.python

# 重启VSCode
```

---

## 🐛 常见问题排查

### Q1: 刷新后还是看不到新环境
**解决**: 
```powershell
# 确保环境确实存在
conda env list

# 手动添加环境到VSCode搜索路径
# 编辑 settings.json，添加：
"python.venvPath": "F:\\anaconda\\envs"
```

### Q2: 终端激活的环境和VSCode不一致
**解决**:
- 关闭所有终端窗口
- 按 `Ctrl+Shift+P` → `Python: Select Interpreter`
- 重新打开终端（会自动激活选择的环境）

### Q3: pip安装的包在VSCode中提示找不到
**解决**:
```powershell
# 检查pip对应的Python版本
python -m pip --version

# 确保使用正确环境的pip
conda activate cassandra
pip install <package>
```

---

## 💡 最佳实践建议

1. **使用专用环境**: 为每个项目创建独立环境
2. **避免在base环境安装**: base环境应保持干净
3. **使用requirements.txt**: 记录项目依赖
4. **定期清理环境**: 删除不用的环境节省空间

```powershell
# 导出环境配置
conda env export > environment.yml

# 删除不用的环境
conda env remove -n old_env_name

# 清理缓存
conda clean --all
```

---

## 📌 针对Cassandra项目的配置

### 推荐环境配置

```powershell
# 创建Cassandra专用环境
conda create -n cassandra python=3.11 -y
conda activate cassandra

# 安装依赖
pip install -r requirements.txt

# 验证关键包
python -c "
from google import genai
from loguru import logger
import neo4j
import redis
print('✅ All key dependencies installed')
"
```

### VSCode工作区设置

创建 `.vscode/settings.json`（已为你生成，见下一步）

---

## 🔗 相关资源

- [VSCode Python教程](https://code.visualstudio.com/docs/python/python-tutorial)
- [Conda环境管理](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html)
- [VSCode Python设置参考](https://code.visualstudio.com/docs/python/settings-reference)

---

**最后更新**: 2026-02-09  
**适用于**: VSCode + Miniconda/Anaconda on Windows
