"""IR (Intermediate Representation) 模块"""

from .schema import (
    BlockType, 
    HeadingLevel, 
    ChapterBlock, 
    Chapter, 
    IRDocument, 
    IRSchema
)
from .validator import IRValidator

__all__ = [
    'BlockType',
    'HeadingLevel',
    'ChapterBlock',
    'Chapter',
    'IRDocument',
    'IRSchema',
    'IRValidator',
]
