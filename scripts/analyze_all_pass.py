"""Show ALL PASS+STRIP endpoints on cursor/github with payloads."""
import json
from collections import defaultdict

with open("sniff_capture.jsonl") as f:
    records = [json.loads(line) for line in f]

endpoints = defaultdict(list)

for r in records:
    h = r["host"]
    # Skip localhost, MCPs, npm, gravatar
    if "127.0.0.1" in h or "mcp." in h or "registry.npmjs" in h or "gravatar" in h:
        continue
    if r["action"] not in ("PASS", "STRIP"):
        continue

    tag = f" [{r['action']}]" if r["action"] == "STRIP" else ""
    key = r["path"].split("?")[0]
    endpoints[f"{h}{key}{tag}"].append(r)

for ep in sorted(endpoints.keys()):
    recs = endpoints[ep]
    sizes = [r["size"] for r in recs]
    total_bytes = sum(sizes)
    max_size = max(sizes)

    print("=" * 75)
    print(f"ENDPOINT: {ep}")
    print(f"  Count: {len(recs)}x  |  Total sent: {total_bytes:,}B  |  Max single: {max_size:,}B")

    # Show one representative payload
    shown = False
    for r in recs:
        payload = r.get("payload", [])
        body = r.get("body", "")
        if payload:
            print("  PAYLOAD EXAMPLE:")
            obj = payload[0] if len(payload) == 1 else payload
            text = json.dumps(obj, indent=2, ensure_ascii=False)
            if len(text) > 1500:
                text = text[:1500] + "\n  ... (truncated)"
            for line in text.split("\n"):
                print(f"    {line}")
            shown = True
            break
        elif body:
            print(f"  BODY EXAMPLE: {body[:800]}")
            shown = True
            break

    if not shown:
        print("  PAYLOAD: (empty body - only auth headers sent)")
    print()
