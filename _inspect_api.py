import json, re

SRC = r"c:\Users\Damascus\.cursor\projects\f-Proiecte-lucky-numbers\attachments\97af1e01-83b8-4f29-ab2a-f55b514d291c\VedAstro-API.postman_collection.json"

with open(SRC, encoding="utf-8") as f:
    data = json.load(f)

# ── Easy (MCP) endpoints ──────────────────────────────────────────────────────
print("=== EASY (MCP) endpoints ===")
for item in data["item"][0]["item"]:
    req = item.get("request", {})
    url = req.get("url", {})
    raw = url.get("raw", "") if isinstance(url, dict) else str(url)
    body = req.get("body", {}).get("raw", "")
    print(f"\n  [{item['name']}]")
    print(f"    {req.get('method','?')} {raw[:120]}")
    if body:
        try:
            b = json.loads(body)
            print(f"    Body keys: {list(b.keys())}")
            # Show params sub-keys if present
            for k,v in b.items():
                if isinstance(v, dict):
                    print(f"      {k}: {list(v.keys())}")
                else:
                    print(f"      {k}: {str(v)[:80]}")
        except Exception:
            print(f"    Body: {body[:200]}")

# ── Advanced: find all unique Calculate methods ───────────────────────────────
print("\n\n=== ADVANCED: unique /Calculate/ methods ===")
methods = set()
for item in data["item"][1]["item"]:
    req = item.get("request", {})
    url = req.get("url", {})
    raw = url.get("raw", "") if isinstance(url, dict) else str(url)
    m = re.search(r"/Calculate/([^/]+)", raw)
    if m:
        methods.add(m.group(1))

# Print sorted, highlight the ones we use
used = {"PlanetSignName", "AllPlanetData", "GocharaZodiacSign",
        "HoroscopePredictions", "DasaAtTime", "CurrentTransits"}
for method in sorted(methods):
    tag = " ← WE USE" if method in used else ""
    print(f"  {method}{tag}")

# ── Find sign/planet-related methods ─────────────────────────────────────────
print("\n\n=== Methods containing 'Sign' or 'Gochara' or 'Planet' ===")
for method in sorted(m for m in methods if any(k in m for k in ["Sign","Gochara","Planet","Natal","Lagna","Ascend"])):
    print(f"  {method}")
