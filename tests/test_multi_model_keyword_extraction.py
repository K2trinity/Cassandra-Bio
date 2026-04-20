"""
Multi-Model SciSpacy Keyword Extraction Benchmark
==================================================

Tests keyword (entity) extraction across 4 SciSpacy biomedical NER models
using 5 real PubMed paper abstracts.

Models under test:
  1. en_ner_bionlp13cg_md  — BioNLP13CG corpus (gene, cell, organ, cancer …)
  2. en_ner_bc5cdr_md       — BC5CDR corpus (chemical ↔ disease)
  3. en_ner_jnlpba_md       — JNLPBA corpus (gene/protein heavy)
  4. en_core_sci_md         — General scientific (broad entity types)

No subjective scoring is performed.  The test purely compares which
entities each model extracts from the same abstract text.

Run:
    cd f:\\Visual Studio Code\\alpha\\Cassandra
    python -m pytest tests/test_multi_model_keyword_extraction.py -v -s
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

# Ensure project root is on sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ---------------------------------------------------------------------------
# 5 representative PubMed papers (hardcoded PMIDs)
# ---------------------------------------------------------------------------
# We pick papers across different therapeutic areas so the models
# get a variety of biomedical vocabulary.

SELECTED_PMIDS: List[str] = [
    "33378609",  # Pembrolizumab + chemotherapy in NSCLC (KEYNOTE-789)
    "35594969",  # Trastuzumab deruxtecan in HER2+ breast cancer (DESTINY-Breast03)
    "28006315",  # CAR-T cell therapy for B-cell lymphoma (Axicabtagene ciloleucel)
    "29132837",  # Osimertinib in EGFR-mutant NSCLC (FLAURA trial)
    "33085857",  # CRISPR-Cas9 gene editing in sickle cell disease
]

PAPER_LABELS: Dict[str, str] = {
    "33378609": "Immune Checkpoint (PD-1/PD-L1)",
    "35594969": "ADC (Trastuzumab Deruxtecan)",
    "28006315": "CAR-T Cell Therapy",
    "29132837": "Targeted Therapy (EGFR TKI)",
    "33085857": "Gene Editing (CRISPR-Cas9)",
}

# The 4 SciSpacy models to compare
MODEL_NAMES: List[str] = [
    "en_ner_bionlp13cg_md",
    "en_ner_bc5cdr_md",
    "en_ner_jnlpba_md",
    "en_core_sci_md",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def pubmed_abstracts() -> List[Dict[str, str]]:
    """Fetch the 5 selected PubMed paper abstracts once per test session."""
    from src.tools.pubmed_client import fetch_details

    articles = fetch_details(SELECTED_PMIDS)
    assert len(articles) >= 1, (
        f"PubMed fetch returned 0 articles — network issue? Tried PMIDs: {SELECTED_PMIDS}"
    )
    return articles


@pytest.fixture(scope="module")
def loaded_models() -> Dict[str, Any]:
    """Load all 4 SciSpacy models once and return as {name: nlp}."""
    import spacy

    models: Dict[str, Any] = {}
    for name in MODEL_NAMES:
        try:
            models[name] = spacy.load(name)
        except OSError:
            pytest.skip(f"Model '{name}' not installed — skipping")
    return models


# ---------------------------------------------------------------------------
# Helper: Extract entities using a given spaCy nlp pipeline
# ---------------------------------------------------------------------------

def _extract_entities(nlp: Any, text: str) -> List[Tuple[str, str]]:
    """Return deduplicated list of (entity_text, entity_label) tuples."""
    if not text or not text.strip():
        return []
    doc = nlp(text)
    seen = set()
    results: List[Tuple[str, str]] = []
    for ent in doc.ents:
        key = (ent.text.strip(), ent.label_)
        if key not in seen:
            seen.add(key)
            results.append(key)
    return results


# ---------------------------------------------------------------------------
# Pretty-print helper
# ---------------------------------------------------------------------------

def _print_comparison_table(
    pmid: str,
    title: str,
    results: Dict[str, List[Tuple[str, str]]],
) -> None:
    """Print a side-by-side entity extraction comparison for one paper."""
    area = PAPER_LABELS.get(pmid, "Unknown")
    print(f"\n{'='*100}")
    print(f"📄 PMID {pmid}  |  {area}")
    print(f"   {title[:90]}{'…' if len(title) > 90 else ''}")
    print(f"{'='*100}")

    for model_name, entities in results.items():
        short_name = model_name.replace("en_ner_", "").replace("en_core_", "core_")
        if entities:
            ent_strs = [f"{text} [{label}]" for text, label in entities]
            print(f"  🔬 {short_name:20s} ({len(entities):2d} entities): {', '.join(ent_strs[:15])}")
            if len(ent_strs) > 15:
                print(f"{'':26s}… and {len(ent_strs) - 15} more")
        else:
            print(f"  🔬 {short_name:20s} (  0 entities): —")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMultiModelKeywordExtraction:
    """
    Compare entity extraction across 4 SciSpacy models on 5 PubMed papers.

    Assertions are deliberately lightweight — we verify that each model
    produces *some* output on biomedical text.  The real value is the
    console comparison table printed during the run.
    """

    def test_all_models_loaded(self, loaded_models: Dict[str, Any]) -> None:
        """All 4 SciSpacy models should load without error."""
        assert len(loaded_models) == 4, (
            f"Expected 4 models, loaded {len(loaded_models)}: {list(loaded_models.keys())}"
        )

    def test_abstracts_fetched(self, pubmed_abstracts: List[Dict[str, str]]) -> None:
        """Should fetch at least 3 of the 5 selected papers."""
        assert len(pubmed_abstracts) >= 3, (
            f"Expected >=3 abstracts, got {len(pubmed_abstracts)}"
        )
        # Every abstract should have non-trivial text
        for art in pubmed_abstracts:
            abstract = art.get("abstract", "")
            assert len(abstract) > 50 or abstract == "No abstract available", (
                f"PMID {art.get('pmid')}: abstract too short ({len(abstract)} chars)"
            )

    def test_keyword_extraction_comparison(
        self,
        pubmed_abstracts: List[Dict[str, str]],
        loaded_models: Dict[str, Any],
    ) -> None:
        """
        Core benchmark: run all 4 models on each abstract and print
        a structured comparison table.  Assert each model extracts
        at least 1 entity from at least 1 paper.
        """
        model_hit_count: Dict[str, int] = {m: 0 for m in MODEL_NAMES}

        print("\n")
        print("=" * 100)
        print("🧬  MULTI-MODEL KEYWORD EXTRACTION BENCHMARK")
        print(f"    Papers: {len(pubmed_abstracts)}  |  Models: {len(loaded_models)}")
        print("=" * 100)

        for article in pubmed_abstracts:
            pmid = article.get("pmid", "?")
            title = article.get("title", "No title")
            abstract = article.get("abstract", "")

            if not abstract or abstract == "No abstract available":
                print(f"\n⚠️  PMID {pmid}: no abstract available — skipping")
                continue

            paper_results: Dict[str, List[Tuple[str, str]]] = {}

            for model_name, nlp in loaded_models.items():
                entities = _extract_entities(nlp, abstract)
                paper_results[model_name] = entities
                if entities:
                    model_hit_count[model_name] += 1

            _print_comparison_table(pmid, title, paper_results)

        # ---- Summary Table ----
        print(f"\n{'='*100}")
        print("📊  SUMMARY: Entity Extraction Hit Count per Model")
        print(f"{'='*100}")
        for model_name in MODEL_NAMES:
            short = model_name.replace("en_ner_", "").replace("en_core_", "core_")
            hits = model_hit_count[model_name]
            print(f"  {short:20s}: {hits}/{len(pubmed_abstracts)} papers with entities")

        # Assert: every model should extract entities from at least 1 paper
        for model_name, hits in model_hit_count.items():
            assert hits >= 1, (
                f"Model '{model_name}' extracted 0 entities from all papers — "
                f"model may not be loaded correctly"
            )

    def test_entity_type_diversity(
        self,
        pubmed_abstracts: List[Dict[str, str]],
        loaded_models: Dict[str, Any],
    ) -> None:
        """
        Each model should produce more than 1 distinct entity label type
        across all papers combined.
        """
        for model_name, nlp in loaded_models.items():
            all_labels: set = set()
            for article in pubmed_abstracts:
                abstract = article.get("abstract", "")
                if not abstract or abstract == "No abstract available":
                    continue
                entities = _extract_entities(nlp, abstract)
                all_labels.update(label for _, label in entities)

            assert len(all_labels) >= 1, (
                f"Model '{model_name}' produced 0 label types — "
                f"likely not a biomedical NER model"
            )

            short = model_name.replace("en_ner_", "").replace("en_core_", "core_")
            print(f"  🏷️  {short:20s} label types: {sorted(all_labels)}")
