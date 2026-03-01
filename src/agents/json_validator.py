"""
JSON验证器和修复器 - 确保Gemini生成的JSON格式正确

这个模块提供:
1. JSON格式验证和自动修复
2. 检查官角色 - 验证JSON完整性
3. 分段JSON生成管理器
"""

import json
import re
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger


class JSONValidator:
    """JSON格式验证器和修复器"""
    
    @staticmethod
    def validate_and_repair(json_text: str, expected_fields: List[str]) -> Tuple[bool, Optional[Dict], List[str]]:
        """
        验证JSON并尝试修复常见错误
        
        Args:
            json_text: 待验证的JSON文本
            expected_fields: 期望的字段列表
        
        Returns:
            (is_valid, parsed_data, errors)
        """
        errors = []
        
        # 🔥 CRITICAL FIX: Check for None or empty input
        if json_text is None:
            logger.error("❌ JSONValidator received None input")
            return False, None, ["Input is None"]
        
        if not json_text or not json_text.strip():
            logger.error("❌ JSONValidator received empty input")
            return False, None, ["Input is empty"]
        
        # 🔥 STAGE 0: Try json-repair library first (most powerful)
        try:
            from json_repair import repair_json
            logger.info("🔧 Attempting json-repair library (Stage 0)...")
            
            repaired_obj = repair_json(json_text, return_objects=True)
            if isinstance(repaired_obj, dict):
                logger.success("✅ json-repair library fixed JSON successfully")
                
                # Validate fields
                missing_fields = [f for f in expected_fields if f not in repaired_obj]
                if missing_fields:
                    errors.append(f"Missing fields: {', '.join(missing_fields)}")
                    for field in missing_fields:
                        repaired_obj[field] = "[Data not available]"
                
                return True, repaired_obj, errors
                
        except ImportError:
            logger.debug("json-repair library not available, using manual repair")
        except Exception as e:
            logger.debug(f"json-repair failed: {e}, falling back to manual repair")
        
        # 1. 预处理 - 清理常见问题
        cleaned = JSONValidator._preprocess_json(json_text)
        
        # 2. 尝试直接解析
        try:
            data = json.loads(cleaned)
            
            # 3. 验证必需字段
            missing_fields = [f for f in expected_fields if f not in data]
            if missing_fields:
                errors.append(f"Missing fields: {', '.join(missing_fields)}")
                # 补充缺失字段
                for field in missing_fields:
                    data[field] = "[Data not available]"
                logger.warning(f"🔧 Auto-filled {len(missing_fields)} missing fields")
            
            # 4. 验证字段值不为空
            empty_fields = [k for k, v in data.items() if not v or (isinstance(v, str) and v.strip() == "")]
            if empty_fields:
                errors.append(f"Empty fields: {', '.join(empty_fields)}")
                for field in empty_fields:
                    data[field] = "[Insufficient data]"
            
            logger.success(f"✅ JSON validation passed with {len(errors)} warnings")
            return True, data, errors
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON parsing failed: {e}")
            # 🔥 NEW: 显示错误上下文以便调试
            if hasattr(e, 'pos') and e.pos < len(cleaned):
                error_start = max(0, e.pos - 50)
                error_end = min(len(cleaned), e.pos + 50)
                context = cleaned[error_start:error_end]
                logger.error(f"Error context at position {e.pos}:")
                logger.error(f"...{context}...")
            else:
                logger.error(f"First 200 chars of problematic JSON:")
                logger.error(f"{cleaned[:200]}")
            
            errors.append(f"JSON decode error: {e}")
            
            # 5. 尝试高级修复策略
            repaired_data = JSONValidator._advanced_repair(cleaned, expected_fields, e)
            if repaired_data:
                logger.success("✅ JSON repaired successfully via advanced strategies")
                return True, repaired_data, errors
            
            return False, None, errors
    
    @staticmethod
    def _preprocess_json(text: str) -> str:
        """预处理JSON文本，修复常见格式问题"""
        # 🔥 DEBUG: 记录原始响应的前200字符
        logger.debug(f"📥 Raw JSON input (first 200 chars): {text[:200]}")
        
        # 移除markdown代码块标记
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
            logger.debug("🔧 Removed markdown ```json wrapper")
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            logger.debug("🔧 Removed markdown ``` wrapper")
        
        # 移除BOM和零宽字符
        text = text.replace('\ufeff', '').replace('\u200b', '')
        
        # 🔥 CRITICAL FIX: 修复字符串值内部的未转义引号
        # 这是Gemini生成JSON的最常见问题
        text = JSONValidator._fix_unescaped_quotes_in_strings(text)
        
        # 🔥 NEW: 修复无引号的属性名 (Gemini常见问题)
        # 匹配模式: { field_name: "value" } → { "field_name": "value" }
        # 仅在对象内部进行替换，避免误伤字符串内容
        original_text = text
        text = re.sub(
            r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)\s*:',
            r'\1"\2":',
            text
        )
        
        # 🔥 DEBUG: 检查是否修复了无引号属性名
        if text != original_text:
            logger.debug(f"🔧 Fixed unquoted property names (changed {len(text) - len(original_text)} chars)")
            logger.debug(f"📤 After fix (first 200 chars): {text[:200]}")
        
        # 修复常见的转义问题
        # 1. 处理未转义的换行符（在字符串内）
        text = re.sub(r'(?<!\\)"([^"]*)\n([^"]*)"', r'"\1\\n\2"', text)
        
        # 2. 修复连续的转义反斜杠
        text = text.replace('\\\\n', '\\n').replace('\\\\t', '\\t')
        
        return text.strip()
    
    @staticmethod
    def _fix_unescaped_quotes_in_strings(text: str) -> str:
        """
        修复JSON字符串值内部的未转义引号
        
        例如: "text": "He said "hello" there" 
        修复为: "text": "He said \\"hello\\" there"
        
        使用简化的正则表达式方法，更可靠
        """
        try:
            # 🔥 SIMPLE STRATEGY: 使用正则表达式找到所有字符串值，然后修复其中的引号
            # 模式: "field_name": "value with possible "quotes" inside"
            
            def fix_quotes_in_match(match):
                """修复匹配到的字符串值中的引号"""
                field_name = match.group(1)
                string_value = match.group(2)
                
                # 在字符串值内部转义所有未转义的引号
                # 但要小心已经转义的引号
                fixed_value = string_value
                
                # 先标记已经转义的引号
                fixed_value = fixed_value.replace('\\"', '<<<ESCAPED_QUOTE>>>')
                
                # 转义所有剩余的引号
                fixed_value = fixed_value.replace('"', '\\"')
                
                # 恢复已经转义的引号
                fixed_value = fixed_value.replace('<<<ESCAPED_QUOTE>>>', '\\"')
                
                return f'"{field_name}": "{fixed_value}"'
            
            # 匹配模式：属性名: 值
            # 允许值包含换行和其他字符
            pattern = r'"([^"]+)"\s*:\s*"((?:[^"\\]|\\.)*?)(?="(?:\s*[,}\]])|$)'
            
            fixed = re.sub(pattern, fix_quotes_in_match, text, flags=re.DOTALL)
            
            if fixed != text:
                logger.info(f"🔧 Applied regex-based quote fixing")
                return fixed
            
            return text
            
        except Exception as e:
            logger.warning(f"⚠️ Regex quote fixing failed: {e}, trying character-by-character approach")
            
            # FALLBACK: 字符级别的修复（原有逻辑）
            return JSONValidator._fix_unescaped_quotes_detailed(text)
    
    @staticmethod
    def _fix_unescaped_quotes_detailed(text: str) -> str:
        """
        详细的字符级别引号修复（备用方案）
        """
        try:
            result = []
            i = 0
            in_string = False
            string_start_pos = -1
            
            while i < len(text):
                char = text[i]
                
                # 检查转义字符
                if char == '\\' and i + 1 < len(text):
                    result.append(char)
                    result.append(text[i + 1])
                    i += 2
                    continue
                
                # 检查引号
                if char == '"':
                    # 判断这是属性名的引号还是字符串值的引号
                    # 通过查看前后上下文来判断
                    
                    if not in_string:
                        # 进入字符串
                        in_string = True
                        string_start_pos = i
                        result.append(char)
                        i += 1
                        
                        # 🔥 关键：判断这是属性名还是值
                        # 如果后面紧跟着冒号，这是属性名
                        lookahead = i
                        while lookahead < len(text) and text[lookahead] in [' ', '\t', '\n', '\r']:
                            lookahead += 1
                        
                        if lookahead < len(text) and text[lookahead] == ':':
                            # 这是属性名，继续查找属性值
                            while i < len(text) and text[i] != '"':
                                result.append(text[i])
                                i += 1
                            if i < len(text):
                                result.append(text[i])  # 闭合属性名的引号
                                i += 1
                            
                            # 跳过冒号和空白
                            while i < len(text) and text[i] in [':', ' ', '\t', '\n', '\r']:
                                result.append(text[i])
                                i += 1
                            
                            # 现在应该是值的开始引号
                            if i < len(text) and text[i] == '"':
                                in_string = True
                                string_start_pos = i
                                result.append(text[i])
                                i += 1
                            else:
                                in_string = False
                        
                    else:
                        # 可能是字符串结束，也可能是内部未转义的引号
                        # 检查后面是否跟着逗号、花括号或方括号
                        lookahead = i + 1
                        while lookahead < len(text) and text[lookahead] in [' ', '\t', '\n', '\r']:
                            lookahead += 1
                        
                        if lookahead < len(text) and text[lookahead] in [',', '}', ']']:
                            # 这是字符串结束
                            in_string = False
                            result.append(char)
                            i += 1
                        else:
                            # 这是内部未转义的引号，需要转义
                            logger.debug(f"🔧 Escaping unescaped quote at position {i}")
                            result.append('\\')
                            result.append(char)
                            i += 1
                else:
                    result.append(char)
                    i += 1
            
            fixed = ''.join(result)
            
            if fixed != text:
                # 计算修复了多少处
                fix_count = fixed.count('\\"') - text.count('\\"')
                if fix_count > 0:
                    logger.info(f"🔧 Fixed {fix_count} unescaped quotes via detailed analysis")
            
            return fixed
            
        except Exception as e:
            logger.warning(f"⚠️ Detailed quote fixing failed: {e}, returning original text")
            return text
    
    @staticmethod
    def _advanced_repair(text: str, expected_fields: List[str], error: json.JSONDecodeError) -> Optional[Dict]:
        """高级JSON修复策略"""
        strategies = [
            JSONValidator._repair_unterminated_string,
            JSONValidator._repair_via_regex_extraction,
            JSONValidator._repair_truncated_json,
        ]
        
        for strategy in strategies:
            try:
                result = strategy(text, expected_fields, error)
                if result:
                    return result
            except Exception as e:
                logger.debug(f"Strategy {strategy.__name__} failed: {e}")
                continue
        
        return None
    
    @staticmethod
    def _repair_unterminated_string(text: str, expected_fields: List[str], error: json.JSONDecodeError) -> Optional[Dict]:
        """修复未终止的字符串 - 增强版（支持 json-repair 库）"""
        if 'Unterminated string' not in str(error):
            return None
        
        # 🔥 PRIORITY 1: Try json-repair library first (most reliable)
        try:
            from json_repair import repair_json
            logger.info("🔧 Attempting json-repair library for unterminated string...")
            repaired = repair_json(text)
            if isinstance(repaired, dict):
                logger.success("✅ json-repair library successfully fixed unterminated string")
                return repaired
        except ImportError:
            logger.debug("json-repair library not available, using manual repair")
        except Exception as e:
            logger.debug(f"json-repair failed: {e}, falling back to manual repair")
        
        # 🔥 PRIORITY 2: Manual repair strategies
        pos = error.pos if hasattr(error, 'pos') else -1
        if pos > 0 and pos < len(text):
            # Strategy 1: Find next delimiter and close string before it
            next_delimiter = pos
            for i in range(pos, min(pos + 200, len(text))):
                if text[i] in [',', '}', ']']:
                    next_delimiter = i
                    break
            
            # Try inserting closing quote at delimiter
            fixed_text = text[:next_delimiter] + '"' + text[next_delimiter:]
            try:
                return json.loads(fixed_text)
            except:
                pass
            
            # Strategy 2: Close string immediately and try to close JSON
            for ending in ['"}}', '"}', '","']:
                try:
                    fixed_text = text[:pos] + ending
                    return json.loads(fixed_text)
                except:
                    continue
        
        return None
    
    @staticmethod
    def _repair_via_regex_extraction(text: str, expected_fields: List[str], error: json.JSONDecodeError) -> Optional[Dict]:
        """通过正则表达式提取字段内容"""
        extracted = {}
        
        for field in expected_fields:
            # 匹配 "field": "value" 格式，支持多行和转义引号
            pattern = rf'"{field}"\s*:\s*"((?:[^"\\]|\\.)*)(?:"|\Z)'
            match = re.search(pattern, text, re.DOTALL)
            
            if match:
                value = match.group(1)
                # 反转义
                value = value.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
                extracted[field] = value.strip()
            else:
                extracted[field] = "[Data extraction failed]"
        
        # 验证至少提取了一半的字段
        valid_fields = [v for v in extracted.values() if v != "[Data extraction failed]"]
        if len(valid_fields) >= len(expected_fields) / 2:
            logger.info(f"📝 Regex extraction recovered {len(valid_fields)}/{len(expected_fields)} fields")
            return extracted
        
        return None
    
    @staticmethod
    def _repair_truncated_json(text: str, expected_fields: List[str], error: json.JSONDecodeError) -> Optional[Dict]:
        """修复被截断的JSON"""
        # 尝试找到最后一个完整的字段
        last_complete = text.rfind('",')
        if last_complete > 0:
            # 截取到最后一个完整字段，添加闭合括号
            truncated = text[:last_complete + 1] + '\n}'
            
            try:
                data = json.loads(truncated)
                # 补充缺失字段
                for field in expected_fields:
                    if field not in data:
                        data[field] = "[Data truncated]"
                
                logger.info(f"🔧 Repaired truncated JSON, recovered {len(data)} fields")
                return data
            except:
                pass
        
        return None


