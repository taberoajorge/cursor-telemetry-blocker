"""Analyze sniff_capture.jsonl and print detailed payloads for cursor.sh PASS requests."""
import json
import sys

with open("sniff_capture.jsonl") as f:
    records = [json.loads(line) for line in f]

print("=== DETAILED PAYLOADS FOR CURSOR.SH PASS REQUESTS ===")
print()

for r in records:
    if r["action"] != "PASS":
        continue
    if "cursor" not in r["host"] and "github" not in r["host"]:
        continue
    # Skip auth/stripe/extensions/updates
    if any(skip in r["path"] for skip in ["auth/", "stripe", "extensions-control", "updates/"]):
        continue

    path_short = r["path"].split("?")[0]
    payload = r.get("payload", [])
    body = r.get("body", "")

    print(f'--- [{r["ts"]}] {r["method"]} {r["host"]}{path_short} ({r["size"]}B) ---')
    if payload:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        print(f"  payload: {text[:3000]}")
    elif body:
        print(f"  body: {body[:2000]}")
    else:
        print("  (empty body)")
    print()
