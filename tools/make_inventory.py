# -*- coding: utf-8 -*-
"""Build DATA_INVENTORY.csv (single source of truth for what the mirror holds).

Columns: dataset_id, title, category, scope(current|edition), kind(csv|parquet),
edition, filename, bytes, md5_or_etag, source_url, local_path, note

Usage:  python tools/make_inventory.py [--root .] [--out DATA_INVENTORY.csv]
"""
import argparse, csv, os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--root", default=root)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out_path = args.out or os.path.join(args.root, "DATA_INVENTORY.csv")

    reg = common.load_json(os.path.join(args.root, "registry", "registry.json"))
    meta = {d["id"]: d for d in reg}
    rows = []

    man_path = os.path.join(args.root, "data", "manifest.json")
    man = common.load_json(man_path) if os.path.exists(man_path) else {}
    for did, entry in sorted(man.items()):
        d = meta.get(did, {})
        for kind in ("csv", "parquet"):
            fe = entry.get(kind) or {}
            if fe.get("unavailable"):
                rows.append([did, d.get("title"), d.get("category"), "current", kind, "",
                             "", "", "", "", "", "unavailable upstream (date-template dataset)"])
                continue
            if not fe:
                continue
            path = fe.get("path", "")
            local = path if os.path.isabs(path) else os.path.join(args.root, path)
            size = os.path.getsize(local) if os.path.exists(local) else fe.get("bytes")
            rows.append([did, d.get("title"), d.get("category"), "current", kind, "",
                         os.path.basename(local), size, fe.get("etag", ""), fe.get("url", ""),
                         os.path.relpath(local, args.root).replace("\\", "/"), ""])

    ed_path = os.path.join(args.root, "data", "editions_manifest.json")
    ed = common.load_json(ed_path) if os.path.exists(ed_path) else {}
    for did, kinds in sorted(ed.items()):
        d = meta.get(did, {})
        for kind, tags in sorted(kinds.items()):
            for tag, fe in sorted(tags.items()):
                path = fe.get("path", "")
                local = path if os.path.isabs(path) else os.path.join(args.root, path)
                size = os.path.getsize(local) if os.path.exists(local) else fe.get("bytes")
                rows.append([did, d.get("title"), d.get("category"), "edition", kind, tag,
                             os.path.basename(local), size, fe.get("etag", ""), fe.get("url", ""),
                             os.path.relpath(local, args.root).replace("\\", "/"), ""])

    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset_id", "title", "category", "scope", "kind", "edition",
                    "filename", "bytes", "md5_or_etag", "source_url", "local_path", "note"])
        w.writerows(rows)
    total = sum(r[7] or 0 for r in rows)
    print("inventory rows: %d, total %.1f MB -> %s" % (len(rows), total / 1e6, out_path))

if __name__ == "__main__":
    main()
