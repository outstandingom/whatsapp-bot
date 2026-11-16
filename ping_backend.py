"""
Lightweight 24/7 Keep-Alive Pinger for Render WhatsApp Backend.
Pings https://whatapp-51qf.onrender.com/api/health every 4 minutes.
"""

import time
import urllib.request
import datetime

TARGET_URL = "https://whatapp-51qf.onrender.com/api/health"
INTERVAL_SECONDS = 240  # 4 minutes (well before Render's 15-minute sleep cutoff)


def ping_once():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        req = urllib.request.Request(
            TARGET_URL,
            headers={"User-Agent": "RenderKeepAlivePinger/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            status = response.status
            body = response.read().decode("utf-8")
            print(f"[{now}] [OK {status}] Render is awake: {body}")
            return True
    except Exception as e:
        print(f"[{now}] [WARNING] Ping failed: {e}")
        return False


def main():
    print("=" * 65)
    print("  Render 24/7 Keep-Alive Background Pinger")
    print(f"  Target:   {TARGET_URL}")
    print(f"  Interval: Every {INTERVAL_SECONDS} seconds (4 minutes)")
    print("=" * 65)

    # Initial ping
    ping_once()

    while True:
        time.sleep(INTERVAL_SECONDS)
        ping_once()


if __name__ == "__main__":
    main()
