"""Drive the API's public endpoints to generate realistic telemetry.
Usage: python scripts/synthetic_traffic.py [--base-url http://localhost:8000] [--loops 20]
"""
import argparse
import json
import random
import time
import urllib.request


def get(base: str, path: str) -> int:
    req = urllib.request.Request(base + path, headers={"User-Agent": "synthetic-traffic"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
        return resp.status


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--loops", type=int, default=20)
    args = ap.parse_args()

    with urllib.request.urlopen(args.base_url + "/api/v1/maps", timeout=10) as r:
        maps = json.load(r)
    map_id = maps[0]["id"]
    with urllib.request.urlopen(f"{args.base_url}/api/v1/maps/{map_id}/viewers", timeout=10) as r:
        viewer_ids = [v["id"] for v in json.load(r)]

    paths = ["/api/v1/health", "/api/v1/maps", f"/api/v1/maps/{map_id}/notes"]
    paths += [f"/api/v1/maps/{map_id}/notes?preview_as={v}" for v in viewer_ids]

    for i in range(args.loops):
        p = random.choice(paths)
        status = get(args.base_url, p)
        print(f"[{i+1}/{args.loops}] {status} {p}")
        time.sleep(random.uniform(0.1, 0.6))


if __name__ == "__main__":
    main()
