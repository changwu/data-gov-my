# -*- coding: utf-8 -*-
"""Local integrity verification of the mirror (no network).

Checks every file recorded in data/manifest.json and data/editions_manifest.json:
  * exists on disk, size matches the recorded/registry size
  * MD5 matches when the ETag is a plain MD5
  * Parquet files start with the PAR1 magic bytes

Usage:  python tools/verify.py [--root <data-gov-my dir>] [--registry registry/registry.json]
"""
import argparse, os, sys, json, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

def check_file(path, expect_bytes, expect_md5, is_parquet=False):
    if not os.path.exists(path):
        return "missing"
    size = os.path.getsize(path)
    if expect_bytes is not None and size != expect_bytes:
        return "size have=%d want=%s" % (size, expect_bytes)
    if expect_md5:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest().lower() != expect_md5.lower():
            return "md5 mismatch"
    if is_parquet:
        with open(path, "rb") as f:
            if f.read(4) != b"PAR1":
                return "bad parquet magic"
    return None

def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--root", default=root)
    ap.add_argument("--registry", default=os.path.join(root, "registry", "registry.json"))
    args = ap.parse_args()

    reg_path = args.registry
    reg = common.load_json(reg_path) if os.path.exists(reg_path) else None
    reg_ids = {d["id"]: d for d in reg} if reg else {}

    problems, checked, total_bytes = [], 0, 0
    ok_kinds = {"csv": 0, "parquet": 0}

    def walk(manifest_path, expect_from_registry, is_editions):
        nonlocal checked, total_bytes
        if not os.path.exists(manifest_path):
            print("no manifest:", manifest_path)
            return
        man = common.load_json(manifest_path)
        for did, entry in man.items():
            for kind in ("csv", "parquet"):
                fe = entry.get(kind)
                if isinstance(fe, dict) and fe.get("unavailable"):
                    continue
                if isinstance(fe, dict) and not is_editions:
                    files = {".": fe}
                elif isinstance(fe, dict):
                    files = fe  # editions: {tag: {...}}
                else:
                    continue
                for tag, finfo in (files.items() if is_editions else [(".", fe)]):
                    path = finfo.get("path") or finfo.get("url")
                    if not path:
                        continue
                    local = path if os.path.isabs(path) else os.path.join(args.root, path)
                    expect_b = finfo.get("bytes")
                    if expect_from_registry and reg_ids.get(did):
                        expect_b = reg_ids[did].get(kind + "_bytes") or expect_b
                    expect_md5 = common.plain_md5_etag(finfo.get("etag"))
                    err = check_file(local, expect_b, expect_md5, is_parquet=(kind == "parquet"))
                    checked += 1
                    total_bytes += os.path.getsize(local) if os.path.exists(local) else 0
                    if err:
                        problems.append("%s/%s%s: %s (%s)" % (did, kind, "/" + str(tag) if is_editions else "", err, local))
                    else:
                        ok_kinds[kind] += 1

    walk(os.path.join(args.root, "data", "manifest.json"), expect_from_registry=True, is_editions=False)
    walk(os.path.join(args.root, "data", "editions_manifest.json"), expect_from_registry=False, is_editions=True)

    print("files checked: %d (csv-ok=%d parquet-ok=%d)" % (checked, ok_kinds["csv"], ok_kinds["parquet"]))
    print("total bytes on disk: %.1f MB" % (total_bytes / 1e6))
    print("problems: %d" % len(problems))
    for p in problems[:50]:
        print("  -", p)
    sys.exit(1 if problems else 0)

if __name__ == "__main__":
    main()
