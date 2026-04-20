"""
SciSpacy Biomedical NER Service — Cassandra Preprocessing Layer

Singleton service providing biomedical Named Entity Recognition powered by
SciSpacy. Used as a **tool-layer enhancement** within existing engine nodes
— NOT a standalone LangGraph agent.

Capabilities:
  1. Entity extraction (GENE/PROTEIN, DRUG, DISEASE, CELL, ORGAN, ORGANISM)
  2. Enhanced entity normalization (fallback when hand-crafted regex misses)
  3. Paper section boundary detection (Methods / Results / Discussion)
  4. Sentence splitting (spaCy-based)

Author: Cassandra Project
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class BioEntity:
    """A single biomedical named entity extracted from text."""
    text: str
    label: str          # e.g. "GENE_OR_GENE_PRODUCT", "SIMPLE_CHEMICAL", "CANCER"
    start: int          # character offset
    end: int
    umls_cui: Optional[str] = None


@dataclass
class ScoredSentence:
    """A sentence annotated with extracted entities."""
    text: str
    entities: List[BioEntity] = field(default_factory=list)
    has_statistics: bool = False
    section: Optional[str] = None       # "Methods", "Results", etc.


@dataclass
class Section:
    """A detected section boundary in a research paper."""
    title: str
    start_char: int
    end_char: int
    sentence_count: int = 0


# ---------------------------------------------------------------------------
# Statistics detection regex (compiled once at module level)
# ---------------------------------------------------------------------------

_STATS_PATTERN = re.compile(
    r"""
      p\s*[<=>≤≥]\s*0\.\d+              |  # p-value
      p\s*=\s*0\.\d+                     |  # p = 0.xxx
      CI\s*[\[\(]                        |  # confidence interval
      HR\s*[=:]\s*\d                     |  # hazard ratio
      OR\s*[=:]\s*\d                     |  # odds ratio
      RR\s*[=:]\s*\d                     |  # relative risk
      n\s*=\s*\d{2,}                     |  # sample size
      hazard\s+ratio                     |
      odds\s+ratio                       |
      confidence\s+interval              |
      relative\s+risk                    |
      median\s+(?:OS|PFS|DFS|overall\s+survival)  |
      (?:overall|progression.free)\s+survival
    """,
    re.IGNORECASE | re.VERBOSE,
)

# ---------------------------------------------------------------------------
# Section heading detection regex
# ---------------------------------------------------------------------------

_SECTION_HEADING_PATTERN = re.compile(
    r"""
      ^\s*(?:\d+\.?\s*)?                 # optional numbering
      (
        abstract     | introduction  | background   |
        methods?     | materials?\s+and\s+methods?   |
        results?     | findings?     |
        discussion   | conclusions?  | summary      |
        supplementary\s*materials?   |
        acknowledgments?             | acknowledgements? |
        references?  | bibliography  |
        appendix     | appendices    |
        limitations? | funding       | disclosures? |
        study\s+design | statistical\s+analysis
      )
      \s*$
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)

# Labels from en_ner_bionlp13cg_md that map to drug/target entities
_DRUG_TARGET_LABELS = frozenset({
    "GENE_OR_GENE_PRODUCT",
    "SIMPLE_CHEMICAL",
    "CHEMICAL",
    "DNA",
    "RNA",
    "PROTEIN",
    "protein",
})

_DISEASE_LABELS = frozenset({
    "CANCER",
    "DISEASE",
    "ORGAN",
    "ORGANISM",
    "PATHOLOGICAL_FORMATION",
    "MULTI-TISSUE_STRUCTURE",
})

_GENE_LABELS = frozenset({
    "GENE_OR_GENE_PRODUCT",
    "DNA",
    "RNA",
    "PROTEIN",
    "protein",
})

# Lightweight SciSpacy model candidates (same 0.5.5 compatibility line)
_LIGHTWEIGHT_MODELS = (
    "en_ner_bionlp13cg_md",
    "en_ner_bc5cdr_md",
    "en_ner_jnlpba_md",
    "en_ner_craft_md",
)


# ---------------------------------------------------------------------------
# SciSpacyNERService (Singleton)
# ---------------------------------------------------------------------------

class SciSpacyNERService:
    """
    Singleton biomedical NER service powered by SciSpacy.

    Thread-safe lazy initialization — the spaCy model is loaded on first use
    and reused for all subsequent calls (~2-3s cold start, ~10ms/sentence
    thereafter, CPU only).

    Usage::

        svc = SciSpacyNERService.get_instance()
        entities = svc.extract_entities("EGFR mutation in NSCLC")
    """

    _instance: Optional["SciSpacyNERService"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._nlp: Any = None
        self._model_name: str = "en_ner_bionlp13cg_md"  # overridden by config if available
        self._model_version: str = "0.5.4"

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "SciSpacyNERService":
        """Return the singleton instance (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Lazy model loading
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load the spaCy model on first call (idempotent)."""
        if self._nlp is not None:
            return

        # Read model name from config if available
        try:
            from config import settings
            self._model_name = getattr(
                settings, "SCISPACY_MODEL_NAME", self._model_name
            )
            self._model_version = getattr(
                settings, "SCISPACY_MODEL_VERSION", self._model_version
            )
        except Exception:
            pass

        try:
            import spacy
        except ImportError:
            logger.error(
                "❌ spacy / scispacy not installed. Run: pip install spacy scispacy"
            )
            raise

        model_candidates: List[str] = []
        for model_name in (self._model_name, *_LIGHTWEIGHT_MODELS):
            if model_name and model_name not in model_candidates:
                model_candidates.append(model_name)

        load_errors: List[str] = []
        for model_name in model_candidates:
            try:
                logger.info(
                    f"🧬 Loading SciSpacy model '{model_name}' ... (first-time only)"
                )
                self._nlp = spacy.load(model_name)
                self._model_name = model_name
                logger.success(
                    f"✅ SciSpacy model loaded: '{model_name}' — {len(self._nlp.pipe_names)} pipeline components"
                )
                return
            except OSError as exc:
                load_errors.append(f"{model_name}: {exc}")

        install_cmds = "\n".join(
            (
                "  pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/"
                f"releases/v{self._model_version}/{name}-{self._model_version}.tar.gz"
            )
            for name in _LIGHTWEIGHT_MODELS
        )
        logger.error(
            "❌ No compatible SciSpacy lightweight model was found.\n"
            f"Tried: {', '.join(model_candidates)}\n"
            f"Install one or more of:\n{install_cmds}\n"
            f"Errors:\n  - " + "\n  - ".join(load_errors)
        )
        raise OSError("No compatible SciSpacy model found")

    # ------------------------------------------------------------------
    # Public API: Entity Extraction
    # ------------------------------------------------------------------

    def extract_entities(self, text: str) -> List[BioEntity]:
        """
        Extract biomedical named entities from *text*.

        Returns a list of ``BioEntity`` with ``text``, ``label``,
        ``start`` and ``end`` character offsets.
        """
        self._ensure_loaded()
        if not text or not text.strip():
            return []

        doc = self._nlp(text)
        entities: List[BioEntity] = []
        for ent in doc.ents:
            entities.append(
                BioEntity(
                    text=ent.text,
                    label=ent.label_,
                    start=ent.start_char,
                    end=ent.end_char,
                )
            )
        return entities



    # ------------------------------------------------------------------
    # Public API: Enhanced Normalisation
    # ------------------------------------------------------------------

    def normalize_entity(self, raw_text: str, entity_type: str = "") -> str:
        """
        Try to normalise *raw_text* using NER-based identification.

        If the NER model finds a plausible gene/protein or chemical entity
        inside *raw_text*, return its canonical surface form (uppercased for
        genes, title-cased for chemicals).  Otherwise return an empty string.

        This is intended as a **fallback** after the hand-crafted regex rules
        in ``biomedical_normalization.py`` have already been tried.
        """
        self._ensure_loaded()
        if not raw_text or not raw_text.strip():
            return ""

        doc = self._nlp(raw_text)
        for ent in doc.ents:
            if ent.label_ in _DRUG_TARGET_LABELS:
                # Genes → UPPER; chemicals → title case
                if ent.label_ == "GENE_OR_GENE_PRODUCT":
                    return ent.text.upper()
                return ent.text.title()
        return ""

    # ------------------------------------------------------------------
    # Public API: Section Boundary Detection
    # ------------------------------------------------------------------

    def detect_section_boundaries(self, text: str) -> List[Section]:
        """
        Detect major IMRaD-style section headings in *text*.

        Uses regex heuristics (not NER) to locate heading lines and returns
        ``Section`` objects with character spans.
        """
        if not text:
            return []

        sections: List[Section] = []
        matches = list(_SECTION_HEADING_PATTERN.finditer(text))

        for i, m in enumerate(matches):
            title = m.group(1).strip().title()
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[start:end]
            sentence_count = len([s for s in chunk.split(".") if s.strip()])

            sections.append(
                Section(
                    title=title,
                    start_char=start,
                    end_char=end,
                    sentence_count=sentence_count,
                )
            )

        return sections

    # ------------------------------------------------------------------
    # Public API: Sentence Splitting (convenience wrapper)
    # ------------------------------------------------------------------

    def split_sentences(self, text: str) -> List[str]:
        """
        Split *text* into sentences using spaCy's sentence segmenter.

        Prefer this over naive ``split('.')`` because spaCy handles
        abbreviations, decimal numbers, and other edge cases.
        """
        self._ensure_loaded()
        if not text or not text.strip():
            return []

        doc = self._nlp(text)
        return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


# ---------------------------------------------------------------------------
# Module-level convenience factory
# ---------------------------------------------------------------------------

def get_ner_service() -> SciSpacyNERService:
    """Return the global ``SciSpacyNERService`` singleton."""
    return SciSpacyNERService.get_instance()
