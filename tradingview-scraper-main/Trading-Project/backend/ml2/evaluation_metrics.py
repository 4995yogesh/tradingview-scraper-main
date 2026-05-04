import numpy as np

def evaluate_batch(samples: list, threshold: float = 0.5) -> dict:
    """
    Comprehensive Evaluation Module for Consolidation Detection v2.1.
    """
    if not samples:
        return {}

    eps = 1e-8
    n = len(samples)

    # ── Convert to NumPy Arrays ──────────────────────────────────────────────
    p_boxes = np.array([s["pred_box"] for s in samples])  # [N, 4]
    t_boxes = np.array([s["true_box"] for s in samples])  # [N, 4]
    p_scores = np.array([s["pred_score"] for s in samples])
    t_quality = np.array([s["true_quality"] for s in samples])
    is_consol = np.array([s["is_consolidation"] for s in samples])

    p_start, p_end, p_high, p_low = p_boxes.T
    t_start, t_end, t_high, t_low = t_boxes.T

    # ── 1. IoU Calculation ───────────────────────────────────────────────────
    inter_w = np.maximum(0, np.minimum(p_end, t_end) - np.maximum(p_start, t_start))
    inter_h = np.maximum(0, np.minimum(p_high, t_high) - np.maximum(p_low, t_low))
    inter_area = inter_w * inter_h

    p_area = np.maximum(0, p_end - p_start) * np.maximum(0, p_high - p_low)
    t_area = np.maximum(0, t_end - t_start) * np.maximum(0, t_high - t_low)
    union_area = p_area + t_area - inter_area
    
    ious = inter_area / (union_area + eps)
    
    valid_mask = (is_consol == 1)
    neg_mask = (is_consol == 0)
    
    if valid_mask.any():
        mean_iou = np.mean(ious[valid_mask])
        iou_50 = np.mean(ious[valid_mask] > 0.5)
        iou_70 = np.mean(ious[valid_mask] > 0.7)
    else:
        mean_iou, iou_50, iou_70 = 0.0, 0.0, 0.0

    # ── 2. Boundary Error (MAE in Candles) ───────────────────────────────────
    # Since coordinates are normalized (0..1) over 50 candles:
    err_start = np.abs(p_start - t_start) * 50
    err_end   = np.abs(p_end - t_end) * 50
    
    if valid_mask.any():
        m_err_start = np.mean(err_start[valid_mask])
        m_err_end   = np.mean(err_end[valid_mask])
        m_err_candles = (m_err_start + m_err_end) / 2.0
    else:
        m_err_start = m_err_end = m_err_candles = 0.0

    # ── 3. Decision Metrics (FPR/Rejection Accuracy) ─────────────────────────
    pred_class = (p_scores > threshold).astype(int)
    
    tp = np.sum((pred_class == 1) & (is_consol == 1))
    fp = np.sum((pred_class == 1) & (is_consol == 0))
    tn = np.sum((pred_class == 0) & (is_consol == 0))
    fn = np.sum((pred_class == 0) & (is_consol == 1))
    
    precision = tp / (tp + fp + eps)
    recall = tp / (tp + fn + eps)
    f1 = 2 * (precision * recall) / (precision + recall + eps)
    
    fpr = fp / (np.sum(neg_mask) + eps)
    rejection_accuracy = tn / (np.sum(neg_mask) + eps)
    accuracy = (tp + tn) / n

    # ── 4. Quality Score Alignment ───────────────────────────────────────────
    score_mse = np.mean((p_scores - t_quality)**2)

    return {
        "mean_iou": float(mean_iou),
        "iou_at_07": float(iou_70),
        "boundary_mae_candles": float(m_err_candles),
        "false_positive_rate": float(fpr),
        "rejection_accuracy": float(rejection_accuracy),
        "f1_score": float(f1),
        "accuracy": float(accuracy),
        "score_mse": float(score_mse),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn)
    }
