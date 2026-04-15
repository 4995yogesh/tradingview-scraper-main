"""
cookie_extractor.py — Auto-extract TradingView cookies from the OS browser store.

Tries browsers in this order: Chrome → Edge → Firefox → Brave → Opera
Works on Windows, macOS, Linux — no user interaction required.

Usage:
    from cookie_extractor import get_tv_cookie_string
    cookie_str = get_tv_cookie_string()   # e.g. "sessionid=abc; _tv_uid=xyz"
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_TV_DOMAIN = "tradingview.com"

# Keys that meaningfully extend TV's anonymous history depth
_USEFUL_KEYS = [
    "sessionid",
    "sessionid_sign",
    "_tv_uid",
    "__cflb",
    "tv_ecuid",
    "_ga",
    "_gid",
]


def _extract_via_browser_cookie3() -> Optional[str]:
    """Try each browser via browser_cookie3 and return a cookie string."""
    try:
        import browser_cookie3
    except ImportError:
        logger.warning("[cookie] browser_cookie3 not installed — skipping auto-extract")
        return None

    loaders = [
        ("Chrome",  browser_cookie3.chrome),
        ("Edge",    browser_cookie3.edge),
        ("Firefox", browser_cookie3.firefox),
        ("Brave",   browser_cookie3.brave),
        ("Opera",   browser_cookie3.opera),
        ("Chromium",browser_cookie3.chromium),
    ]

    for browser_name, loader_fn in loaders:
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(loader_fn, domain_name=_TV_DOMAIN)
                try:
                    jar = future.result(timeout=8)
                except concurrent.futures.TimeoutError:
                    logger.debug("[cookie] %s: timed out (cookie DB may be locked)", browser_name)
                    continue
            cookies = {c.name: c.value for c in jar}
            if not cookies:
                continue

            # Build cookie string — all found keys first, then any extras
            parts = []
            for key in _USEFUL_KEYS:
                if key in cookies:
                    parts.append(f"{key}={cookies[key]}")
            # Also include any other TV cookies not in our list
            for k, v in cookies.items():
                if k not in _USEFUL_KEYS:
                    parts.append(f"{k}={v}")

            if parts:
                cookie_str = "; ".join(parts)
                logger.info("[cookie] Extracted %d cookies from %s (%s)",
                            len(parts), browser_name, _TV_DOMAIN)
                return cookie_str

        except Exception as exc:
            logger.debug("[cookie] %s: %s", browser_name, exc)
            continue

    logger.warning("[cookie] No TV cookies found in any browser — using anonymous access")
    return None


def get_tv_cookie_string() -> str:
    """
    Return a cookie header string for TradingView WebSocket requests.

    Priority:
      1. TRADINGVIEW_COOKIE env var (manual override)
      2. Auto-extracted from OS browser store
      3. Empty string (anonymous access, ~5000 bar limit)
    """
    import os

    # 1. Manual override always wins
    env_cookie = os.getenv("TRADINGVIEW_COOKIE", "").strip()
    if env_cookie:
        logger.info("[cookie] Using TRADINGVIEW_COOKIE env var")
        return env_cookie

    # 2. Auto-extract
    extracted = _extract_via_browser_cookie3()
    if extracted:
        return extracted

    # 3. Fallback
    return ""
