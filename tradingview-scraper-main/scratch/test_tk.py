import tkinter as tk
try:
    root = tk.Tk()
    print("Tkinter initialized successfully")
    root.withdraw() # hide window
    root.after(100, root.destroy)
    root.mainloop()
    print("Tkinter event loop finished")
except Exception as e:
    print(f"Tkinter failed: {e}")
