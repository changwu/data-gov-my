# -*- coding: utf-8 -*-
"""Monitor data.gov.my for changes (run daily via cron / Task Scheduler).

Three cheap layers:
  1. registry refresh : new / removed datasets, changed data_as_of
     (one page fetch from data.gov.my; no rate limit)
  2. HEAD sweep       : ETag/size change of every CSV/Parquet on the S3 hosts
     (no rate limit; detects data updates without re-downloading)
  3. API delta pull   : optional, for API-served datasets (4 req/min - see README)

Usage:
  python tools/monitor.py --refresh-registry --head [--registry ...] [--out data]
                          [--webhook https://...] [--download]
"""
import argparse, os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common

def head_report(rows, manifest_path, jobs=8):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    manifest = common.load_json(manifest_path) if os.path.exists(manifest_path) else {}
    checks = []
    for d in rows:
        did = d["id"]
        entry = manifest.get(did, {})
        for kind, key in (("csv", "link_csv"), ("parquet", "link_parquet")):
            url = d.get(key)
            if url:
                checks.append((did, kind, url, entry.get(kind) or {}))
    changed, missing, api_only = [], [], []
    def check(item):
        did, kind, url, prev = item
        h = common.http_head(url)
        status = h and h.get("_status")
        if status == 200:
            etag = (h.get("etag") or "").strip('"')
            cl = h.get("content-length")
            size = int(cl) if cl else None
            if prev.get("unavailable"):
                return ("changed", (did, kind, "was-404", "now-200"))
            if not prev.get("path"):
                return ("missing", (did, kind))
            prev_etag = (prev.get("etag") or "").strip('"')
            prev_bytes = prev.get("bytes")
            etag_same = bool(prev_etag) and bool(etag) and prev_etag == etag
            size_same = size is None or prev_bytes in (None, size)
            if not (etag_same or size_same):
                return ("changed", (did, kind, prev_bytes, size))
            if prev_etag and etag and not etag_same:
                return ("changed", (did, kind, prev_etag, etag))
            return ("same", None)
        if status == 404:
            return ("404", (did, kind))
        return ("same", None)
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futs = [ex.submit(check, c) for c in checks]
        done_n = 0
        for f in as_completed(futs):
            done_n += 1
            if done_n % 100 == 0:
                print("  head sweep %d/%d" % (done_n, len(checks)), flush=True)
            kind_, payload = f.result()
            if kind_ == "changed": changed.append(payload)
            elif kind_ == "missing": missing.append(payload)
            elif kind_ == "404": api_only.append(payload)
    return changed, missing, sorted(set(api_only))
def main():
    ap = argparse.ArgumentParser()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--registry", default=os.path.join(root, "registry", "registry.json"))
    ap.add_argument("--out", default=os.path.join(root, "data"))
    ap.add_argument("--refresh-registry", action="store_true")
    ap.add_argument("--head", action="store_true")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--webhook", default="")
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()

    report = {"ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    rows = None
    if args.refresh_registry:
        print("fetching registry ...", flush=True)
        rows = common.fetch_registry()
        old = {}
        if os.path.exists(args.registry):
            old = {d["id"]: d for d in common.load_json(args.registry)}
        cur = {d["id"]: d for d in rows}
        report["new_datasets"] = sorted(set(cur) - set(old))
        report["removed_datasets"] = sorted(set(old) - set(cur))
        report["data_as_of_changed"] = sorted(i for i in cur if i in old and old[i].get("data_as_of") != cur[i].get("data_as_of"))
        report["total_datasets"] = len(cur)
        common.save_json(args.registry, rows)
        print("registry: %d datasets; new=%d removed=%d data_as_of_changed=%d" % (
            len(cur), len(report["new_datasets"]), len(report["removed_datasets"]),
            len(report["data_as_of_changed"])), flush=True)

    if args.head:
        if rows is None:
            rows = common.load_json(args.registry)
        print("HEAD sweep ...", flush=True)
        changed, missing, api_only = head_report(rows, os.path.join(args.out, "manifest.json"), jobs=args.jobs)
        report["files_changed"] = ["%s/%s %s->%s" % c for c in changed]
        report["files_not_yet_downloaded"] = ["%s/%s" % m for m in missing]
        report["files_404_api_likely"] = ["%s/%s" % m for m in api_only]
        print("files changed=%d missing=%d api-404=%d" % (len(changed), len(missing), len(api_only)), flush=True)

    keys = ("new_datasets", "removed_datasets", "data_as_of_changed", "files_changed")
    changed_any = any(report.get(k) for k in keys)
    print("summary:", "CHANGES FOUND" if changed_any else "no changes")
    if changed_any:
        print(json.dumps({k: v for k, v in report.items() if v}, ensure_ascii=False, indent=1))
        if args.download:
            dl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "download.py")
            os.system(sys.executable + ' "%s" --registry "%s" --out "%s"' % (dl, args.registry, args.out))
    if args.webhook and changed_any:
        import urllib.request
        req = urllib.request.Request(args.webhook, data=json.dumps(report).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=20)
            print("webhook notified")
        except Exception as e:
            print("webhook failed:", e)

if __name__ == "__main__":
    main()