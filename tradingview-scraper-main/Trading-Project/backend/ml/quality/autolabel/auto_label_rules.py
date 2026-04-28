import numpy as np

def rule_based_label(features_dict):
    """
    Primary rule-based engine for consolidation quality.
    Input: dict of 23 features.
    Output: (label, confidence)
    """
    score = 0.0
    
    # 1. Structural Strength (Weight: 40%)
    # behavior_score is rejection_rate * boundary_time_ratio * movement_efficiency
    bs = features_dict.get("behavior_score", 0.0)
    score += min(bs * 2.0, 0.4) 
    
    # 2. Boundary Integrity (Weight: 30%)
    wr = features_dict.get("wick_ratio", 0.0)
    rs = features_dict.get("respect_score", 0.0)
    if rs > 0.9 and wr > 1.5:
        score += 0.3
    elif rs > 0.8:
        score += 0.15
        
    # 3. Efficiency (Weight: 20%)
    me = features_dict.get("movement_efficiency", 0.0)
    if me > 0.8:
        score += 0.2
    elif me > 0.5:
        score += 0.1
        
    # 4. Penalty (Negative Weight)
    sp = features_dict.get("structure_penalty", 0.0)
    score -= sp * 0.3
    
    # Decision
    if score >= 0.65:
        return "GOOD", min(score, 1.0)
    elif score <= 0.35:
        return "BAD", 1.0 - max(score, 0.0)
    else:
        return "UNCERTAIN", 0.5
