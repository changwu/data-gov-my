# -*- coding: utf-8 -*-
"""Fetch the data.gov.my data catalogue registry (all dataset ids/metadata).

Usage:  python tools/fetch_registry.py [--out registry/registry.json]
Prints a diff summary when a previous registry exists.
"""
import argparse, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--out", default=os.path.join(root, "registry", "registry.json"))
    args = ap.parse_args()

    print("[1/2] fetching catalogue page ...", flush=True)
    rows = common.fetch_registry()
    print("[2/2] parsed %d datasets" % len(rows), flush=True)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    prev = None
    if os.path.exists(args.out):
        prev = {d["id"]: d for d in common.load_json(args.out)}
    cur = {d["id"]: d for d in rows}
    if prev:
        added = sorted(set(cur) - set(prev))
        removed = sorted(set(prev) - set(cur))
        changed = sorted(i for i in cur if i in prev and prev[i].get("data_as_of") != cur[i].get("data_as_of"))
        print("diff vs previous: +%d new, -%d gone, %d with changed data_as_of" % (len(added), len(removed), len(changed)))
        if added: print("  new:", ", ".join(added))
        if removed: print("  gone:", ", ".join(removed))
        if changed: print("  data_as_of changed:", ", ".join(changed))
    common.save_json(args.out, rows)
    csv_path = os.path.splitext(args.out)[0] + ".csv"
    common.write_registry_csv(csv_path, rows)
    cats = {}
    for d in rows: cats[d["category"]] = cats.get(d["category"], 0) + 1
    print("categories: " + ", ".join("%s=%d" % kv for kv in sorted(cats.items())))
    print("saved:", args.out, "and", csv_path)

if __name__ == "__main__":
    main()
