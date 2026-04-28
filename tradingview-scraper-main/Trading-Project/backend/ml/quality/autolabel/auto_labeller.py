import logging
from .auto_label_rules import rule_based_label
from .gemini_label import gemini_label
from .decision import final_decision
from .storage import save_label

logger = logging.getLogger(__name__)

def auto_label_pipeline(boxes, extractor, gemini_client):
    """
    Main orchestration logic for hybrid auto-labelling.
    Input:
      boxes: list of box metadata (start, end, symbol, etc)
      extractor: quality feature extractor instance
      gemini_client: configured Gemini API client
    """
    results = []
    
    for box in boxes:
        try:
            # 1. Feature Extraction
            features = extractor.extract(box)
            if not features:
                continue
            
            # Convert list to dict if needed for rule-based engine
            if isinstance(features, list):
                from ml.quality.features import FEATURE_NAMES
                features = dict(zip(FEATURE_NAMES, features))
                
            # 2. Rule-Based Label
            rule_label, rule_conf = rule_based_label(features)
            
            # 3. Gemini Structured Reasoning (TRANSLATOR ONLY)
            gemini_out = gemini_label(features, gemini_client)
            
            # 4. Decision Fusion
            final_label, final_conf, status = final_decision(
                rule_label, rule_conf, gemini_out
            )
            
            # 5. Result Assembly
            result = {
                "box_id": box.get("box_id", "unknown"),
                "symbol": box.get("symbol"),
                "timeframe": box.get("timeframe"),
                "start": box.get("start", box.get("timeStart")),
                "end": box.get("end", box.get("timeEnd")),
                "features": features,
                "label": final_label,
                "confidence": final_conf,
                "status": status,
                "source": "RULE+GEMINI",
                "reason": gemini_out.get("interpretation", "")
            }
            
            # 6. Storage & Final Approval Logic
            stored = save_label(result)
            results.append(stored)
            
        except Exception as e:
            logger.error(f"Error processing box {box.get('box_id')}: {str(e)}")
            continue
            
    return results
