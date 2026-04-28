def final_decision(rule_label, rule_conf, gemini_output):
    """
    Safe fusion of rules and AI reasoning.
    Gemini does NOT override; it only reinforces.
    """
    structure = gemini_output.get("structure_type", "unclear")
    gemini_conf = gemini_output.get("confidence", 0.0)
    
    # 1. Reinforcement Matrix
    if rule_label == "GOOD" and structure == "balanced":
        return "GOOD", max(rule_conf, gemini_conf), "AGREED"
        
    if rule_label == "BAD" and structure == "drifting":
        return "BAD", max(rule_conf, gemini_conf), "AGREED"
    
    # 2. Conflicting or Weak Signals
    # If Gemini says balanced but rules say bad (or vice-versa), we fail-safe to human.
    return "UNCERTAIN", 0.5, "DISAGREE"
