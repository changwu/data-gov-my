# -*- coding: utf-8 -*-
"""Snapshot per-dataset detail metadata from data.gov.my detail pages.

The catalogue registry (fetch_registry.py) carries the download links but not
the research-critical detail fields (frequency, next_update, methodology,
caveat, fields schema, exclude_openapi, preview link, editions). This fetches
each detail page's __NEXT_DATA__ and stores a trimmed copy under
registry/details/<id>.json plus registry/details_index.json.

Usage:  python tools/fetch_details.py [--registry registry/registry.json]
                                      [--out registry/details] [--jobs 6]
                                      [--ids id1,id2] [--refresh]
"""
import argparse, os, sys, json, re, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from concurrent.futures import ThreadPoolExecutor, as_completed

KEEP = ["id", "title", "description", "data_as_of", "last_updated", "next_update",
        "frequency", "data_source", "exclude_openapi", "link_csv", "link_parquet",
        "link_preview", "link_editions", "fields", "methodology", "caveat",
        "publication", "category", "subcategory", "params", "query"]

def fetch_detail(did):
    url = "%s/data-catalogue/%s" % (common.SITE, did)
    html = common.http_get_text(url, timeout=90)
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>', html)
    if not m:
        return did, {"error": "no __NEXT_DATA__ on detail page"}
    pp = json.loads(m.group(1))["props"]["pageProps"]
    meta = pp.get("meta") or {}
    out = {k: pp.get(k) for k in KEEP if k in pp}
    out["agency"] = meta.get("agency")
    out["category"] = pp.get("category") or out.get("category")
    return did, out

def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--registry", default=os.path.join(root, "registry", "registry.json"))
    ap.add_argument("--out", default=os.path.join(root, "registry", "details"))
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--ids", default="")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    rows = common.load_json(args.registry)
    if args.ids:
        want = set(x.strip() for x in args.ids.split(",") if x.strip())
        rows = [r for r in rows if r["id"] in want]
    os.makedirs(args.out, exist_ok=True)
    index_path = os.path.join(args.out, "details_index.json")
    index = common.load_json(index_path) if os.path.exists(index_path) else {}

    todo = []
    for d in rows:
        did = d["id"]
        if not args.refresh and os.path.exists(os.path.join(args.out, did + ".json")):
            continue
        todo.append(did)
    print("detail pages to fetch: %d" % len(todo), flush=True)

    ok, fail = 0, []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = [ex.submit(fetch_detail, did) for did in todo]
        n = 0
        for f in as_completed(futs):
            n += 1
            did, data = f.result()
            if "error" in data:
                fail.append((did, data["error"]))
            else:
                with open(os.path.join(args.out, did + ".json"), "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=1)
                index[did] = {"title": data.get("title"), "agency": data.get("agency"),
                              "frequency": data.get("frequency"),
                              "data_as_of": data.get("data_as_of"),
                              "next_update": data.get("next_update"),
                              "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                ok += 1
            if n % 25 == 0:
                print("  progress %d/%d (ok=%d)" % (n, len(todo), ok), flush=True)
            time.sleep(0.1)
    common.save_json(index_path, index)
    print("done: ok=%d fail=%d" % (ok, len(fail)), flush=True)
    for did, err in fail[:20]:
        print("  FAIL", did, err, flush=True)

if __name__ == "__main__":
    main()
