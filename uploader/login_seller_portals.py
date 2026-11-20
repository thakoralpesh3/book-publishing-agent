#!/usr/bin/env python3
"""1-Click Merchant Portal Login Session Initializer.
Opens a visible browser with the persistent agent profile for Amazon KDP or Flipkart.
Sign in once, and session cookies are preserved for 100% headless automated publishing.
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROFILES = {
    "kdp": (Path.home() / ".cache" / "pub_agent_kdp_profile", "https://kdp.amazon.com/en_US/title-setup/paperback/new/details"),
    "amazon": (Path.home() / ".cache" / "pub_agent_kdp_profile", "https://kdp.amazon.com/en_US/title-setup/paperback/new/details"),
    "flipkart": (Path.home() / ".cache" / "pub_agent_flipkart_profile", "https://seller.flipkart.com"),
}

def open_session(platform: str):
    key = platform.lower()
    if key not in PROFILES:
        print(f"Unknown platform '{platform}'. Choose 'kdp' or 'flipkart'.")
        return
    profile_dir, url = PROFILES[key]
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Clear stale SingletonLocks
    for lock in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        try:
            (profile_dir / lock).unlink(missing_ok=True)
        except Exception:
            pass

    print(f"🚀 Opening {platform.upper()} browser session: {url}")
    if key in ["kdp", "amazon"]:
        print("👉 Complete Amazon Sign-In/2FA and password verification.")
        print("👉 Make sure you check 'Keep me signed in' if prompted.")
        print("👉 Once the 'Paperback Details' title setup page loads, close the browser window.")
    else:
        print("👉 Click 'Login' at the top right and sign into your Flipkart Seller account.")
        print("👉 Once your Seller Hub Dashboard loads, close the browser window.")
    print("👉 Session cookies are automatically preserved for background automated publishing.")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded")
            while not page.is_closed():
                page.wait_for_timeout(1000)
        except Exception:
            pass
        finally:
            try:
                context.close()
            except Exception:
                pass
    print(f"✅ {platform.upper()} session successfully saved in {profile_dir}!")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "kdp"
    open_session(target)
