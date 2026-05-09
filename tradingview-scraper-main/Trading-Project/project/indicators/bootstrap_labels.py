import sys
import os
import sqlite3
import json

# Add project root and backend to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(project_root)
sys.path.append(os.path.join(project_root, "backend"))

from project.indicators.user_style_learner import UserStyleLearner

def bootstrap():
    print("Starting Bootstrap from Legacy Labels...")
    
    # Paths
    db_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
    training_db_path = os.path.join(db_dir, "training_set.db")
    
    if not os.path.exists(training_db_path):
        print(f"Error: Training database not found at {training_db_path}")
        return
        
    learner = UserStyleLearner()
    
    try:
        with sqlite3.connect(training_db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Query labeled boxes
            cursor.execute("""
                SELECT box_id, symbol, timeframe, original_meta, user_box, status 
                FROM review_queue 
                WHERE status IN ('LABELED', 'ANALYZED')
            """)
            
            rows = cursor.fetchall()
            print(f"Found {len(rows)} legacy labels to process.")
            
            processed = 0
            for r in rows:
                try:
                    # Parse JSON fields
                    orig_meta = json.loads(r["original_meta"]) if r["original_meta"] else None
                    user_box_data = json.loads(r["user_box"]) if r["user_box"] else None
                    
                    if not orig_meta:
                        continue
                        
                    if isinstance(user_box_data, list) and len(user_box_data) > 0:
                        user_box = user_box_data[0]
                    elif isinstance(user_box_data, dict):
                        user_box = user_box_data
                    else:
                        user_box = None
                        
                    original_box = {
                        "start": orig_meta.get("start", 0),
                        "end": orig_meta.get("end", 0),
                        "top": float(orig_meta.get("priceHigh", orig_meta.get("top", 0))),
                        "bottom": float(orig_meta.get("priceLow", orig_meta.get("bottom", 0))),
                        "type": orig_meta.get("type", "LOOSE"),
                        "score": float(orig_meta.get("score", 0.0))
                    }
                    
                    user_box_mapped = None
                    if user_box:
                        user_box_mapped = {
                            "start": user_box.get("start", original_box["start"]),
                            "end": user_box.get("end", original_box["end"]),
                            "top": float(user_box.get("priceHigh", user_box.get("top", original_box["top"]))),
                            "bottom": float(user_box.get("priceLow", user_box.get("bottom", original_box["bottom"])))
                        }
                        
                    status = 'edited' if user_box_mapped else 'validated'
                    
                    learner.record_feedback(
                        symbol=r["symbol"],
                        timeframe=r["timeframe"],
                        original_box=original_box,
                        user_box=user_box_mapped,
                        status=status
                    )
                    processed += 1
                    
                except Exception as e:
                    print(f"Failed to process row {r['box_id']}: {e}")
                    
            print(f"Successfully processed {processed} rows.")
            
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == '__main__':
    bootstrap()
