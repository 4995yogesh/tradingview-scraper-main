# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['launcher_exe.py'],
    pathex=[],
    binaries=[],
    datas=[('Trading-Project\\backend', 'backend'), ('Trading-Project\\pipeline', 'pipeline'), ('Trading-Project\\project', 'project'), ('Trading-Project\\frontend\\build', 'frontend_build'), ('tradingview_scraper', 'tradingview_scraper')],
    hiddenimports=['uvicorn', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on', 'fastapi', 'fastapi.middleware.cors', 'starlette', 'lightgbm', 'pandas', 'numpy', 'dotenv', 'websockets', 'multiprocessing'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TradingDashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='TradingDashboard',
)
