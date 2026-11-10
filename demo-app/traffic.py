"""Sends steady traffic to the demo gateway. Usage:
    python demo-app/traffic.py --duration 120 --workers 5 --rps 2
"""

import argparse
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

URL = "http://localhost:8080/api/orders"
results: Counter = Counter()
lock = threading.Lock()


def worker(stop_at: float, rps: float) -> None:
    while time.time() < stop_at:
        try:
            with urllib.request.urlopen(URL, timeout=10) as r:
                key = str(r.status)
        except urllib.error.HTTPError as e:
            key = str(e.code)
        except Exception:
            key = "error"
        with lock:
            results[key] += 1
        time.sleep(1 / rps)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=int, default=60, help="seconds")
    p.add_argument("--workers", type=int, default=5)
    p.add_argument("--rps", type=float, default=2, help="requests/sec per worker")
    args = p.parse_args()

    stop_at = time.time() + args.duration
    threads = [
        threading.Thread(target=worker, args=(stop_at, args.rps))
        for _ in range(args.workers)
    ]
    print(f"Sending ~{args.workers * args.rps:.0f} req/s for {args.duration}s...")
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    print("Done. Results by status:", dict(results))


if __name__ == "__main__":
    main()