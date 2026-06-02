"""
FAISS Similarity Engine — Phase 4
Cosine similarity search over TimeFM pattern embeddings.
Uses IndexFlatIP with L2-normalized vectors (= exact cosine similarity).
"""
from __future__ import annotations

import os
import time
import logging
import threading
import numpy as np
from typing import List, Tuple, Optional

log = logging.getLogger(__name__)

_DEFAULT_INDEX_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pattern_memory.faiss"
)
_DEFAULT_IDS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pattern_memory_ids.npy"
)

REBUILD_THRESHOLD = 100   # auto-rebuild if this many new patterns added since last build


class PatternSimilarityEngine:
    """
    FAISS-backed cosine similarity engine for pattern embeddings.

    Workflow:
        1. build_index()  — loads all embeddings from PatternMemoryDB, normalizes, builds index
        2. search()       — query with a new embedding, returns top-K (pattern_id, score) pairs
        3. Rebuild is triggered automatically when > REBUILD_THRESHOLD new patterns are added
    """

    def __init__(
        self,
        index_path: str = _DEFAULT_INDEX_PATH,
        ids_path:   str = _DEFAULT_IDS_PATH,
    ):
        self.index_path  = index_path
        self.ids_path    = ids_path
        self._index      = None          # faiss.IndexFlatIP
        self._ids: List[str] = []        # pattern_ids aligned with FAISS internal indices
        self._lock = threading.Lock()
        self._n_at_last_build = 0

    # ── Build ──────────────────────────────────────────────────────────────────

    def build_index(self, pattern_db) -> int:
        """
        Build (or rebuild) the FAISS index from all embeddings in pattern_db.

        Args:
            pattern_db: PatternMemoryDB instance

        Returns:
            Number of vectors in the built index.
        """
        try:
            import faiss
        except ImportError:
            raise ImportError(
                "faiss-cpu not installed. Run: pip install faiss-cpu"
            )

        log.info("[similarity] Building FAISS index from PatternMemoryDB...")
        ids, matrix = pattern_db.get_all_embeddings()

        if len(ids) == 0:
            log.warning("[similarity] No embeddings in DB — index is empty")
            with self._lock:
                d = 512   # placeholder dimension; will be fixed on first real build
                self._index = faiss.IndexFlatIP(d)
                self._ids = []
                self._n_at_last_build = 0
            return 0

        d = matrix.shape[1]
        log.info("[similarity] %d embeddings, dim=%d", len(ids), d)

        # L2-normalize each row → cosine via inner product
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        matrix_norm = (matrix / norms).astype(np.float32)

        index = faiss.IndexFlatIP(d)
        index.add(matrix_norm)

        # Persist to disk
        faiss.write_index(index, self.index_path)
        np.save(self.ids_path, np.array(ids))

        with self._lock:
            self._index = index
            self._ids   = ids
            self._n_at_last_build = len(ids)

        log.info("[similarity] FAISS index built: %d vectors (dim=%d) → %s", len(ids), d, self.index_path)
        return len(ids)

    def load_index(self) -> bool:
        """
        Load a pre-built index from disk.
        Returns True if successful, False if index file doesn't exist.
        """
        if not os.path.exists(self.index_path) or not os.path.exists(self.ids_path):
            log.info("[similarity] No saved index found at %s", self.index_path)
            return False

        try:
            import faiss
        except ImportError:
            raise ImportError("faiss-cpu not installed. Run: pip install faiss-cpu")

        index = faiss.read_index(self.index_path)
        ids   = np.load(self.ids_path, allow_pickle=True).tolist()

        with self._lock:
            self._index = index
            self._ids   = ids
            self._n_at_last_build = len(ids)

        log.info("[similarity] Loaded FAISS index: %d vectors from %s", len(ids), self.index_path)
        return True

    # ── Search ─────────────────────────────────────────────────────────────────

    def search(
        self,
        query_embedding: np.ndarray,
        k: int = 100,
        exclude_ids: Optional[List[str]] = None,
    ) -> List[Tuple[str, float]]:
        """
        Find top-K most similar historical patterns.

        Args:
            query_embedding: 1D float32 numpy array [D,] — will be L2-normalized
            k:               Number of neighbours to return
            exclude_ids:     Pattern IDs to exclude (e.g. the query pattern itself)

        Returns:
            List of (pattern_id, cosine_similarity_score) sorted descending.
            Score is in [-1, 1]; 1.0 = identical.
        """
        with self._lock:
            if self._index is None or self._index.ntotal == 0:
                log.warning("[similarity] Index is empty — returning []")
                return []

            # L2-normalize query
            q = query_embedding.astype(np.float32).reshape(1, -1)
            norm = np.linalg.norm(q)
            if norm == 0:
                return []
            q /= norm

            # Fetch more candidates to account for exclusions
            fetch_k = min(k + len(exclude_ids or []) + 10, self._index.ntotal)
            scores, indices = self._index.search(q, fetch_k)

        results = []
        exclude_set = set(exclude_ids or [])
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._ids):
                continue
            pid = self._ids[idx]
            if pid in exclude_set:
                continue
            results.append((pid, float(score)))
            if len(results) >= k:
                break

        return results

    # ── Maintenance ────────────────────────────────────────────────────────────

    def needs_rebuild(self, pattern_db) -> bool:
        """Returns True if enough new patterns have been added to warrant a rebuild."""
        current_count = pattern_db.count()["total"]
        return (current_count - self._n_at_last_build) >= REBUILD_THRESHOLD

    def rebuild_if_needed(self, pattern_db) -> bool:
        """Rebuild index if threshold exceeded. Returns True if rebuilt."""
        if self.needs_rebuild(pattern_db):
            log.info("[similarity] Rebuild triggered (threshold=%d)", REBUILD_THRESHOLD)
            self.build_index(pattern_db)
            return True
        return False

    @property
    def size(self) -> int:
        """Number of vectors in the current index."""
        with self._lock:
            return self._index.ntotal if self._index else 0


# ── Module-level singleton ─────────────────────────────────────────────────────
# Populated at server startup via load_index() or build_index()
_engine: Optional[PatternSimilarityEngine] = None


def get_engine() -> PatternSimilarityEngine:
    global _engine
    if _engine is None:
        _engine = PatternSimilarityEngine()
    return _engine
