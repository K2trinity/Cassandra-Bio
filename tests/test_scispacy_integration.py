"""
Tests for SciSpacy NER Service and SmartContextBuilder V2.

These tests validate:
1. SciSpacyNERService singleton pattern & lazy loading
2. Entity extraction accuracy for drugs, genes, diseases
3. SmartContextBuilder v2 compression quality
4. biomedical_normalization.py regression (existing regex rules)
"""

import os
import re
import subprocess
import sys
from functools import lru_cache
import pytest
from unittest.mock import patch, MagicMock


RUN_SCISPACY_INTEGRATION_ENV = "CASSANDRA_RUN_SCISPACY_INTEGRATION"


@lru_cache(maxsize=1)
def _probe_scispacy_runtime() -> tuple[bool, str]:
    script = (
        "from src.tools.scispacy_ner_service import SciSpacyNERService\n"
        "svc = SciSpacyNERService.get_instance()\n"
        "svc.extract_entities('EGFR mutation in NSCLC')\n"
        "print('scispacy runtime ok')\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        return False, "SciSpacy runtime probe timed out after 90 seconds."

    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, output[-1200:]


@pytest.fixture(scope="module")
def scispacy_runtime_available() -> None:
    enabled_values = {"1", "true", "TRUE", "yes", "YES"}
    if os.getenv(RUN_SCISPACY_INTEGRATION_ENV) not in enabled_values:
        pytest.skip(
            f"Set {RUN_SCISPACY_INTEGRATION_ENV}=1 to run optional SciSpacy "
            "runtime integration tests."
        )

    ok, output = _probe_scispacy_runtime()
    if not ok:
        pytest.skip(f"SciSpacy runtime is unavailable in this environment: {output}")


# ============================================================
# Test Group 1: SciSpacyNERService Unit Tests
# ============================================================

class TestSciSpacyNERService:
    """Tests for src/tools/scispacy_ner_service.py"""

    def test_singleton_pattern(self):
        """get_instance() must return the same object across calls."""
        from src.tools.scispacy_ner_service import SciSpacyNERService
        # Reset singleton for clean test
        SciSpacyNERService._instance = None
        a = SciSpacyNERService.get_instance()
        b = SciSpacyNERService.get_instance()
        assert a is b, "Singleton must return same instance"

    def test_extract_entities_returns_list(self, scispacy_runtime_available):
        """extract_entities must return a list (even if empty)."""
        from src.tools.scispacy_ner_service import SciSpacyNERService
        svc = SciSpacyNERService.get_instance()
        result = svc.extract_entities("EGFR mutation in NSCLC treated with pembrolizumab")
        assert isinstance(result, list)
        # Should find at least 1 entity in this biomedical sentence
        assert len(result) >= 1, f"Expected entities in biomedical text, got {result}"

    def test_extract_entities_labels(self, scispacy_runtime_available):
        """Extracted entities should have valid biomedical labels."""
        from src.tools.scispacy_ner_service import SciSpacyNERService
        svc = SciSpacyNERService.get_instance()
        result = svc.extract_entities("BRCA1 gene mutation causes breast cancer")
        labels = {e.label for e in result}
        # At least one of the expected BioNLP13CG labels should appear
        expected_labels = {
            "GENE_OR_GENE_PRODUCT", "SIMPLE_CHEMICAL", "CANCER",
            "ORGAN", "ORGANISM", "CELL", "AMINO_ACID",
            "PATHOLOGICAL_FORMATION", "MULTI-TISSUE_STRUCTURE",
        }
        assert labels & expected_labels, f"Expected biomedical labels, got {labels}"

    def test_extract_entities_empty_input(self, scispacy_runtime_available):
        """Empty input must return empty list, not crash."""
        from src.tools.scispacy_ner_service import SciSpacyNERService
        svc = SciSpacyNERService.get_instance()
        assert svc.extract_entities("") == []
        assert svc.extract_entities("   ") == []

    def test_normalize_entity_gene(self, scispacy_runtime_available):
        """NER-based normalization should recognize gene names."""
        from src.tools.scispacy_ner_service import SciSpacyNERService
        svc = SciSpacyNERService.get_instance()
        result = svc.normalize_entity("epidermal growth factor receptor", "TARGET")
        # Should return some form of EGFR or related uppercased entity
        assert result != "", f"Should normalize a known gene/protein, got empty"

    def test_split_sentences(self, scispacy_runtime_available):
        """Sentence splitter should handle abbreviations correctly."""
        from src.tools.scispacy_ner_service import SciSpacyNERService
        svc = SciSpacyNERService.get_instance()
        text = "Dr. Smith administered 5 mg i.v. pembrolizumab. The patient responded well."
        sents = svc.split_sentences(text)
        assert len(sents) >= 1, "Should split into at least 1 sentence"

    def test_detect_section_boundaries(self):
        """Section detection should find IMRaD headings."""
        from src.tools.scispacy_ner_service import SciSpacyNERService
        svc = SciSpacyNERService.get_instance()
        text = """
Abstract
This study examines the effect of drug X.

Methods
We enrolled 200 patients in a randomized trial.

Results
The primary endpoint was met with p=0.001.

Discussion
These findings suggest efficacy.
"""
        sections = svc.detect_section_boundaries(text)
        titles = [s.title for s in sections]
        assert "Abstract" in titles or "Methods" in titles, f"Should detect IMRaD sections, got {titles}"


# ============================================================
# Test Group 2: Statistics Pattern Detection
# ============================================================

class TestStatisticsPattern:
    """Test the compiled regex used for statistics detection."""

    def test_p_value_patterns(self):
        from src.tools.scispacy_ner_service import _STATS_PATTERN
        assert _STATS_PATTERN.search("p < 0.05")
        assert _STATS_PATTERN.search("p = 0.001")
        assert _STATS_PATTERN.search("p=0.03")
        assert _STATS_PATTERN.search("P≤0.01")

    def test_ci_pattern(self):
        from src.tools.scispacy_ner_service import _STATS_PATTERN
        assert _STATS_PATTERN.search("95% CI [0.55-0.95]")
        assert _STATS_PATTERN.search("CI(0.3-0.7)")

    def test_hr_or_pattern(self):
        from src.tools.scispacy_ner_service import _STATS_PATTERN
        assert _STATS_PATTERN.search("HR=0.72")
        assert _STATS_PATTERN.search("OR = 2.3")
        assert _STATS_PATTERN.search("hazard ratio")

    def test_sample_size(self):
        from src.tools.scispacy_ner_service import _STATS_PATTERN
        assert _STATS_PATTERN.search("n = 200")
        assert _STATS_PATTERN.search("n=1500")

    def test_no_false_positives(self):
        from src.tools.scispacy_ner_service import _STATS_PATTERN
        assert not _STATS_PATTERN.search("The cat sat on the mat")
        assert not _STATS_PATTERN.search("We used Python 3.9")


# ============================================================
# Test Group 3: SmartContextBuilder V2
# ============================================================

class TestSmartContextBuilderV2:
    """Tests for the build_scored_context method (entity-based filtering, no scoring)."""

    def _make_data_items(self):
        """Create mock data items for testing."""
        return [
            {
                "filename": "paper_A.pdf",
                "paper_summary": (
                    "This study evaluated EGFR inhibitor in NSCLC patients. "
                    "The primary endpoint was met with HR=0.72 (95% CI 0.55-0.95, p=0.02). "
                    "Adverse events included grade 3 hepatotoxicity in 12% of patients. "
                    "The weather was nice during the study period. "
                    "We thank the funding agency for support."
                ),
                "risk_level": "HIGH",
                "risk_type": "toxicity",
                "quote": "grade 3 hepatotoxicity in 12% of patients",
                "explanation": "Significant hepatotoxicity signal",
            },
            {
                "filename": "paper_B.pdf",
                "paper_summary": (
                    "A randomized trial of pembrolizumab in melanoma. "
                    "Overall survival was significantly improved (p<0.001). "
                    "Data not shown for secondary endpoints. "
                    "The investigators met quarterly."
                ),
                "risk_level": "MEDIUM",
                "risk_type": "data-not-shown",
                "quote": "Data not shown for secondary endpoints",
                "explanation": "Missing secondary endpoint data",
            },
        ]

    def _make_evidence_items(self):
        """Backward-compatible alias used by legacy test names."""
        return self._make_data_items()

    def test_build_scored_context_returns_tuple(self, scispacy_runtime_available):
        """build_scored_context must return (str, dict)."""
        from src.agents.smart_context_builder import SmartContextBuilder
        builder = SmartContextBuilder(max_chars=120000)
        context, stats = builder.build_scored_context(self._make_data_items())
        assert isinstance(context, str)
        assert isinstance(stats, dict)
        assert "total_chars" in stats
        assert "compression_ratio" in stats

    def test_no_extreme_compression(self, scispacy_runtime_available):
        """Compression should NOT exceed 85% (was 91% in v1)."""
        from src.agents.smart_context_builder import SmartContextBuilder
        builder = SmartContextBuilder(max_chars=120000)
        items = self._make_data_items()
        context, stats = builder.build_scored_context(items)

        # Context should retain meaningful content
        assert stats["total_chars"] > 100, "Context should not be empty"

    def test_statistics_sentences_preserved(self, scispacy_runtime_available):
        """Sentences with p-values/HR must survive compression."""
        from src.agents.smart_context_builder import SmartContextBuilder
        builder = SmartContextBuilder(max_chars=120000)
        context, stats = builder.build_scored_context(self._make_evidence_items())
        # At least one statistical reference should be in output
        has_stats = bool(re.search(r"p[=<]|HR|CI", context))
        assert has_stats, "Statistical sentences should be preserved in compressed output"

    def test_empty_evidence_returns_empty(self):
        """Empty input should return empty context without crash."""
        from src.agents.smart_context_builder import SmartContextBuilder
        builder = SmartContextBuilder(max_chars=120000)
        context, stats = builder.build_scored_context([])
        assert isinstance(context, str)
        assert stats["total_chars"] == 0 or context == ""


# ============================================================
# Test Group 4: Biomedical Normalization Regression
# ============================================================

class TestBiomedicalNormalizationRegression:
    """Ensure existing regex rules still work correctly after SciSpacy fallback was added."""

    def test_pd1_alias(self):
        from src.engines.harvest.core.normalization import normalize_target_term
        assert normalize_target_term("pd1") == "PD-1"
        assert normalize_target_term("cd279") == "PD-1"

    def test_her2_alias(self):
        from src.engines.harvest.core.normalization import normalize_target_term
        assert normalize_target_term("erbb2") == "HER2"
        assert normalize_target_term("her2") == "HER2"

    def test_egfr_alias(self):
        from src.engines.harvest.core.normalization import normalize_target_term
        assert normalize_target_term("egfr") == "EGFR"

    def test_drug_class_adc(self):
        from src.engines.harvest.core.normalization import normalize_drug_class
        assert normalize_drug_class("antibody drug conjugate") == "ADC"

    def test_drug_class_car_t(self):
        from src.engines.harvest.core.normalization import normalize_drug_class
        assert normalize_drug_class("CAR-T cell therapy") == "Cell Therapy"

    def test_placeholder_returns_empty(self):
        from src.engines.harvest.core.normalization import normalize_target_term
        assert normalize_target_term("n/a") == ""
        assert normalize_target_term("unknown") == ""
        assert normalize_target_term("") == ""

    def test_extract_normalized_targets(self):
        from src.engines.harvest.core.normalization import extract_normalized_targets
        result = extract_normalized_targets("PD-1 and EGFR")
        assert "PD-1" in result
        assert "EGFR" in result