class JSONInspector:
    """JSON检查官 - 验证JSON完整性和质量"""
    
    QUALITY_THRESHOLDS = {
        'min_length_per_field': 50,  # 每个字段最少50字符
        'placeholder_patterns': [
            r'\[Data not available\]',
            r'\[Insufficient data\]',
            r'\[Unknown\]',
            r'\.\.\.',
            r'N/A',
        ],
        'max_placeholder_ratio': 0.3,  # 最多30%的字段可以是占位符
    }
    
    @staticmethod
    def inspect_quality(data: Dict[str, Any], section_name: str = "Unknown") -> Dict[str, Any]:
        """
        检查JSON数据质量
        
        Args:
            data: 待检查的数据
            section_name: 章节名称
        
        Returns:
            质量报告字典
        """
        report = {
            'section': section_name,
            'total_fields': len(data),
            'issues': [],
            'quality_score': 10.0,
            'recommendations': []
        }
        
        placeholder_count = 0
        short_field_count = 0
        
        for field, value in data.items():
            str_value = str(value)
            
            # 检查占位符
            is_placeholder = any(
                re.search(pattern, str_value, re.IGNORECASE) 
                for pattern in JSONInspector.QUALITY_THRESHOLDS['placeholder_patterns']
            )
            
            if is_placeholder:
                placeholder_count += 1
                report['issues'].append(f"Field '{field}' contains placeholder text")
            
            # 检查字段长度
            if len(str_value) < JSONInspector.QUALITY_THRESHOLDS['min_length_per_field']:
                short_field_count += 1
                report['issues'].append(f"Field '{field}' is too short ({len(str_value)} chars)")
        
        # 计算质量分数
        placeholder_ratio = placeholder_count / len(data) if data else 1.0
        short_ratio = short_field_count / len(data) if data else 1.0
        
        # 扣分逻辑
        if placeholder_ratio > JSONInspector.QUALITY_THRESHOLDS['max_placeholder_ratio']:
            deduction = (placeholder_ratio - 0.3) * 20
            report['quality_score'] -= deduction
            report['recommendations'].append(
                f"⚠️ High placeholder ratio ({placeholder_ratio:.1%}). Request more detailed content."
            )
        
        if short_ratio > 0.4:
            report['quality_score'] -= short_ratio * 15
            report['recommendations'].append(
                f"⚠️ Many fields are too short. Request expanded analysis."
            )
        
        report['quality_score'] = max(0, report['quality_score'])
        
        # 生成总结
        if report['quality_score'] >= 8:
            report['verdict'] = "✅ EXCELLENT"
        elif report['quality_score'] >= 6:
            report['verdict'] = "⚠️ ACCEPTABLE"
        else:
            report['verdict'] = "❌ POOR - Regeneration recommended"
        
        logger.info(f"🔍 Quality inspection: {report['verdict']} (Score: {report['quality_score']:.1f}/10)")
        
        return report


