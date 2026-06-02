"""End-to-end smoke test for Pattern Memory pipeline."""
import sys
sys.path.insert(0, 'ml2')
sys.path.insert(0, 'ml2/pattern_memory')

from pattern_db import PatternMemoryDB
from similarity_engine import PatternSimilarityEngine
from outcome_intelligence import OutcomeIntelligence

db = PatternMemoryDB()
engine = PatternSimilarityEngine()
intel = OutcomeIntelligence()

# Load the FAISS index
ok = engine.load_index()
print('Index loaded:', ok, '| Size:', engine.size)

# Full pipeline test
ids, matrix = db.get_all_embeddings()
query = matrix[0]
results = engine.search(query, k=50, exclude_ids=[ids[0]])
print('FAISS search results:', len(results), 'matches')
print('Top score:', results[0][1] if results else 'N/A')

pids   = [pid for pid, _ in results]
scores = [score for _, score in results]
matches = db.get_patterns_by_ids(pids)
print('Loaded', len(matches), 'PatternRecord objects')

intelligence = intel.compute(matches, scores, horizon=20)
report = intelligence.to_dict()

print()
print('=== Pattern Intelligence Report ===')
for k, v in report.items():
    if k != 'similar_patterns':
        print(f'  {k}: {v}')
sp = report.get('similar_patterns', [])
print(f'  similar_patterns: [{len(sp)} items]')
if sp:
    print('  First similar pattern:', sp[0])
