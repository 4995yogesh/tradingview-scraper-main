"""
Google TimesFM 2.5 predictor using the official PyTorch backend.

Model checkpoint: google/timesfm-2.5-200m-pytorch (HuggingFace)
  ~200M parameters, no JAX required, CPU-compatible on Windows.

PUBLIC INTERFACE (unchanged):
  TimesFMPredictor.forecast_close_prices(candles) -> np.ndarray[horizon_len]
"""
import numpy as np
import torch
from timesfm import TimesFM_2p5_200M_torch, ForecastConfig


class SafeTimesFM(TimesFM_2p5_200M_torch):
    """
    Subclass of TimesFM_2p5_200M_torch that accepts and ignores extra keyword arguments.
    This works around a bug in the library's `_from_pretrained` method where modern
    `huggingface_hub` versions forward additional parameters (like `proxies`) to the
    model constructor, which originally did not accept `**kwargs`.
    """
    def __init__(self, torch_compile: bool = True, config: dict | None = None, **kwargs):
        # We explicitly turn off torch_compile by default as it is not needed for inference
        # and can fail/be very slow on Windows without standard compilation setups.
        super().__init__(torch_compile=False, config=config)


class TimesFMPredictor:
    def __init__(
        self,
        context_len: int = 512,
        horizon_len: int = 50,
        model_id: str = "google/timesfm-2.5-200m-pytorch",
    ):
        self.context_len = context_len
        self.horizon_len = horizon_len
        self.model_id = model_id
        self.tfm = None

        try:
            print(f"TimesFMPredictor: Loading '{model_id}' (TimesFM 2.5 PyTorch backend)...")
            self.tfm = SafeTimesFM.from_pretrained(
                self.model_id,
            )
            print("TimesFMPredictor: Compiling model...")
            self.tfm.compile(
                forecast_config=ForecastConfig(
                    max_context=self.context_len,
                    max_horizon=self.horizon_len,
                )
            )
            print("TimesFMPredictor: Google TimesFM 2.5 loaded and compiled successfully.")
        except Exception as e:
            print(f"TimesFMPredictor: Error loading/compiling model: {e}")
            raise e

    def forecast_close_prices(self, candles: list) -> np.ndarray:
        """
        Extracts closing prices from OHLC candles, pads/truncates to context_len,
        and returns a numpy array of point forecasted close prices of
        shape [horizon_len].

        Args:
            candles: list of dicts with at least a 'close' key.

        Returns:
            np.ndarray of shape (horizon_len,) — point forecast.
        """
        if not self.tfm:
            raise RuntimeError("TimesFM model is not initialized.")

        # Extract and truncate/pad close prices
        close_prices = np.array([c["close"] for c in candles], dtype=np.float32)
        if len(close_prices) > self.context_len:
            close_prices = close_prices[-self.context_len:]
        elif len(close_prices) < self.context_len:
            close_prices = np.pad(close_prices, (self.context_len - len(close_prices), 0), 'edge')

        # forecast() expects: (horizon, inputs)
        # point_forecast shape: [batch, horizon_len]
        point_forecast, _ = self.tfm.forecast(
            horizon=self.horizon_len,
            inputs=[close_prices],
        )

        # Return 1-D array of shape [horizon_len]
        return np.array(point_forecast[0], dtype=np.float32)

    def get_embedding(self, candles: list) -> np.ndarray:
        """
        Extracts closing prices, processes them through the TimesFM model,
        and uses a forward hook on the final transformer block to extract
        the pooled representations as a 1280-dim embedding vector.
        The returned array is L2-normalized.
        """
        if not self.tfm or not hasattr(self.tfm, "model"):
            raise RuntimeError("TimesFM model or internal torch module is not initialized.")

        # Extract and truncate/pad close prices
        close_prices = np.array([c["close"] for c in candles], dtype=np.float32)
        if len(close_prices) > self.context_len:
            close_prices = close_prices[-self.context_len:]
        elif len(close_prices) < self.context_len:
            close_prices = np.pad(close_prices, (self.context_len - len(close_prices), 0), 'edge')

        cache = {}
        def hook_fn(module, input, output):
            if isinstance(output, tuple):
                cache["hidden"] = output[0].detach().cpu()
            else:
                cache["hidden"] = output.detach().cpu()

        # Register hook on the final block of stacked_xf
        final_block = self.tfm.model.stacked_xf[-1]
        handle = final_block.register_forward_hook(hook_fn)

        try:
            with torch.no_grad():
                # We call forecast to trigger forward pass
                # horizon=1 is minimal to avoid extra computation
                _, _ = self.tfm.forecast(
                    horizon=1,
                    inputs=[close_prices],
                )
        finally:
            handle.remove()

        if "hidden" not in cache:
            raise RuntimeError("TimeFM embedding hook failed to trigger.")

        # cache["hidden"] shape is [batch=1, n_patches=16, d_model=1280]
        # Mean pool across patches
        pooled = cache["hidden"].mean(dim=1).numpy()[0]  # shape (1280,)

        # L2-normalize the vector
        norm = np.linalg.norm(pooled)
        if norm > 0:
            pooled /= norm

        return pooled

