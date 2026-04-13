"""
IR (Intermediate Representation) Schema v2.0

定义报告生成的中间表示格式，用于：
1. LLM输出的结构化验证
2. 章节内容的标准化存储
3. 最终报告的组装（一次生成，多格式输出：HTML/PDF/Markdown）

支持全量block类型（借鉴BettaFish并扩展）：
- heading: 标题（H1-H4）
- paragraph: 段落
- list: 有序/无序列表
- quote: 引用块
- chart: Chart.js 图表（bar/line/pie/scatter等10+种）
- table: 数据表格（支持合并单元格）
- formula: LaTeX数学公式
- wordcloud: 词云图
- image: 图片（含带标题的Figure）
- callout: 警告/提示/信息框
- code: 代码块（支持语法高亮）
- divider: 分割线
"""

from typing import List, Dict, Any, Optional, Literal
from dataclasses import dataclass, field
from enum import Enum


class BlockType(str, Enum):
    """Block类型枚举"""
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    QUOTE = "quote"
    CHART = "chart"
    TABLE = "table"           # 数据表格
    FORMULA = "formula"       # LaTeX 数学公式
    WORDCLOUD = "wordcloud"   # 词云图
    IMAGE = "image"           # 图片/Figure
    CALLOUT = "callout"       # 警告框、提示框等
    CODE = "code"             # 代码块
    DIVIDER = "divider"       # 水平分隔线


class HeadingLevel(int, Enum):
    """标题级别"""
    H1 = 1
    H2 = 2
    H3 = 3
    H4 = 4


@dataclass
class ChapterBlock:
    """
    章节内容块 v2.0

    content 规范（按 type）:
    - heading   : str（标题文本）
    - paragraph : str（段落文本，支持 **bold** / *italic* Markdown内联）
    - list      : List[str | dict]（列表项；dict时可含 "text"/"sub_items"）
    - quote     : str
    - code      : str（代码文本）；metadata: {"language": "python"}
    - divider   : None 或 ""
    - callout   : str；metadata: {"variant": "warning|info|success|error", "title": "..."}
    - image     : str（URL 或 base64 data-URI）；metadata: {"caption": "...", "alt": "..."}
    - formula   : str（LaTeX 公式字符串，例如 r"\alpha = \beta"）；
                  metadata: {"display": true/false}  display=True 为块级公式
    - wordcloud : List[{"word": str, "weight": float}] 或 Dict[str, float]
    - table     : {
                    "headers": List[str],
                    "rows": List[List[str]],
                    "caption": str (optional),
                    "col_widths": List[str] (optional, e.g. ["20%","30%","50%"])
                  }
    - chart     : {
                    "type": "bar"|"line"|"pie"|"doughnut"|"scatter"|"radar"|"bubble",
                    "title": str,
                    "labels": List[str],
                    "datasets": [{"label": str, "data": List[float], "backgroundColor": ...}],
                    "options": dict (Chart.js options, optional)
                  }

    Attributes:
        type: Block类型
        content: Block内容（见上规范）
        level: 标题级别（仅用于heading类型，1-4）
        block_id: 唯一ID，用于前端锚点
        metadata: 额外元数据
    """
    type: BlockType
    content: Any
    level: Optional[int] = None          # For headings
    block_id: Optional[str] = None       # Unique anchor ID
    metadata: Dict[str, Any] = field(default_factory=dict)

    def word_count(self) -> int:
        """估算本 block 的字数（用于章节字数统计）"""
        if self.type in (BlockType.PARAGRAPH, BlockType.QUOTE, BlockType.CODE, BlockType.CALLOUT):
            return len(str(self.content).split())
        elif self.type == BlockType.LIST:
            items = self.content if isinstance(self.content, list) else []
            return sum(len(str(i).split()) for i in items)
        elif self.type == BlockType.TABLE:
            if isinstance(self.content, dict):
                return sum(
                    len(str(cell).split())
                    for row in self.content.get("rows", [])
                    for cell in row
                )
        elif self.type == BlockType.HEADING:
            return len(str(self.content).split())
        return 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result: Dict[str, Any] = {
            "type": self.type.value,
            "content": self.content,
        }
        if self.level is not None:
            result["level"] = self.level
        if self.block_id is not None:
            result["block_id"] = self.block_id
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChapterBlock":
        """从字典创建"""
        return cls(
            type=BlockType(data["type"]),
            content=data["content"],
            level=data.get("level"),
            block_id=data.get("block_id"),
            metadata=data.get("metadata", {})
        )


@dataclass
class Chapter:
    """
    章节
    
    Attributes:
        id: 章节唯一标识
        title: 章节标题
        slug: URL友好的标识符
        order: 章节顺序
        blocks: 内容块列表
        metadata: 章节元数据（字数统计、生成时间等）
    """
    id: str
    title: str
    slug: str
    order: int
    blocks: List[ChapterBlock] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "title": self.title,
            "slug": self.slug,
            "order": self.order,
            "blocks": [block.to_dict() for block in self.blocks],
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Chapter":
        """从字典创建"""
        return cls(
            id=data["id"],
            title=data["title"],
            slug=data["slug"],
            order=data["order"],
            blocks=[ChapterBlock.from_dict(b) for b in data.get("blocks", [])],
            metadata=data.get("metadata", {})
        )
    
    def word_count(self) -> int:
        """计算字数"""
        total = 0
        for block in self.blocks:
            if block.type in [BlockType.PARAGRAPH, BlockType.QUOTE, BlockType.CODE]:
                total += len(str(block.content).split())
            elif block.type == BlockType.LIST:
                for item in block.content:
                    total += len(str(item).split())
            elif block.type == BlockType.TABLE:
                if isinstance(block.content, dict):
                    for row in block.content.get("rows", []):
                        for cell in row:
                            total += len(str(cell).split())
            elif block.type == BlockType.CALLOUT:
                total += len(str(block.content).split())
        return total


@dataclass
class IRDocument:
    """
    IR文档（完整报告）
    
    Attributes:
        title: 报告标题
        subtitle: 副标题（可选）
        query: 原始查询（可选）
        chapters: 章节列表
        metadata: 文档元数据（生成时间、作者、风险评分等）
    """
    title: str
    chapters: List[Chapter] = field(default_factory=list)
    subtitle: Optional[str] = None
    query: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "query": self.query,
            "chapters": [chapter.to_dict() for chapter in self.chapters],
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IRDocument":
        """从字典创建"""
        return cls(
            title=data["title"],
            subtitle=data.get("subtitle"),
            query=data["query"],
            chapters=[Chapter.from_dict(c) for c in data.get("chapters", [])],
            metadata=data.get("metadata", {})
        )
    
    def total_word_count(self) -> int:
        """计算总字数"""
        return sum(chapter.word_count() for chapter in self.chapters)


class IRSchema:
    """
    IR Schema工具类
    
    提供Schema验证、转换等功能
    """
    
    @staticmethod
    def get_chapter_schema() -> Dict[str, Any]:
        """获取章节JSON Schema"""
        return {
            "type": "object",
            "required": ["title", "blocks"],
            "properties": {
                "title": {"type": "string"},
                "blocks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["type", "content"],
                        "properties": {
                            "type": {"type": "string", "enum": [t.value for t in BlockType]},
                            "content": {},  # Can be string, list, or dict
                            "level": {"type": "integer", "minimum": 1, "maximum": 4},
                            "metadata": {"type": "object"}
                        }
                    }
                }
            }
        }
    
    @staticmethod
    def validate_block_type(block_type: str) -> bool:
        """验证block类型"""
        try:
            BlockType(block_type)
            return True
        except ValueError:
            return False