class SegmentedJSONGenerator:
    """分段JSON生成管理器 - 将大JSON拆分成小块生成"""
    
    # 定义报告的各个段落和对应字段
    REPORT_SEGMENTS = {
        'metadata': {
            'fields': ['compound_name', 'moa_description', 'target_description', 
                      'development_stage', 'sponsor_company', 'market_context'],
            'description': 'Project metadata and basic information',
            'max_tokens': 1500
        },
        'summary': {
            'fields': ['executive_summary', 'red_flags_list', 'decision_factors'],
            'description': 'Executive summary and key findings',
            'max_tokens': 2000
        },
        'analysis': {
            'fields': ['scientific_rationale', 'clinical_trial_analysis'],
            'description': 'Scientific and clinical analysis',
            'max_tokens': 2500
        },
        'evidence': {
            'fields': ['dark_data_synthesis', 'forensic_findings'],
            'description': 'Dark data and forensic findings',
            'max_tokens': 2000
        },
        'risk': {
            'fields': ['risk_cascade_narrative', 'failure_timeline'],
            'description': 'Risk analysis and timeline',
            'max_tokens': 2000
        },
        'scenarios': {
            'fields': ['bull_case', 'bear_case', 'black_swan_case', 'analyst_verdict'],
            'description': 'Investment scenarios and verdict',
            'max_tokens': 2000
        }
    }
    
    @staticmethod
    def get_segment_prompt(segment_key: str, base_prompt: str, evidence_summary: str) -> str:
        """
        生成特定段落的prompt
        
        Args:
            segment_key: 段落键名
            base_prompt: 基础prompt模板
            evidence_summary: 证据摘要
        
        Returns:
            完整的segment prompt
        """
        segment_info = SegmentedJSONGenerator.REPORT_SEGMENTS[segment_key]
        
        prompt = f"""You are generating the '{segment_key}' section of a biomedical due diligence report.

**SEGMENT FOCUS:** {segment_info['description']}

**REQUIRED FIELDS:**
{json.dumps(segment_info['fields'], indent=2)}

{evidence_summary}

**CRITICAL JSON FORMATTING REQUIREMENTS:**
1. Generate ONLY the fields listed above
2. ALL property names MUST be enclosed in double quotes ("field_name":)
3. Return VALID JSON - test your output with a JSON parser before responding
4. Each field should contain substantial content (minimum 100 words for analysis fields)
5. Cite sources using [Source: PMC/PMID] or [Trial: NCT] format
6. DO NOT use placeholder text like "[Data not available]" unless truly no data exists
7. Ensure all strings are properly terminated with closing quotes
8. NO markdown code fences (no ```json), NO explanatory text - ONLY JSON

**STRICT OUTPUT FORMAT:**
Return ONLY a valid JSON object. Start with {{ and end with }}. Nothing else.

Example (note the quoted property names):
{{{{
  "field_name_1": "Detailed content here...",
  "field_name_2": "More detailed content..."
}}}}

⚠️ VALIDATION: Your response will be parsed with json.loads(). If it fails, generation will be rejected.

{base_prompt}
"""
        return prompt
    
    @staticmethod
    def merge_segments(segments: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        合并多个段落的JSON数据
        
        Args:
            segments: 段落字典，key为segment_key，value为该段落的数据
        
        Returns:
            合并后的完整数据字典
        """
        merged = {}
        
        for segment_key in SegmentedJSONGenerator.REPORT_SEGMENTS.keys():
            if segment_key in segments:
                merged.update(segments[segment_key])
            else:
                logger.warning(f"⚠️ Missing segment: {segment_key}")
                # 补充缺失段落的字段
                segment_info = SegmentedJSONGenerator.REPORT_SEGMENTS[segment_key]
                for field in segment_info['fields']:
                    merged[field] = "[Segment generation failed]"
        
        logger.success(f"✅ Merged {len(segments)}/{len(SegmentedJSONGenerator.REPORT_SEGMENTS)} segments")
        return merged
