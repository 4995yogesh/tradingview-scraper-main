import traceback
try:
    import launcher
    print('Loaded OK')
except Exception as e:
    traceback.print_exc()
