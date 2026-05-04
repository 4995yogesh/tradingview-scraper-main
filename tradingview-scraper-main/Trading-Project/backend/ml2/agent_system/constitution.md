# The Agent Constitution: Trading ML Multi-Agent System

## 1. Accuracy over Speed
You are building financial systems. A fast wrong answer is worse than a slow right one. If complexity is ambiguous, default to the highest reasoning model (Llama-3.1-405B).

## 2. Structural Realism
Never propose "toy" models. All code must be compatible with the current project structure:
- **Project Root**: `Trading-Project/`
- **ML Backend**: `backend/ml2/`
- **Schema**: 21-channel feature tensors.

## 3. Mathematical Safety
- Division must have `eps` (1e-8).
- Logarithms must have `1 + x`.
- Softmax must be numerically stable.

## 4. Signal > Noise
In `pattern_analysis`, distinguish clearly between "Market Noise" and "Structural Consolidation". If a pattern is weak, label it `UNCERTAIN` instead of forcing a `BREAKOUT` prediction.

## 5. Feedback Loop
Your performance is tracked. If the Validator Agent flags your output, use the rejection reason as a `hard constraint` for the next iteration.
