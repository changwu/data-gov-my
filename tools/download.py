# -*- coding: utf-8 -*-
"""Download every dataset's CSV/Parquet from the S3 file hosts (resumable).

Usage:
  python tools/download.py [--registry registry/registry.json] [--out data] [--jobs 8]
                           [--ids id1,id2] [--csv-only|--parquet-only] [--force] [--limit N]
Behaviour:
  * Cheap HEAD per file (ETag + content-length); skip if ETag matches manifest.
  * Download with Range resume; verify size and, when the ETag is a plain MD5, the MD5.
  * Files that 404 are recorded as unavailable (served via the API instead - see README).
"""
import argparse, os, sys, time, hashlib, json, threading, queue
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

def plain_md5_matches(path, md5hex):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().lower() == md5hex.lower()

def download_one(url, dest, expected_size, expected_md5, force=False):
    """Returns (status, detail); status in ok|up-to-date|size-mismatch|md5-mismatch|error."""
    if os.path.exists(dest) and not force:
        cur = os.path.getsize(dest)
        if expected_size is not None and cur == expected_size:
            if expected_md5 is None or plain_md5_matches(dest, expected_md5):
                return ("up-to-date", "already present")
    tmp = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    start = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    try:
        headers = {"Range": "bytes=%d-" % start} if start else {}
        req = urllib.request.Request(url, headers={"User-Agent": common.UA, **headers})
        try:
            with common.OPENER.open(req, timeout=120) as r:
                mode = "ab" if (r.status == 206) else "wb"
                with open(tmp, mode) as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
        except urllib.error.HTTPError as e:
            if e.code == 416 and start > 0:
                # resume start already at EOF -> the .part file is complete
                pass
            else:
                raise
        size = os.path.getsize(tmp)
        if expected_size is not None and size != expected_size:
            return ("size-mismatch", "have %d want %d" % (size, expected_size))
        if expected_md5 is not None and not plain_md5_matches(tmp, expected_md5):
            return ("md5-mismatch", "md5 mismatch")
        os.replace(tmp, dest)
        return ("ok", "downloaded %d bytes" % size)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ("404", "not on S3 (API-served?)")
        return ("error", "http %s" % e.code)
    except Exception as e:
        return ("error", str(e))

def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--registry", default=os.path.join(root, "registry", "registry.json"))
    ap.add_argument("--out", default=os.path.join(root, "data"))
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--ids", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--csv-only", action="store_true")
    ap.add_argument("--parquet-only", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    rows = common.load_json(args.registry)
    if args.ids:
        want = set(x.strip() for x in args.ids.split(",") if x.strip())
        rows = [r for r in rows if r["id"] in want]
    if args.limit:
        rows = rows[: args.limit]
    print("datasets to process: %d" % len(rows), flush=True)

    manifest_path = os.path.join(args.out, "manifest.json")
    manifest = common.load_json(manifest_path) if os.path.exists(manifest_path) else {}
    os.makedirs(args.out, exist_ok=True)

    only_csv = args.csv_only and not args.parquet_only
    only_pq = args.parquet_only and not args.csv_only
    tasks = []
    for d in rows:
        did = d["id"]
        for kind, key, ext in (("csv", "link_csv", "csv"), ("parquet", "link_parquet", "parquet")):
            if only_csv and kind != "csv":
                continue
            if only_pq and kind != "parquet":
                continue
            url = d.get(key)
            if not url:
                continue
            dest = os.path.join(args.out, did, did + "." + ext)
            tasks.append((did, kind, url, dest, d.get(kind + "_bytes"), (d.get(kind + "_etag") or "").strip('"')))

    stats = {"ok": 0, "up-to-date": 0, "404": 0, "error": 0, "size-mismatch": 0, "md5-mismatch": 0}
    q = queue.Queue()
    for t in tasks:
        q.put(t)
    lock = threading.Lock()
    done = [0]

    def worker():
        while True:
            try:
                t = q.get_nowait()
            except queue.Empty:
                return
            did, kind, url, dest, size, etag = t
            md5 = common.plain_md5_etag(etag)
            try:
                st = download_one(url, dest, size, md5, force=args.force)
            except Exception as e:
                st = ("error", "exception: %s" % e)
            with lock:
                done[0] += 1
                if done[0] % 25 == 0 or done[0] == len(tasks):
                    print("  progress %d/%d" % (done[0], len(tasks)), flush=True)
                code = st[0]
                if code == "ok":
                    stats["ok"] += 1
                    manifest.setdefault(did, {})[kind] = {
                        "url": url, "bytes": size, "etag": etag, "path": dest,
                        "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                elif code == "up-to-date":
                    stats["up-to-date"] += 1
                elif code == "404":
                    stats["404"] += 1
                    manifest.setdefault(did, {}).setdefault(kind, {})["unavailable"] = True
                else:
                    stats[code] = stats.get(code, 0) + 1
                if code not in ("ok", "up-to-date"):
                    print("  %s/%s -> %s: %s" % (did, kind, code, st[1]), flush=True)
            q.task_done()

    threads = [threading.Thread(target=worker) for _ in range(max(1, args.jobs))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    common.save_json(manifest_path, manifest)
    print("done:", json.dumps(stats))

if __name__ == "__main__":
    main()
