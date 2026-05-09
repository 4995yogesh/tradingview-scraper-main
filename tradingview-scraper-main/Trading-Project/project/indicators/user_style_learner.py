import os
import sqlite3
import json
import datetime
import numpy as np

class UserStyleLearner:
    def __init__(self, db_path=None):
        if db_path is None:
            # Default path relative to project root
            self.db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "rule_evolution.db"))
        else:
            self.db_path = db_path
            
        # Ensure data directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Initialize the database schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Table for storing evolved parameters
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS parameters (
                    name TEXT PRIMARY KEY,
                    value REAL,
                    description TEXT,
                    last_updated TEXT
                )
            ''')
            
            # Table for storing human feedback and deltas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    symbol TEXT,
                    timeframe TEXT,
                    original_box TEXT,
                    user_box TEXT,
                    delta TEXT,
                    status TEXT
                )
            ''')
            
            # Table for tracking learning state and patterns
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS learning_state (
                    pattern_id TEXT PRIMARY KEY,
                    count INTEGER,
                    last_updated TEXT
                )
            ''')
            
            # Insert default parameters if they don't exist
            default_params = [
                ('touch_thresh_pct', 0.05, 'Percentage of range to consider a touch'),
                ('min_touches', 4.0, 'Minimum touches for a TIGHT box'),
                ('tightness_thresh', 0.005, 'Tightness threshold for TIGHT box'),
                ('efficiency_thresh', 0.4, 'Efficiency threshold for DRIFT box'),
                ('bias_thresh', 0.3, 'Bias threshold for DRIFT box'),
                ('wick_inclusion_weight', 1.0, 'Weight given to user wick inclusions')
            ]
            
            for name, val, desc in default_params:
                cursor.execute('''
                    INSERT OR IGNORE INTO parameters (name, value, description, last_updated)
                    VALUES (?, ?, ?, ?)
                ''', (name, val, desc, datetime.datetime.now().isoformat()))
                
            conn.commit()

    def record_feedback(self, symbol, timeframe, original_box, user_box, status):
        """
        Record human feedback.
        
        original_box: dict with {start, end, top, bottom, type, score}
        user_box: dict with {start, end, top, bottom} or None if validated as is
        status: 'validated' or 'edited'
        """
        timestamp = datetime.datetime.now().isoformat()
        
        delta = {}
        if status == 'edited' and user_box and original_box:
            delta = {
                'top_diff': float(user_box['top'] - original_box['top']),
                'bottom_diff': float(user_box['bottom'] - original_box['bottom']),
                'wick_included': float(user_box['top'] - original_box['top']) > 0 or float(original_box['bottom'] - user_box['bottom']) > 0
            }
            
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO feedback (timestamp, symbol, timeframe, original_box, user_box, delta, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                timestamp, 
                symbol, 
                timeframe, 
                json.dumps(original_box), 
                json.dumps(user_box) if user_box else None, 
                json.dumps(delta), 
                status
            ))
            
            # If edited, update learning state for patterns
            if status == 'edited' and delta.get('wick_included'):
                self._update_pattern_count(cursor, 'wick_inclusion')
                
            conn.commit()
            
        # Trigger evolution check
        self._check_and_evolve()

    def _update_pattern_count(self, cursor, pattern_id):
        """Increment count for a specific pattern."""
        cursor.execute('''
            INSERT INTO learning_state (pattern_id, count, last_updated)
            VALUES (?, 1, ?)
            ON CONFLICT(pattern_id) DO UPDATE SET 
                count = count + 1,
                last_updated = ?
        ''', (pattern_id, datetime.datetime.now().isoformat(), datetime.datetime.now().isoformat()))

    def _check_and_evolve(self):
        """Check if patterns meet the threshold (3-5) and evolve rules."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check wick inclusion pattern
            cursor.execute("SELECT count FROM learning_state WHERE pattern_id = 'wick_inclusion'")
            row = cursor.fetchone()
            if row and row[0] >= 3: # Pattern threshold
                print(f"[Learner] Pattern 'wick_inclusion' reached count {row[0]}. Evolving parameters...")
                
                # Fetch current touch threshold
                cursor.execute("SELECT value FROM parameters WHERE name = 'touch_thresh_pct'")
                curr_thresh = cursor.fetchone()[0]
                
                # Evolve: Make touch threshold more lenient to include wicks
                # This is a simple example of evolution
                new_thresh = curr_thresh + 0.01 # Increase by 1%
                
                cursor.execute('''
                    UPDATE parameters 
                    SET value = ?, last_updated = ?
                    WHERE name = 'touch_thresh_pct'
                ''', (new_thresh, datetime.datetime.now().isoformat()))
                
                # Reset counter or reduce it to prevent runaway evolution
                cursor.execute('''
                    UPDATE learning_state 
                    SET count = 0, last_updated = ?
                    WHERE pattern_id = 'wick_inclusion'
                ''', (datetime.datetime.now().isoformat(),))
                
                print(f"[Learner] Updated touch_thresh_pct from {curr_thresh} to {new_thresh}")
                
            conn.commit()

    def get_parameters(self):
        """Retrieve current parameters."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name, value FROM parameters")
            return {name: value for name, value in cursor.fetchall()}

if __name__ == '__main__':
    # Self-test
    learner = UserStyleLearner()
    print("Database initialized.")
    print("Current params:", learner.get_parameters())
    
    # Simulate feedback
    orig = {"start": 10, "end": 20, "top": 100.0, "bottom": 90.0, "type": "LOOSE", "score": 1.0}
    user = {"start": 10, "end": 20, "top": 102.0, "bottom": 90.0} # User included a top wick
    
    learner.record_feedback("BTCUSDT", "1h", orig, user, "edited")
    learner.record_feedback("BTCUSDT", "1h", orig, user, "edited")
    learner.record_feedback("BTCUSDT", "1h", orig, user, "edited") # 3rd time should trigger evolution
    
    print("Post-feedback params:", learner.get_parameters())
