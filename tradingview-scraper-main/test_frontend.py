from playwright.sync_api import sync_playwright
import time

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        logs = []
        page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: logs.append(f"[error] {err}"))
        
        print("Navigating to http://localhost:3000/chart...")
        page.goto("http://localhost:3000/chart")
        
        print("Waiting 20 seconds for live ticks and polling...")
        time.sleep(20)
        
        print("\n--- BROWSER CONSOLE LOGS ---")
        for log in logs:
            print(log)
            
        browser.close()

if __name__ == "__main__":
    run()
