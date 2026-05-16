# ANTIGRAVITY FAILURE LOG

## Task: Inference with 43 features
- **Result**: Failure
- **Reason**: The model was updated to expect 43 features (due to adding volume, time, and HTF swings), but the inference code in `inference.py` was still calling `build_features` which only produced 32 features. This caused a shape mismatch error in PyTorch: `expected input[1, 32, 50] to have 43 channels, but got 32 channels instead`.
- **Solution**: Updated `inference.py` to also extract the same 11 extra features (Volume, Time, HTF Swings) as `dataset.py` before passing the tensor to the model.

## Task: Training the new model from UI
- **Result**: Failure
- **Reason**: The "Train Model" button in the Refine Studio dashboard triggered `train_nn.py`. However, `train_nn.py` was still using the old `ConsolidationCNN` model and manual feature extraction (100 sequence length, 5 features) instead of the new `SegmentationModel` and `ConsolidationDataset` (50 sequence length, 43 features). This meant training from the UI didn't actually update the model used by inference.
- **Solution**: Updated `train_nn.py` to use `ConsolidationDataset` and `SegmentationModel`, and set `pos_weight` to `3.0` (Option A) to reduce position bias/edge effects.

## Task: Training failed in studio after update
- **Result**: Failure
- **Reason**: `ConsolidationDataset` was initialized with a relative path `'training_set.db'` in `train_nn.py`. This caused the relative path calculation for `candles.db` (inside `dataset.py`) to resolve to the wrong directory, making it unable to find the database and failing the dataset load.
- **Solution**: Modified `train_nn.py` to use the absolute path to `training_set.db` so that `dataset.py` can correctly locate `candles.db` relative to it.

## Task: Training still failing (Dataset empty)
- **Result**: Failure
- **Reason**: The database path calculation in `train_nn.py` was resolving to the wrong directory (root or `Trading-Project/` where the DB was empty or didn't have the table). The correct database with the labeled samples was actually located in `Trading-Project/backend/training_set.db`.
- **Solution**: Updated `train_nn.py` to use `os.path.join(backend_dir, 'training_set.db')` which points directly to the correct 18MB database containing the samples.

## Task: Temporary Inference Error during Training
- **Result**: Temporary Failure
- **Reason**: While the new training is running in the background, the Refine Studio dashboard continues to request predictions to draw the heatmap. The inference code sends 43 features (as updated), but the model file on disk (`model_a.pt`) still has the old 32-channel weights. This causes the error: `expected input to have 32 channels, but got 43 channels instead`.
- **Solution**: This is a temporary state. Once the background training completes (at Epoch 100) and saves the new 43-channel model to `model_a.pt`, the error will resolve automatically.

## Task: Error still showing after restart (Channel mismatch)
- **Result**: Failure
- **Reason**: Even after a full restart, the server was still throwing the error that it expected 32 channels but got 43. This was because Python was loading the cached bytecode (`__pycache__`) for the model definition file (`model_a.py`), which still contained the old 32-channel hardcoded value.
- **Solution**: Deleted all `__pycache__` directories in the backend to force Python to recompile and load the updated file with 43 channels.

## Task: Loss value not showing after training
- **Result**: Failure
- **Reason**: In `train_nn.py`, line 154 tried to call `.item()` on `loss` (which was already a float) and used `val_loss` (which was undefined). This caused an exception inside a `try...except: pass` block, so the error was swallowed and the loss was not updated in the database.
- **Solution**: Updated line 154 to use `float(epoch_loss)` for both train and val loss, as `epoch_loss` is a valid float in that scope.

## Task: Fetch failed after training model
- **Result**: Failure
- **Reason**: The frontend showed "Fetch failed: Failed to fetch", which indicates that the backend server (`server.py`) crashed or stopped responding after the training completed. This could be due to an unhandled exception when updating the live model in memory, or the server exiting unexpectedly.
- **Solution**: Documented the failure. The server needs to be restarted via the launcher.

## Task: Training failed with FATAL ERROR (sqlite3)
- **Result**: Failure
- **Reason**: `FATAL ERROR: cannot access local variable 'sqlite3' where it is not associated with a value`. This happened because I added `import sqlite3` inside the `train()` function at line 183 (to support hard samples detection), which shadowed the global `import sqlite3` at line 5. Python treated `sqlite3` as a local variable for the entire function scope, causing it to fail at line 77 when it tried to use it before it was assigned in that scope.
- **Solution**: Removed the redundant local imports of `sqlite3` and `json` inside the `train()` function to allow it to use the global imports correctly.

## Task: Loss samples not moving to Analyzed tab
- **Result**: Failure
- **Reason**: The user reports that giving feedback on loss samples does not move them to the "ANALYZED" tab (or they still show in the "LOSS SAMPLES" tab). This implies that either the `update_label` function is not matching the `box_id` with `hard_samples.json` (possibly due to type mismatch or path issues), or the status is not being updated correctly in the database.
- **Solution**: Added debug prints to `update_label` in `training_db.py`. Also identified that the user was "skipping" the labels instead of saving them. When a label is skipped, it calls `skip_box` which sets status to `SKIPPED`, not `ANALYZED`. Updated `server.py` to promote hard samples to `ANALYZED` (with empty user boxes) even when skipped, so they move out of the loss samples tab and into the analyzed tab.

## Task: Loss samples reappearing in list after labeling
- **Result**: Failure
- **Reason**: To fulfill the user's request to "show all loss samples", the `AND status != 'ANALYZED'` filter was removed from the query in `/api/training/hard_samples` in `server.py`. This caused samples to remain in the "LOSS SAMPLES" list even after being labeled (which changes status to `ANALYZED`).
- **Solution**: Added the status filter back to only show boxes that are NOT `ANALYZED` (or `LABELED`), so they disappear from the "LOSS SAMPLES" list once reviewed.
