import numpy as np

def evaluate_batch(samples: list, threshold: float = 0.5) -> dict:
    """
    Comprehensive Evaluation Module for Consolidation Detection.
    
    Input samples format:
    {
      "pred_box": [p_start, p_end, p_high, p_low],
      "true_box": [t_start, t_end, t_high, t_low],
      "pred_score": float (0–1),
      "true_quality": float (0, 0.6, 1),
      "is_consolidation": 0 or 1
    }
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

    # Unpack coordinates: [start, end, high, low]
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
    
    # Filter IoU only for actual consolidations (otherwise IoU is meaningless)
    valid_mask = (is_consol == 1)
    if valid_mask.any():
        mean_iou = np.mean(ious[valid_mask])
        iou_50 = np.mean(ious[valid_mask] > 0.5)
        iou_70 = np.mean(ious[valid_mask] > 0.7)
    else:
        mean_iou, iou_50, iou_70 = 0.0, 0.0, 0.0

    # ── 2. Boundary Error ────────────────────────────────────────────────────
    err_start = np.abs(p_start - t_start)
    err_end   = np.abs(p_end - t_end)
    err_top   = np.abs(p_high - t_high)
    err_bot   = np.abs(p_low - t_low)
    
    # Boundary error only relevant for ground truth consolidations
    if valid_mask.any():
        m_err_start = np.mean(err_start[valid_mask])
        m_err_end   = np.mean(err_end[valid_mask])
        m_err_top   = np.mean(err_top[valid_mask])
        m_err_bot   = np.mean(err_bot[valid_mask])
        m_err_all   = (m_err_start + m_err_end + m_err_top + m_err_bot) / 4.0
    else:
        m_err_start = m_err_end = m_err_top = m_err_bot = m_err_all = 0.0

    # ── 3. Decision Metrics (FPR/FNR/F1) ─────────────────────────────────────
    pred_class = (p_scores > threshold).astype(int)
    
    tp = np.sum((pred_class == 1) & (is_consol == 1))
    fp = np.sum((pred_class == 1) & (is_consol == 0))
    tn = np.sum((pred_class == 0) & (is_consol == 0))
    fn = np.sum((pred_class == 0) & (is_consol == 1))
    
    precision = tp / (tp + fp + eps)
    recall = tp / (tp + fn + eps)
    f1 = 2 * (precision * recall) / (precision + recall + eps)
    
    fpr = fp / (fp + tn + eps)
    fnr = fn / (fn + tp + eps)
    accuracy = (tp + tn) / n

    # ── 4. Quality Score Alignment ───────────────────────────────────────────
    score_mse = np.mean((p_scores - t_quality)**2)
    # Correlation (using numpy.corrcoef)
    if n > 1 and np.std(p_scores) > 0 and np.std(t_quality) > 0:
        score_corr = np.corrcoef(p_scores, t_quality)[0, 1]
    else:
        score_corr = 0.0

    # ── 5. Composite Score ───────────────────────────────────────────────────
    # Normalized boundary error (1.0 = perfect, 0.0 = error >= 1.0 window unit)
    norm_err = np.clip(1.0 - m_err_all, 0, 1)
    
    final_score = (
        0.4 * mean_iou +
        0.2 * norm_err +
        0.2 * f1 +
        0.2 * (1.0 - fpr)
    )

    return {
        "mean_iou": float(mean_iou),
        "iou_50": float(iou_50),
        "iou_70": float(iou_70),
        "boundary_error": {
            "start": float(m_err_start),
            "end": float(m_err_end),
            "top": float(m_err_top),
            "bottom": float(m_err_bot),
            "mean": float(m_err_all)
        },
        "false_positive_rate": float(fpr),
        "false_negative_rate": float(fnr),
        "precision": float(precision),
        "recall": float(recall),
        "f1_score": float(f1),
        "accuracy": float(accuracy),
        "score_mse": float(score_mse),
        "score_correlation": float(score_corr),
        "final_score": float(final_score)
    }

if __name__ == "__main__":
    # ── Synthetic Tests ──────────────────────────────────────────────────────
    test_samples = [
        # 1. Perfect Match
        {
            "pred_box": [10, 20, 100, 90],
            "true_box": [10, 20, 100, 90],
            "pred_score": 0.95,
            "true_quality": 1.0,
            "is_consolidation": 1
        },
        # 2. No Overlap
        {
            "pred_box": [30, 40, 110, 105],
            "true_box": [10, 20, 100, 90],
            "pred_score": 0.8,
            "true_quality": 1.0,
            "is_consolidation": 1
        },
        # 3. False Positive
        {
            "pred_box": [15, 25, 95, 85],
            "true_box": [0, 0, 0, 0],
            "pred_score": 0.7,
            "true_quality": 0.0,
            "is_consolidation": 0
        },
        # 4. Zero Width Box (Edge Case)
        {
            "pred_box": [10, 10, 100, 100],
            "true_box": [10, 20, 100, 90],
            "pred_score": 0.1,
            "true_quality": 1.0,
            "is_consolidation": 1
        }
    ]
    
    results = evaluate_batch(test_samples)
    
    import json
    print(json.dumps(results, indent=2))
    
    # Assertions for sanity
    assert results["mean_iou"] < 1.0, "IoU should be average of perfect and no-overlap"
    assert results["false_positive_rate"] > 0, "Should detect the FP"
    print("\nValidation Successful.")
