"""
Word Budget Node - 字数规划节点

根据总体报告长度和各章节重要性，
分配每个章节的目标字数。

借鉴BettaFish的WordBudgetNode设计
"""

from typing import Dict, List, Any
from loguru import logger


class WordBudgetNode:
    """
    字数规划节点
    
    负责为每个章节分配合理的字数预算
    """
    
    # 默认章节权重
    DEFAULT_WEIGHTS = {
        # Disease-oriented review framework
        "disease_landscape": 1.0,
        "executive_summary": 1.0,
        "drug_class_landscape": 1.25,
        "drug_asset_catalog": 1.55,
        "target_mechanism_map": 1.2,
        "company_sponsor_landscape": 1.1,
        "clinical_progress_matrix": 1.45,
        "data_quality_and_gaps": 0.95,
        "scenario_analysis": 1.4,

        # Legacy slugs kept for backward compatibility
        "scientific_rationale": 1.3,
        "dark_data_synthesis": 1.5,
        "knowledge_graph": 0.8,
        "investment_scenarios": 1.4,
        "risk_scoring": 0.9,
        "signal_assessment": 0.9,
        "final_recommendation": 1.0,
    }

    LEGACY_SLUG_ALIASES = {
        "evidence_quality_and_gaps": "data_quality_and_gaps",
        "evidence_scenarios": "scenario_analysis",
        "evidence_conclusion": "final_recommendation",
    }
    
    def __init__(self, total_target_words: int = 5000):
        """
        初始化字数规划节点
        
        Args:
            total_target_words: 报告总目标字数
        """
        self.total_target_words = total_target_words
        logger.info(f"WordBudgetNode initialized with target {total_target_words} words")
    
    def allocate_budgets(
        self,
        sections: List[Dict[str, Any]],
        custom_weights: Dict[str, float] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        为各章节分配字数预算
        
        Args:
            sections: 章节列表，每个章节包含title, slug, outline等
            custom_weights: 自定义权重（可选）
        
        Returns:
            字数分配结果，格式：
            {
                "section_slug": {
                    "target_words": 500,
                    "weight": 1.2,
                    "emphasis": "This section should focus on...",
                    "rationale": "Allocated 10% of total words because..."
                }
            }
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"📊 Word Budget Allocation")
        logger.info(f"   Total Target: {self.total_target_words} words")
        logger.info(f"   Sections: {len(sections)}")
        logger.info(f"{'='*60}")
        
        # 使用自定义权重或默认权重
        weights = custom_weights if custom_weights else self.DEFAULT_WEIGHTS
        
        # 计算总权重
        total_weight = sum(
            weights.get(
                self.LEGACY_SLUG_ALIASES.get(section.get("slug", ""), section.get("slug", "")),
                1.0,
            )
            for section in sections
        )
        
        # 分配字数
        allocations = {}
        
        for section in sections:
            slug = section.get("slug", "")
            title = section.get("title", "Untitled")
            outline = section.get("outline", "")
            
            # 获取权重
            normalized_slug = self.LEGACY_SLUG_ALIASES.get(slug, slug)
            weight = weights.get(normalized_slug, 1.0)
            
            # 计算目标字数
            target_words = int((weight / total_weight) * self.total_target_words)
            
            # 确保最小字数
            target_words = max(target_words, 200)
            
            # 生成强调点
            emphasis = self._generate_emphasis(title, outline, target_words)
            
            # 生成分配理由
            percentage = (target_words / self.total_target_words) * 100
            rationale = (
                f"Allocated {target_words} words ({percentage:.1f}% of total) "
                f"based on weight {weight:.1f}"
            )
            
            allocations[slug] = {
                "target_words": target_words,
                "weight": weight,
                "emphasis": emphasis,
                "rationale": rationale
            }
            
            logger.info(f"   {title}: {target_words} words (weight: {weight:.1f})")
        
        # 验证总和
        total_allocated = sum(a["target_words"] for a in allocations.values())
        logger.info(f"\n   Total Allocated: {total_allocated} words")
        
        if abs(total_allocated - self.total_target_words) > 100:
            logger.warning(
                f"⚠️ Allocation differs from target by "
                f"{abs(total_allocated - self.total_target_words)} words"
            )
        
        return allocations
    
    def _generate_emphasis(self, title: str, outline: str, target_words: int) -> str:
        """
        生成章节强调点
        
        Args:
            title: 章节标题
            outline: 章节大纲
            target_words: 目标字数
        
        Returns:
            强调点说明
        """
        if target_words > 1000:
            return (
                f"This is a major section. Provide comprehensive analysis with "
                f"multiple subsections, detailed evidence, and specific examples."
            )
        elif target_words > 500:
            return (
                f"Provide thorough analysis with key evidence and examples. "
                f"Balance depth with conciseness."
            )
        else:
            return (
                f"Keep this section concise and focused. Highlight only the "
                f"most critical points."
            )
    
    def adjust_budget_based_on_content(
        self,
        allocations: Dict[str, Dict[str, Any]],
        data_metrics: Dict[str, int]
    ) -> Dict[str, Dict[str, Any]]:
        """
        根据实际内容量调整字数分配
        
        Args:
            allocations: 初始字数分配
            data_metrics: 各类数据的数量
                {
                    "record_count": 50,
                    "quality_signal_count": 25
                }
        
        Returns:
            调整后的字数分配
        """
        logger.info("\n🔧 Adjusting budgets based on actual data coverage...")
        
        adjusted = allocations.copy()
        
        # 如果数据量很大，增加资产目录/临床矩阵章节预算
        record_count = data_metrics.get("record_count", data_metrics.get("evidence_count", 0))
        if record_count > 30:
            target_slug = "drug_asset_catalog" if "drug_asset_catalog" in adjusted else "dark_data_synthesis"
            if target_slug in adjusted:
                old_words = adjusted[target_slug]["target_words"]
                new_words = int(old_words * 1.2)  # 增加20%
                adjusted[target_slug]["target_words"] = new_words
                adjusted[target_slug]["rationale"] += (
                    f" (Increased by 20% due to {record_count} source records)"
                )
                logger.info(
                    f"   {target_slug}: {old_words} -> {new_words} words "
                    f"(high data volume)"
                )
        
        # 如果质量信号很多，增加质量评估章节预算
        quality_signal_count = data_metrics.get("quality_signal_count", data_metrics.get("risk_signals", 0))
        if quality_signal_count > 20:
            target_slug = "data_quality_and_gaps" if "data_quality_and_gaps" in adjusted else "evidence_quality_and_gaps"
            if target_slug in adjusted:
                old_words = adjusted[target_slug]["target_words"]
                new_words = int(old_words * 1.2)
                adjusted[target_slug]["target_words"] = new_words
                adjusted[target_slug]["rationale"] += (
                    f" (Increased by 20% due to {quality_signal_count} quality signals)"
                )
                logger.info(
                    f"   {target_slug}: {old_words} -> {new_words} words "
                    f"(high quality-signal count)"
                )
        
        return adjusted


def create_word_budget_node(total_target_words: int = 5000):
    """
    工厂函数：创建字数规划节点
    
    Args:
        total_target_words: 报告总目标字数
    
    Returns:
        WordBudgetNode实例
    """
    return WordBudgetNode(total_target_words)
