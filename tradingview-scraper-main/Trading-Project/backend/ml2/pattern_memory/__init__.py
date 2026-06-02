"""
pattern_memory — Pattern Memory System for TimeFM-powered historical similarity search.

Public API:
    PatternMemoryDB           — SQLite persistence (pattern_db.py)
    PatternRecord             — Data class for a stored pattern
    PatternSimilarityEngine   — FAISS cosine search (similarity_engine.py)
    OutcomeIntelligence       — Weighted probability statistics (outcome_intelligence.py)
    PatternIntelligence       — Result dataclass
    TimeFMEmbeddingExtractor  — TimeFM embedding extractor (embedding_extractor.py)
    PatternHarvester          — Batch harvesting pipeline (pattern_harvester.py)
"""

from .pattern_db import PatternMemoryDB, PatternRecord, EMBEDDING_VERSION
from .similarity_engine import PatternSimilarityEngine, get_engine
from .outcome_intelligence import OutcomeIntelligence, PatternIntelligence
from .embedding_extractor import TimeFMEmbeddingExtractor
from .pattern_harvester import harvest as PatternHarvester

__all__ = [
    "PatternMemoryDB",
    "PatternRecord",
    "EMBEDDING_VERSION",
    "PatternSimilarityEngine",
    "get_engine",
    "OutcomeIntelligence",
    "PatternIntelligence",
    "TimeFMEmbeddingExtractor",
    "PatternHarvester",
]


