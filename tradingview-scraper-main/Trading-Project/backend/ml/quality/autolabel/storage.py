from ml.quality.db import save_auto_label, get_auto_labels

def save_label(result):
    """
    Append result to storage (SQLite).
    """
    # Auto-approval check (Section 7)
    approved = False
    if result['confidence'] > 0.75 and result['status'] == "AGREED":
        approved = True
        
    save_auto_label(
        box_id=result['box_id'],
        label=result['label'],
        confidence=result['confidence'],
        status=result['status'],
        approved=approved,
        reason=result.get('reason', ''),
        start=result.get('start'),
        end=result.get('end')
    )
    
    result['approved'] = approved
    return result

def get_all_labels():
    """
    Fetch all stored auto-labels.
    """
    return get_auto_labels()
