# -*- coding: utf-8 -*-
"""Shared helpers for the data.gov.my mirror tools (stdlib only)."""
import json, re, os, time, hashlib
import urllib.request, urllib.error

UA = "data-gov-my-mirror/0.1 (country-policy research mirror; polite crawler)"
SITE = "https://data.gov.my"
CATALOGUE_PAGE = SITE + "/data-catalogue"

# --- proxy policy ---------------------------------------------------------
# Windows may have a system proxy configured (WinINET registry, e.g. a local
# Clash/v2ray on 127.0.0.1:7890). urllib picks it up automatically, which makes
# every download depend on that local process staying alive; if it dies you get
# confusing SSL errors (WRONG_VERSION_NUMBER / UNEXPECTED_EOF) that look like
# the portal is broken. The S3 hosts are directly reachable, so default to
# DIRECT connections.  Override with DGM_PROXY=system | http://host:port
_PROXY_MODE = os.environ.get("DGM_PROXY", "direct").strip()

def _build_opener():
    if _PROXY_MODE == "system":
        return urllib.request.build_opener()
    if _PROXY_MODE.startswith("http"):
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": _PROXY_MODE, "https": _PROXY_MODE}))
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))

OPENER = _build_opener()

def _open(url, timeout=60, method=None, headers=None, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, **(headers or {})})
            return OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                last = e; time.sleep(2 ** attempt * 2); continue
            raise
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 1.5); continue
            raise
    raise last

def http_get_text(url, timeout=60, headers=None):
    with _open(url, timeout=timeout, headers=headers) as r:
        return r.read().decode("utf-8", errors="replace")

def http_head(url, timeout=30, headers=None):
    """HEAD request -> dict of headers incl '_status', or {'_status': code}."""
    try:
        with _open(url, timeout=timeout, method="HEAD", headers=headers) as r:
            h = dict(r.headers); h["_status"] = r.status
            return h
    except urllib.error.HTTPError as e:
        return {"_status": e.code}
    except Exception:
        return None

def extract_registry(html):
    """Parse the __NEXT_DATA__ JSON embedded in the SSR catalogue page -> list of dataset dicts."""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">([\s\S]*?)</script>', html)
    if not m:
        raise ValueError("__NEXT_DATA__ block not found (page layout changed?)")
    data = json.loads(m.group(1))
    col = data["props"]["pageProps"]["collection"]
    out = []
    for cat, subs in col.items():
        for sub, items in subs.items():
            if not isinstance(items, list):
                continue
            for it in items:
                row = dict(it)
                row["category"] = cat
                row["subcategory"] = sub
                row["data_source"] = row.get("data_source") or []
                out.append(row)
    return out

def fetch_registry():
    return extract_registry(http_get_text(CATALOGUE_PAGE))

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)

def csv_cell(v):
    if v is None: return ""
    s = ";".join(v) if isinstance(v, list) else str(v)
    return '"' + s.replace('"', '""') + '"'

def write_registry_csv(path, rows):
    keys = ["category", "subcategory", "id", "title", "data_as_of", "description",
            "data_source", "link_csv", "link_parquet", "link_editions",
            "csv_bytes", "csv_etag", "csv_last_modified",
            "parquet_bytes", "parquet_etag", "parquet_last_modified"]
    NL = chr(10)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(",".join(keys) + NL)
        for r in rows:
            f.write(",".join(csv_cell(r.get(k)) for k in keys) + NL)
    return keys

def plain_md5_etag(etag):
    etag = (etag or "").strip('"')
    return etag if re.fullmatch(r"[0-9a-fA-F]{32}", etag) else None

