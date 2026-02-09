# JSON 解析错误 - 问题分析与修复报告

## 📌 问题摘要

**错误类型**: `Expecting property name enclosed in double quotes: line 2 column XX`  
**发生频率**: 所有报告段落（metadata, summary, analysis, evidence, risk, scenarios）  
**影响范围**: 报告生成完全失败，输出低质量内容

---

## 🔍 根本原因分析

### 1. Gemini API 返回格式不规范

尽管请求时指定了 `response_mime_type="application/json"`，Gemini 3.0 Pro 可能返回：

#### ❌ 问题格式
```javascript
// 无引号属性名 (最常见)
{
  compound_name: "value",
  moa_description: "text"
}

// Markdown 包裹
```json
{"field": "value"}
```

// 截断的 JSON (超出 token 限制)
{"field": "val
```

#### ✅ 期望格式
```json
{
  "compound_name": "value",
  "moa_description": "text"
}
```

### 2. 错误位置定位

| 文件 | 行号 | 说明 |
|------|------|------|
| [src/llms/gemini_client.py](f:\Visual Studio Code\Cassandra\src\llms\gemini_client.py#L254) | 254 | LLM 返回 `response.text` 未验证 |
| [src/agents/report_writer.py](f:\Visual Studio Code\Cassandra\src\agents\report_writer.py#L687-L695) | 687-695 | 调用 LLM 生成 JSON 段落 |
| [src/agents/json_validator.py](f:\Visual Studio Code\Cassandra\src\agents\json_validator.py#L32-L75) | 32-75 | JSON 验证和修复逻辑 |
| [src/agents/json_validator.py](f:\Visual Studio Code\Cassandra\src\agents\json_validator.py#L80-L105) | 80-105 | JSON 预处理（修复格式问题）|

### 3. 为什么所有段落都失败？

根据日志模式：
```
metadata  - POOR (0.0/10) - 修复成功但质量差
summary   - validation failed - 完全失败
analysis  - validation failed - 完全失败
evidence  - POOR (2.5/10) - 勉强修复
risk      - validation failed - 完全失败
scenarios - validation failed - 完全失败
```

**核心问题**:
1. ⚡ **Token 截断** - 响应超过 max_output_tokens 导致 JSON 不完整
2. 📝 **格式不严格** - Gemini 未严格遵循 JSON 语法规范
3. 🔧 **修复不完善** - 原有预处理逻辑无法处理所有情况

---

## ✅ 实施的修复方案

### 修复 1: 增强 JSON 预处理 - 自动修复无引号属性名

**文件**: `src/agents/json_validator.py:80-105`

```python
# 🔥 NEW: 修复无引号的属性名 (Gemini常见问题)
# 匹配模式: { field_name: "value" } → { "field_name": "value" }
text = re.sub(
    r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:',
    r'\1"\2":',
    text
)
```

**效果**: 自动将 `field_name:` 转换为 `"field_name":`

### 修复 2: LLM 层响应验证

**文件**: `src/llms/gemini_client.py:254-274`

```python
# 🔥 NEW: 如果请求JSON格式，验证响应有效性
if kwargs.get('response_mime_type') == 'application/json':
    stripped = result.strip()
    if not stripped.startswith(('{', '[')):
        logger.warning(f"⚠️ JSON response doesn't start with {{ or [")
        # 记录异常情况以便调试
```

**效果**: 在 LLM 层就检测格式问题，提前发出警告

### 修复 3: 改进错误日志

**文件**: 
- `src/agents/json_validator.py:60-79`
- `src/agents/report_writer.py:695-702`

```python
# 显示错误上下文
if hasattr(e, 'pos') and e.pos < len(cleaned):
    error_start = max(0, e.pos - 50)
    error_end = min(len(cleaned), e.pos + 50)
    context = cleaned[error_start:error_end]
    logger.debug(f"Error context at position {e.pos}: ...{context}...")
```

**效果**: 显示错误发生的具体位置和上下文，便于调试

### 修复 4: 强化提示词要求

**文件**: `src/agents/json_validator.py:376-396`

**新增要求**:
```
1. ALL property names MUST be enclosed in double quotes ("field_name":)
2. Return VALID JSON - test your output with a JSON parser before responding
3. NO markdown code fences (no ```json), NO explanatory text - ONLY JSON
⚠️ VALIDATION: Your response will be parsed with json.loads(). If it fails, generation will be rejected.
```

**效果**: 更明确地告诉 Gemini 必须生成严格的 JSON 格式

---

## 🧪 测试结果

### 测试案例 1: 无引号属性名
```javascript
{
  compound_name: "Test Drug",  // ❌ 无引号
  moa_description: "text"
}
```
**结果**: ✅ 成功修复并解析

### 测试案例 2: Markdown 包裹
````
```json
{"compound_name": "Test"}
```
````
**结果**: ✅ 成功移除 markdown 并解析

### 测试案例 3: 混合问题
````javascript
```json
{
  compound_name: "Test",  // 无引号 + markdown
  missing_field_test: "x"
}
````
**结果**: ✅ 成功修复，缺失字段自动补充

---

## 📊 预期改进效果

| 指标 | 修复前 | 修复后（预期）|
|------|--------|---------------|
| 段落成功率 | 33% (2/6) | 90%+ (5-6/6) |
| 平均质量分数 | 0.8/10 | 6.5+/10 |
| 需要重新生成 | 67% | <20% |
| 调试时间 | 困难（无上下文）| 快速（有错误定位）|

---

## 🚀 后续建议

### 短期措施（已实施）
- ✅ JSON 预处理增强
- ✅ LLM 响应验证
- ✅ 错误日志改进
- ✅ 提示词强化

### 中期优化（建议）
1. **Schema 验证** - 使用 `response_schema` 参数强制 JSON 结构
   ```python
   config_params["response_schema"] = {
       "type": "object",
       "properties": {
           "field_name": {"type": "string"}
       },
       "required": ["field_name"]
   }
   ```

2. **分段 Token 预算** - 动态调整每个段落的 `max_tokens`
   ```python
   segment_info['max_tokens'] = calculate_optimal_tokens(
       field_count=len(segment_info['fields']),
       avg_content_length=1500
   )
   ```

3. **多次采样** - 生成多个候选，选择质量最高的
   ```python
   candidates = [generate_segment() for _ in range(3)]
   best = max(candidates, key=lambda x: quality_score(x))
   ```

### 长期优化（可选）
- 考虑切换到 `gemini-2.5-pro`（JSON 模式更稳定）
- 实现 JSON Schema 验证器（pydantic）
- 添加人工审核环节

---

## 📝 使用说明

### 重新运行测试
```bash
python test_json_fix.py
```

### 查看完整日志
```bash
python app.py  # 正常运行应用
```

### 如果还有问题
1. 检查日志中的 `Error context at position XX` 消息
2. 查看 `🔧 Fixed unquoted property names` 是否出现
3. 确认 Gemini 返回的原始响应（前 200 字符会被记录）

---

## 🎯 总结

**核心问题**: Gemini 3.0 Pro 生成 JSON 时不够严格，导致解析失败  
**解决方案**: 4 层防御机制（预处理 + 验证 + 修复 + 提示词）  
**预期效果**: 段落成功率从 33% 提升至 90%+，报告质量显著改善

---

**修复完成时间**: 2026-02-09  
**修复工程师**: Cassandra AI Assistant  
**相关文件**: 3 个核心文件已修改
