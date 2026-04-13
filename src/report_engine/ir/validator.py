"""
IR Validator - 中间表示验证器

对LLM生成的章节JSON进行多层验证：
1. 结构验证（必需字段、类型检查）
2. 内容验证（最小字数、非空检查）
3. 质量验证（避免[Data not available]等占位符）

借鉴BettaFish的严格验证机制
"""

from typing import List, Dict, Any, Tuple
from loguru import logger
from .schema import BlockType, Chapter, ChapterBlock


class IRValidator:
    """IR结构校验器"""
    
    # 最小内容要求
    MIN_NON_HEADING_BLOCKS = 2  # 至少2个非标题块
    MIN_PARAGRAPH_LENGTH = 50   # 段落最小字符数
    
    # 禁止的占位符
    FORBIDDEN_PLACEHOLDERS = [
        "[Data not available]",
        "[No data]",
        "[Analysis pending]",
        "[Content missing]",
        "[TODO]",
        "[N/A]",
    ]
    
    def __init__(self):
        """初始化验证器"""
        pass
    
    def validate_chapter(self, chapter_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        校验章节结构
        
        Args:
            chapter_data: 章节JSON数据
        
        Returns:
            (is_valid, errors): 校验结果和错误列表
        """
        errors = []
        
        # 1. 结构验证
        if "title" not in chapter_data:
            errors.append("Missing required field: title")
        
        if "blocks" not in chapter_data:
            errors.append("Missing required field: blocks")
            return False, errors
        
        blocks = chapter_data.get("blocks", [])
        if not isinstance(blocks, list):
            errors.append("Field 'blocks' must be a list")
            return False, errors
        
        # 2. 最小内容检查
        non_heading_count = sum(
            1 for block in blocks 
            if block.get("type") not in ["heading", BlockType.HEADING.value]
        )
        
        if non_heading_count < self.MIN_NON_HEADING_BLOCKS:
            errors.append(
                f"Chapter has only {non_heading_count} non-heading blocks "
                f"(minimum: {self.MIN_NON_HEADING_BLOCKS})"
            )
        
        # 3. 逐个Block验证
        for idx, block in enumerate(blocks):
            block_errors = self._validate_block(block, idx)
            errors.extend(block_errors)
        
        # 4. 禁止占位符检查
        for block in blocks:
            content = str(block.get("content", ""))
            for placeholder in self.FORBIDDEN_PLACEHOLDERS:
                if placeholder.lower() in content.lower():
                    errors.append(
                        f"Forbidden placeholder found: '{placeholder}' in block content"
                    )
        
        is_valid = len(errors) == 0
        return is_valid, errors
    
    def _validate_block(self, block: Dict[str, Any], idx: int) -> List[str]:
        """
        验证单个block
        
        Args:
            block: Block数据
            idx: Block索引
        
        Returns:
            错误列表
        """
        errors = []
        
        # 检查必需字段
        if "type" not in block:
            errors.append(f"Block {idx}: Missing 'type' field")
            return errors
        
        if "content" not in block:
            errors.append(f"Block {idx}: Missing 'content' field")
            return errors
        
        # 检查type有效性
        block_type = block["type"]
        if not self._is_valid_type(block_type):
            errors.append(
                f"Block {idx}: Invalid type '{block_type}'. "
                f"Valid types: {[t.value for t in BlockType]}"
            )
        
        # 内容验证
        content = block["content"]
        
        # 段落最小长度检查
        if block_type in ["paragraph", BlockType.PARAGRAPH.value]:
            if isinstance(content, str) and len(content) < self.MIN_PARAGRAPH_LENGTH:
                errors.append(
                    f"Block {idx}: Paragraph too short ({len(content)} chars, "
                    f"minimum: {self.MIN_PARAGRAPH_LENGTH})"
                )
        
        # 列表非空检查
        if block_type in ["list", BlockType.LIST.value]:
            if not isinstance(content, list) or len(content) == 0:
                errors.append(f"Block {idx}: List cannot be empty")
        
        # 标题需要level字段
        if block_type in ["heading", BlockType.HEADING.value]:
            if "level" not in block:
                errors.append(f"Block {idx}: Heading must have 'level' field")
            else:
                level = block["level"]
                if not isinstance(level, int) or level < 1 or level > 4:
                    errors.append(f"Block {idx}: Invalid heading level {level} (must be 1-4)")

        # Chart结构验证
        if block_type in ["chart", BlockType.CHART.value]:
            if not isinstance(content, dict):
                errors.append(f"Block {idx}: Chart 'content' must be a dict")
            else:
                if "type" not in content:
                    errors.append(f"Block {idx}: Chart missing required 'type' field (bar/line/pie/…)")
                if "labels" not in content and content.get("type") not in ("scatter", "bubble"):
                    errors.append(f"Block {idx}: Chart missing 'labels' field")
                datasets = content.get("datasets")
                if not isinstance(datasets, list) or len(datasets) == 0:
                    errors.append(f"Block {idx}: Chart 'datasets' must be a non-empty list")
                else:
                    for di, ds in enumerate(datasets):
                        if not isinstance(ds, dict):
                            errors.append(f"Block {idx}: Chart dataset[{di}] must be a dict")
                        elif "data" not in ds:
                            errors.append(f"Block {idx}: Chart dataset[{di}] missing 'data' array")

        return errors
    
    def _is_valid_type(self, block_type: str) -> bool:
        """检查block类型是否有效"""
        try:
            BlockType(block_type)
            return True
        except (ValueError, KeyError):
            return False
    
    def validate_and_fix(self, chapter_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], List[str]]:
        """
        验证并尝试修复章节数据
        
        Args:
            chapter_data: 章节JSON数据
        
        Returns:
            (is_valid, fixed_data, errors): 验证结果、修复后的数据、错误列表
        """
        errors = []
        fixed_data = chapter_data.copy()
        
        # 1. 尝试修复缺失字段
        if "title" not in fixed_data:
            fixed_data["title"] = "Untitled Chapter"
            errors.append("Fixed: Added default title")
        
        if "blocks" not in fixed_data:
            fixed_data["blocks"] = []
            errors.append("Fixed: Added empty blocks array")
        
        # 2. 修复blocks
        fixed_blocks = []
        for idx, block in enumerate(fixed_data.get("blocks", [])):
            try:
                fixed_block = self._fix_block(block, idx)
                if fixed_block:
                    fixed_blocks.append(fixed_block)
            except Exception as e:
                errors.append(f"Block {idx}: Could not fix - {str(e)}")
        
        fixed_data["blocks"] = fixed_blocks
        
        # 3. 再次验证
        is_valid, validation_errors = self.validate_chapter(fixed_data)
        errors.extend(validation_errors)
        
        return is_valid, fixed_data, errors
    
    def _fix_block(self, block: Dict[str, Any], idx: int) -> Dict[str, Any]:
        """
        尝试修复单个block
        
        Args:
            block: Block数据
            idx: Block索引
        
        Returns:
            修复后的block（如果无法修复则返回None）
        """
        fixed = block.copy()
        
        # 修复type
        if "type" not in fixed:
            # 根据content推断type
            if isinstance(fixed.get("content"), list):
                fixed["type"] = BlockType.LIST.value
            else:
                fixed["type"] = BlockType.PARAGRAPH.value
        
        # 修复content
        if "content" not in fixed:
            return None  # 无法修复
        
        # 标准化type值
        block_type = fixed["type"]
        if block_type in ["heading", "Heading", "HEADING"]:
            fixed["type"] = BlockType.HEADING.value
            if "level" not in fixed:
                fixed["level"] = 2  # 默认H2
        
        elif block_type in ["paragraph", "Paragraph", "PARAGRAPH", "text"]:
            fixed["type"] = BlockType.PARAGRAPH.value
        
        elif block_type in ["list", "List", "LIST", "bullet_list", "numbered_list"]:
            fixed["type"] = BlockType.LIST.value
            # 确保content是列表
            if not isinstance(fixed["content"], list):
                fixed["content"] = [str(fixed["content"])]
        
        elif block_type in ["quote", "Quote", "QUOTE", "blockquote"]:
            fixed["type"] = BlockType.QUOTE.value

        elif block_type in ["chart", "Chart", "CHART", "graph", "visualization"]:
            fixed["type"] = BlockType.CHART.value
            # 确保 content 是 dict，如果不是则包装
            if not isinstance(fixed.get("content"), dict):
                fixed["content"] = {"type": "bar", "title": str(fixed.get("content", "Chart")), "labels": [], "datasets": []}

        return fixed
    
    def check_content_quality(self, chapter: Chapter) -> Tuple[bool, List[str]]:
        """
        检查章节内容质量
        
        Args:
            chapter: 章节对象
        
        Returns:
            (is_good_quality, warnings): 质量检查结果和警告列表
        """
        warnings = []
        
        # 1. 字数检查
        word_count = chapter.word_count()
        if word_count < 100:
            warnings.append(f"Chapter is too short: {word_count} words (minimum recommended: 100)")
        
        # 2. 检查内容多样性
        block_types = set(block.type for block in chapter.blocks)
        if len(block_types) == 1 and BlockType.PARAGRAPH in block_types:
            warnings.append("Chapter lacks content diversity (only paragraphs)")
        
        # 3. 检查是否都是标题
        non_heading_count = sum(
            1 for block in chapter.blocks 
            if block.type != BlockType.HEADING
        )
        if non_heading_count == 0:
            warnings.append("Chapter contains only headings, no actual content")
        
        is_good = len(warnings) == 0
        return is_good, warnings
