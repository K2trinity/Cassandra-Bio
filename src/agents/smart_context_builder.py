"""
Smart Context Builder - Intelligent Evidence Context Optimizer

This module implements a token-aware context builder that prioritizes
high-impact evidence and compresses low-value information to prevent
SSL errors caused by oversized prompts.

Core Strategy:
1. PRIORITIZE: Extract all high-impact findings first
2. COMPRESS: Fold supplementary papers into one-liners
3. FILL: Dynamically add summaries until token limit

Author: Cassandra Project
Date: 2026-02-09
"""

import re
from typing import List, Dict, Any, Tuple
from loguru import logger
from dataclasses import dataclass


@dataclass
class ContextBudget:
    """Token budget allocation for different evidence types."""
    max_tokens: int = 30000  # Conservative limit (≈120k chars for Gemini)
    critical_reserve: int = 5000  # Reserve for high-impact findings
    summary_per_paper: int = 800  # Avg chars per paper summary
    clean_paper_budget: int = 100  # Chars for "clean" papers
    
    def chars_to_tokens(self, chars: int) -> int:
        """Rough conversion: 1 token ≈ 4 chars."""
        return chars // 4
    
    def tokens_to_chars(self, tokens: int) -> int:
        """Convert tokens back to chars."""
        return tokens * 4


