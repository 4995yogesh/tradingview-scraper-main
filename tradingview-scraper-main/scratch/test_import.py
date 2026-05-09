try:
    import launcher
    print("Import successful")
    # Don't try to run it, just import
except Exception as e:
    import traceback
    print(f"Import failed: {e}")
    traceback.print_exc()
