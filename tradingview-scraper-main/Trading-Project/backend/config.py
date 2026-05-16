# Global Configuration for ML Pipeline
import hashlib

MODEL_VERSION = "v2.1.0"
SEQUENCE_LENGTH = 100

# Feature Definitions
# 32 from feature_engine_v4 + 3 volume/time + 8 HTF swings = 43
FEATURES = [
    # 32 features from feature_engine_v4
    "ohlc_rel_o", "ohlc_rel_h", "ohlc_rel_l", "ohlc_rel_c",
    "body_size", "c_range", "u_wick", "l_wick", "direction",
    "vol_ratio", "mom_3", "slope",
    "r_high_rel", "r_low_rel", "r_width_norm", "r_stability",
    "overlap", "signed_prox", "impulse", "t_density", "fake",
    "atr_slope", "comp_ratio", "eq_persist", "dir_entropy", "rej_accum",
    "vol_z", "body_exp", "pos_enc", "range_tight",
    "swing_high", "swing_low",
    # 3 added in dataset.py
    "volume_norm", "hour", "day",
    # 8 HTF swings (4 timeframes * 2)
    "htf_60_sh", "htf_60_sl",
    "htf_240_sh", "htf_240_sl",
    "htf_1D_sh", "htf_1D_sl",
    "htf_1W_sh", "htf_1W_sl"
]

FEATURE_COUNT = len(FEATURES)

# Deterministic signature for validation
FEATURE_SIGNATURE = hashlib.md5(",".join(FEATURES).encode()).hexdigest()

def print_diagnostics():
    print("=" * 50)
    print(f"ML SYSTEM DIAGNOSTICS")
    print(f"Version: {MODEL_VERSION}")
    print(f"Sequence Length: {SEQUENCE_LENGTH}")
    print(f"Feature Count: {FEATURE_COUNT}")
    print(f"Signature: {FEATURE_SIGNATURE}")
    print("=" * 50)