class SmartContextBuilder:
    """
    Intelligent evidence context builder with token awareness.
    
    Optimizes prompt size by:
    1. Prioritizing high-impact evidence
    2. Compressing low-value information
    3. Dynamically filling remaining space
    """
    
    def __init__(self, max_chars: int = 120000):
        """
        Initialize context builder.
        
        Args:
            max_chars: Maximum characters for final context (default: 120k for Gemini)
        """
        self.budget = ContextBudget()
        self.budget.max_tokens = self.budget.chars_to_tokens(max_chars)
        logger.info(f"🧠 Smart Context Builder initialized (max: {max_chars} chars / {self.budget.max_tokens} tokens)")
    
    def build_optimized_context(
        self,
        evidence_items: List[Dict[str, Any]],
    ) -> Tuple[str, Dict[str, int]]:
        """
        Build optimized evidence context with intelligent prioritization.
        
        Args:
            evidence_items: List of evidence dictionaries from EvidenceMiner
        
        Returns:
            Tuple of (optimized_context_string, statistics_dict)
        
        Workflow:
            Phase 1: Extract Critical Risks (TOP PRIORITY)
            Phase 2: Extract Medium Risks
            Phase 3: Compress Clean Papers
            Phase 4: Fill Remaining Space with Summaries
        """
        logger.info("\n" + "="*60)
        logger.info("🧠 SMART CONTEXT BUILDER: Optimizing Evidence")
        logger.info("="*60)
        
        # Initialize containers
        critical_evidence = []
        medium_evidence = []
        clean_evidence = []
        
        # Classify evidence by significance level
        for item in evidence_items:
            significance = item.get('significance', 'UNKNOWN').upper()
            
            if significance in ('HIGH', 'HIGH_IMPACT'):
                critical_evidence.append(item)
            elif significance in ('MEDIUM', 'MODERATE'):
                medium_evidence.append(item)
            else:
                clean_evidence.append(item)
        
        logger.info(f"📊 Evidence Classification:")
        logger.info(f"   - HIGH Impact: {len(critical_evidence)}")
        logger.info(f"   - MODERATE: {len(medium_evidence)}")
        logger.info(f"   - SUPPLEMENTARY/Clean: {len(clean_evidence)}")
        
        # Build context in priority order
        context_parts = []
        char_counter = 0
        max_chars = self.budget.tokens_to_chars(self.budget.max_tokens)
        
        # ============ PHASE 1: CRITICAL RISKS (ALWAYS INCLUDE) ============
        logger.info("\n🚨 Phase 1: Adding Critical Risks (Top Priority)")
        critical_section = self._build_critical_section(critical_evidence)
        critical_chars = len(critical_section)
        
        if critical_chars > 0:
            context_parts.append(critical_section)
            char_counter += critical_chars
            logger.success(f"✅ Critical risks added: {critical_chars} chars ({len(critical_evidence)} items)")
        else:
            logger.info("   No critical risks found")
        
        # ============ PHASE 2: MEDIUM RISKS ============
        logger.info("\n⚠️ Phase 2: Adding Medium Risks")
        remaining_space = max_chars - char_counter - self.budget.tokens_to_chars(self.budget.critical_reserve)
        
        if remaining_space > 0:
            medium_section = self._build_medium_section(medium_evidence, max_chars=remaining_space)
            medium_chars = len(medium_section)
            
            if medium_chars > 0:
                context_parts.append(medium_section)
                char_counter += medium_chars
                logger.success(f"✅ Medium risks added: {medium_chars} chars")
        else:
            logger.warning("⚠️ No space for medium risks - critical risks consumed budget")
        
        # ============ PHASE 3: COMPRESS CLEAN PAPERS ============
        logger.info("\n🗜️ Phase 3: Compressing Clean Papers")
        remaining_space = max_chars - char_counter
        
        if remaining_space > 0 and clean_evidence:
            clean_section = self._build_compressed_clean_section(clean_evidence, max_chars=remaining_space)
            clean_chars = len(clean_section)
            
            if clean_chars > 0:
                context_parts.append(clean_section)
                char_counter += clean_chars
                logger.success(f"✅ Clean papers compressed: {clean_chars} chars ({len(clean_evidence)} papers)")
        
        # ============ PHASE 4: FILL WITH SUMMARIES ============
        logger.info("\n📝 Phase 4: Filling Remaining Space with Summaries")
        remaining_space = max_chars - char_counter
        
        if remaining_space > 1000:  # At least 1000 chars worth adding
            summary_section = self._fill_with_summaries(
                evidence_items,
                max_chars=remaining_space,
                already_included={item.get('filename', '') for item in critical_evidence + medium_evidence}
            )
            summary_chars = len(summary_section)
            
            if summary_chars > 0:
                context_parts.append(summary_section)
                char_counter += summary_chars
                logger.success(f"✅ Summaries filled: {summary_chars} chars")
        else:
            logger.info(f"   Insufficient space ({remaining_space} chars) - skipping summaries")
        
        # Combine all parts
        final_context = "\n\n".join(context_parts)
        final_chars = len(final_context)
        final_tokens = self.budget.chars_to_tokens(final_chars)
        
        # Statistics
        # 🔥 FIX: Prevent division by zero in compression ratio calculation
        original_size = sum(len(str(item.get('paper_summary', ''))) for item in evidence_items)
        
        stats = {
            'total_chars': final_chars,
            'total_tokens': final_tokens,
            'critical_count': len(critical_evidence),
            'medium_count': len(medium_evidence),
            'clean_count': len(clean_evidence),
            'compression_ratio': final_chars / original_size if (evidence_items and original_size > 0) else 1.0  # 🔥 FIX: Default to 1.0 (no compression) if original is empty
        }
        
        logger.info("\n" + "="*60)
        logger.success(f"✅ CONTEXT OPTIMIZATION COMPLETE")
        logger.info(f"   Final Size: {final_chars:,} chars ({final_tokens:,} tokens)")
        logger.info(f"   Budget Usage: {(final_tokens / self.budget.max_tokens * 100):.1f}%")
        logger.info(f"   Compression Ratio: {stats['compression_ratio']:.2%}")
        logger.info("="*60 + "\n")
        
        return final_context, stats

    # ==================================================================
    # V2: SciSpacy NER-based Sentence-Level Importance Scoring
    # ==================================================================

    def build_scored_context(
        self,
        evidence_items: List[Dict[str, Any]],
    ) -> Tuple[str, Dict[str, int]]:
        """
        Build optimized evidence context using **sentence-level NER filtering**.

        This replaces the disabled v1 ``build_optimized_context`` which
        suffered from 91% over-compression.  The new strategy:

        Phase 1 — Split all evidence text into individual sentences
        Phase 2 — Extract entities via SciSpacy NER + statistics regex
        Phase 3 — Hard-protect sentences containing statistical data
        Phase 4 — Fill remaining budget with entity-rich sentences

        Returns
        -------
        (optimized_context, statistics_dict)
        """
        logger.info("\n" + "=" * 60)
        logger.info("🧠 SMART CONTEXT BUILDER V2: NER-Based Sentence Filtering")
        logger.info("=" * 60)

        max_chars = self.budget.tokens_to_chars(self.budget.max_tokens)

        # --- lazy-import NER service (avoids hard dependency at module level) ---
        try:
            from src.tools.scispacy_ner_service import SciSpacyNERService
            ner = SciSpacyNERService.get_instance()
            ner_available = True
        except Exception as exc:
            logger.warning(f"⚠️ SciSpacy unavailable ({exc}), falling back to regex-only filtering")
            ner_available = False

        # Read configurable flag
        try:
            from config import settings
            stats_hard_protect: bool = getattr(settings, "SCISPACY_STATS_HARD_PROTECT", True)
        except Exception:
            stats_hard_protect = True

        # ----- Phase 1: Collect sentences from all evidence items -------
        from src.tools.scispacy_ner_service import ScoredSentence, _STATS_PATTERN

        all_sentences: List[ScoredSentence] = []

        for item in evidence_items:
            text = item.get("paper_summary", "") or item.get("quote", "")
            filename = item.get("filename", "unknown")
            if not text:
                continue

            if ner_available:
                sentences = ner.split_sentences(text)
                for s in sentences:
                    entities = ner.extract_entities(s)
                    has_stats = bool(_STATS_PATTERN.search(s))
                    all_sentences.append(ScoredSentence(
                        text=s,
                        entities=entities,
                        has_statistics=has_stats,
                        section=filename,
                    ))
            else:
                # Fallback: naive sentence split + regex-only
                sentences = [s.strip() for s in text.split(".") if s.strip()]
                for s in sentences:
                    has_stats = bool(_STATS_PATTERN.search(s))
                    all_sentences.append(ScoredSentence(
                        text=s,
                        entities=[],
                        has_statistics=has_stats,
                        section=filename,
                    ))

        logger.info(f"📊 Total sentences collected: {len(all_sentences)}")

        # ----- Phase 2: Separate hard-protected vs entity-rich -----
        protected: List[ScoredSentence] = []
        entity_rich: List[ScoredSentence] = []

        for sc in all_sentences:
            if stats_hard_protect and sc.has_statistics:
                protected.append(sc)
            elif len(sc.entities) > 0:
                entity_rich.append(sc)
            # else: discard (no entities, no statistics)

        # Sort entity-rich by descending entity count
        entity_rich.sort(key=lambda s: len(s.entities), reverse=True)

        discarded_count = len(all_sentences) - len(protected) - len(entity_rich)
        logger.info(f"   🛡️ Hard-protected (statistics): {len(protected)}")
        logger.info(f"   📈 Entity-rich sentences: {len(entity_rich)}")
        logger.info(f"   🗑️ Discarded (no entities): {discarded_count}")

        # ----- Phase 3: Fill budget -----
        context_parts: List[str] = []
        char_counter = 0

        # Protected sentences first
        protected_lines: List[str] = []
        for sc in protected:
            line = f"[📊 {sc.section}] {sc.text}"
            if char_counter + len(line) + 1 > max_chars:
                break
            protected_lines.append(line)
            char_counter += len(line) + 1

        if protected_lines:
            section_header = (
                "=" * 80
                + "\n📊 STATISTICALLY CRITICAL SENTENCES (Hard-Protected)\n"
                + "=" * 80
                + "\n"
            )
            context_parts.append(section_header + "\n".join(protected_lines))
            char_counter += len(section_header)

        # Entity-rich sentences (remaining budget)
        rich_lines: List[str] = []
        for sc in entity_rich:
            ent_count = len(sc.entities)
            line = f"[{ent_count} entities | {sc.section}] {sc.text}"
            if char_counter + len(line) + 1 > max_chars:
                break
            rich_lines.append(line)
            char_counter += len(line) + 1

        if rich_lines:
            section_header = (
                "\n"
                + "=" * 80
                + "\n📈 HIGH-RELEVANCE EVIDENCE (By Entity Density)\n"
                + "=" * 80
                + "\n"
            )
            context_parts.append(section_header + "\n".join(rich_lines))
            char_counter += len(section_header)

        # ----- Phase 4: Assemble and report -----
        final_context = "\n\n".join(context_parts)
        final_chars = len(final_context)
        final_tokens = self.budget.chars_to_tokens(final_chars)

        original_size = sum(
            len(str(item.get("paper_summary", ""))) for item in evidence_items
        )
        compression = final_chars / original_size if original_size > 0 else 1.0

        stats = {
            "total_chars": final_chars,
            "total_tokens": final_tokens,
            "protected_count": len(protected_lines),
            "entity_rich_count": len(rich_lines),
            "discarded_count": discarded_count,
            "compression_ratio": compression,
        }

        logger.info("\n" + "=" * 60)
        logger.success("✅ CONTEXT OPTIMISATION V2 COMPLETE")
        logger.info(f"   Original: {original_size:,} chars")
        logger.info(f"   Final:    {final_chars:,} chars ({final_tokens:,} tokens)")
        logger.info(f"   Budget:   {(final_tokens / self.budget.max_tokens * 100):.1f}%")
        logger.info(f"   Compression: {compression:.1%}")
        logger.info("=" * 60 + "\n")

        return final_context, stats

    def _build_critical_section(
        self,
        critical_items: List[Dict[str, Any]],
    ) -> str:
        """
        Build section for HIGH-risk evidence (always included).
        
        Args:
            critical_items: High-risk evidence items
        
        Returns:
            Formatted critical evidence section
        """
        if not critical_items:
            return ""
        
        lines = [
            "=" * 80,
            "🚨 CRITICAL RISK EVIDENCE (HIGH PRIORITY)",
            "=" * 80,
            ""
        ]
        
        # Add critical text evidence
        for idx, item in enumerate(critical_items, 1):
            filename = item.get('filename', 'Unknown')
            risk_type = item.get('finding_type', 'Unknown')
            quote = item.get('quote', 'N/A')
            explanation = item.get('explanation', 'N/A')
            
            lines.extend([
                f"### 🔴 HIGH IMPACT #{idx}: {risk_type}",
                f"**Source:** {filename}",
                f"**Quote:** {quote[:300]}{'...' if len(quote) > 300 else ''}",
                f"**Analysis:** {explanation[:400]}{'...' if len(explanation) > 400 else ''}",
                ""
            ])
        
        return "\n".join(lines)
    
    def _build_medium_section(
        self,
        medium_items: List[Dict[str, Any]],
        max_chars: int
    ) -> str:
        """
        Build section for MEDIUM-risk evidence (space permitting).
        
        Args:
            medium_items: Medium-risk evidence items
            max_chars: Maximum characters allowed
        
        Returns:
            Formatted medium evidence section
        """
        if not medium_items:
            return ""
        
        lines = [
            "=" * 80,
            "⚠️ MEDIUM RISK EVIDENCE",
            "=" * 80,
            ""
        ]
        
        char_count = len("\n".join(lines))
        items_added = 0
        
        for item in medium_items:
            filename = item.get('filename', 'Unknown')
            risk_type = item.get('finding_type', 'Evidence')
            quote = item.get('quote', 'N/A')
            
            item_text = f"**{filename}** | {risk_type}: {quote[:200]}...\n"
            
            if char_count + len(item_text) > max_chars:
                break
            
            lines.append(item_text)
            char_count += len(item_text)
            items_added += 1
        
        if items_added < len(medium_items):
            lines.append(f"\n_[+{len(medium_items) - items_added} more medium-risk items truncated]_")
        
        return "\n".join(lines) if items_added > 0 else ""
    
    def _build_compressed_clean_section(
        self,
        clean_items: List[Dict[str, Any]],
        max_chars: int
    ) -> str:
        """
        Build compressed section for CLEAN papers (one-line summaries).
        
        Args:
            clean_items: Low-risk/clean evidence items
            max_chars: Maximum characters allowed
        
        Returns:
            Compressed clean section
        """
        if not clean_items:
            return ""
        
        lines = [
            "=" * 80,
            "✅ CLEAN PAPERS (No Significant Risks Detected)",
            "=" * 80,
            ""
        ]
        
        char_count = len("\n".join(lines))
        items_added = 0
        
        for item in clean_items:
            filename = item.get('filename', 'Unknown')
            # Ultra-compressed: just filename + status
            item_text = f"- {filename}: No significant risks identified\n"
            
            if char_count + len(item_text) > max_chars:
                break
            
            lines.append(item_text)
            char_count += len(item_text)
            items_added += 1
        
        if items_added < len(clean_items):
            lines.append(f"\n_[+{len(clean_items) - items_added} more clean papers omitted]_")
        
        return "\n".join(lines) if items_added > 0 else ""
    
    def _fill_with_summaries(
        self,
        all_items: List[Dict[str, Any]],
        max_chars: int,
        already_included: set
    ) -> str:
        """
        Fill remaining space with paper summaries (not already included).
        
        Args:
            all_items: All evidence items
            max_chars: Maximum characters allowed
            already_included: Set of filenames already included
        
        Returns:
            Summary section
        """
        lines = [
            "=" * 80,
            "📚 ADDITIONAL PAPER SUMMARIES",
            "=" * 80,
            ""
        ]
        
        char_count = len("\n".join(lines))
        items_added = 0
        
        for item in all_items:
            filename = item.get('filename', 'Unknown')
            
            # Skip if already included
            if filename in already_included:
                continue
            
            summary = item.get('paper_summary', 'No summary available')
            # Truncate summary to fit budget
            truncated_summary = summary[:800] + "..." if len(summary) > 800 else summary
            
            item_text = f"### {filename}\n{truncated_summary}\n\n"
            
            if char_count + len(item_text) > max_chars:
                break
            
            lines.append(item_text)
            char_count += len(item_text)
            items_added += 1
            already_included.add(filename)
        
        return "\n".join(lines) if items_added > 0 else ""


def create_smart_context_builder(max_chars: int = 120000) -> SmartContextBuilder:
    """
    Factory function to create SmartContextBuilder instance.
    
    Args:
        max_chars: Maximum characters for context (default: 120k)
    
    Returns:
        SmartContextBuilder instance
    """
    return SmartContextBuilder(max_chars=max_chars)
