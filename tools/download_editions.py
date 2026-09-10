# -*- coding: utf-8 -*-
"""Download edition + rolling archives for date-template datasets (S3 hosts).

data.gov.my registry rows for "rolling" datasets carry *template* URLs, e.g.
  https://storage.data.gov.my/transportation/ktmb/komuter_YYYY-MM-DD.csv
The site stores one archive per edition (label from `link_editions`, e.g. a year
or year-month) by substituting the edition label into the template, plus a live
rolling file whose date part tracks the snapshot date. These datasets are also
`exclude_openapi: true`, so the Open API will never serve them.

Usage:
  python tools/download_editions.py [--registry registry/registry.json] [--out data]
                                    [--jobs 8] [--ids id1,id2] [--force]
                                    [--rolling-window 5]
Behaviour:
  * editions: HEAD every <template-with-edition> URL, download 200s with resume +
    size/MD5 verification (reuses tools/download.py helpers).
  * rolling:  for datasets whose template still 404s at edition URLs or whose
    editions don't cover the newest date, HEAD the last --rolling-window days up
    to the registry data_as_of date and download the newest existing file.
  * writes data/editions_manifest.json keyed by dataset id.
"""
import argparse, os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import download as dl
from concurrent.futures import ThreadPoolExecutor, as_completed

def head(url):
    return common.http_head(url)

def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--registry", default=os.path.join(root, "registry", "registry.json"))
    ap.add_argument("--out", default=os.path.join(root, "data"))
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--ids", default="")
    ap.add_argument("--rolling-window", type=int, default=5,
                    help="days to look back from data_as_of for the live rolling file")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    rows = common.load_json(args.registry)
    if args.ids:
        want = set(x.strip() for x in args.ids.split(",") if x.strip())
        rows = [r for r in rows if r["id"] in want]

    # ---- 1) expand targets ----
    edition_jobs, rolling_jobs = [], []
    for d in rows:
        did = d["id"]
        for kind, key, ext in (("csv", "link_csv", "csv"), ("parquet", "link_parquet", "parquet")):
            url = d.get(key) or ""
            if "YYYY-MM-DD" not in url:
                continue
            editions = d.get("link_editions") or []
            if editions:
                base = url.replace("YYYY-MM-DD", "%s")
                for ed in editions:
                    edition_jobs.append({"did": did, "kind": kind, "tag": ed,
                                         "url": base % ed, "edition": True})
            # rolling: newest date-slice file near data_as_of
            da = (d.get("data_as_of") or "")[:10]
            if re_date_full(da):
                import datetime
                day = datetime.date.fromisoformat(da)
                for back in range(0, max(0, args.rolling_window) + 1):
                    cand = (day - datetime.timedelta(days=back)).isoformat()
                    rolling_jobs.append({"did": did, "kind": kind, "tag": "rolling-" + cand,
                                         "url": url.replace("YYYY-MM-DD", cand), "edition": False})
    print("edition targets: %d ; rolling candidates: %d" % (len(edition_jobs), len(rolling_jobs)), flush=True)

    # ---- 2) HEAD to filter existing ----
    def status_of(job):
        h = head(job["url"])
        return job, h
    existing = []
    with ThreadPoolExecutor(max_workers=max(4, args.jobs)) as ex:
        futs = [ex.submit(status_of, j) for j in edition_jobs + rolling_jobs]
        n = 0
        for f in as_completed(futs):
            n += 1
            job, h = f.result()
            st = h and h.get("_status")
            if st == 200:
                cl = h.get("content-length")
                job["bytes"] = int(cl) if cl else None  # CDN may omit CL on HEAD
                job["etag"] = (h.get("etag") or "").strip('"')
                existing.append(job)
            if n % 100 == 0:
                print("  head %d/%d" % (n, len(edition_jobs) + len(rolling_jobs)), flush=True)

    # rolling: keep only the newest existing candidate per (did, kind)
    newest = {}
    for j in existing:
        if j["edition"]:
            continue
        key = (j["did"], j["kind"])
        if key not in newest or j["tag"] > newest[key]["tag"]:
            newest[key] = j
    targets = [j for j in existing if j["edition"]] + list(newest.values())
    targets.sort(key=lambda j: (j["did"], j["kind"], j["tag"]))
    print("targets to download: %d (editions %d + rolling-newest %d)" % (
        len(targets), sum(1 for j in targets if j["edition"]), sum(1 for j in targets if not j["edition"])), flush=True)

    # ---- 3) download ----
    os.makedirs(args.out, exist_ok=True)
    manifest_path = os.path.join(args.out, "editions_manifest.json")
    manifest = common.load_json(manifest_path) if os.path.exists(manifest_path) else {}
    stats = {"ok": 0, "up-to-date": 0, "404": 0, "error": 0, "size-mismatch": 0, "md5-mismatch": 0}
    lock = threading_lock()
    done = [0]
    def worker(jobs):
        for j in jobs:
            url = j["url"]
            fname = url.rsplit("/", 1)[-1]
            dest = os.path.join(args.out, j["did"], fname)
            md5 = common.plain_md5_etag(j.get("etag"))
            st = dl.download_one(url, dest, j.get("bytes"), md5, force=args.force)
            with lock:
                done[0] += 1
                if done[0] % 25 == 0 or done[0] == len(targets):
                    print("  progress %d/%d" % (done[0], len(targets)), flush=True)
                code = st[0]
                if code == "ok":
                    stats["ok"] += 1
                    real_bytes = os.path.getsize(dest) if os.path.exists(dest) else j.get("bytes")
                    manifest.setdefault(j["did"], {}).setdefault(j["kind"], {})[j["tag"]] = {
                        "url": url, "bytes": real_bytes, "etag": j.get("etag"),
                        "path": dest, "downloaded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                elif code == "up-to-date":
                    stats["up-to-date"] += 1
                    real_bytes = os.path.getsize(dest) if os.path.exists(dest) else j.get("bytes")
                    manifest.setdefault(j["did"], {}).setdefault(j["kind"], {})[j["tag"]] = {
                        "url": url, "bytes": real_bytes, "etag": j.get("etag"),
                        "path": dest, "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                else:
                    stats[code] = stats.get(code, 0) + 1
                if code not in ("ok", "up-to-date"):
                    print("  %s/%s/%s -> %s: %s" % (j["did"], j["kind"], j["tag"], code, st[1]), flush=True)
    # balanced shards for a bounded thread pool
    import threading
    shards = [[] for _ in range(max(1, args.jobs))]
    for i, j in enumerate(targets):
        shards[i % len(shards)].append(j)
    threads = [threading.Thread(target=worker, args=(s,)) for s in shards if s]
    for t in threads: t.start()
    for t in threads: t.join()
    common.save_json(manifest_path, manifest)
    print("done:", json.dumps(stats))

def re_date_full(s):
    import re
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))

def threading_lock():
    import threading
    return threading.Lock()

if __name__ == "__main__":
    main()
