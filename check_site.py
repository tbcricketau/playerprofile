"""check_site.py — validate a built bundle BEFORE it is pushed live.

Every problem this catches has actually shipped at least once:
  * a card linking a report that was never baked (relinking without re-injecting)
  * an orphaned page whose breadcrumb pointed at an index that only exists on the coach site
  * a vision button whose playlist was filtered away, leaving a button that opens nothing
  * an expired Fairplay SAS, which breaks every clip silently (--deep)

Run it on the assembled bundle, not the build dir — the bundle is what actually gets served.

    .\\venv\\Scripts\\python.exe check_site.py player_pack_site
    .\\venv\\Scripts\\python.exe check_site.py caxi_player_pack_site --deep

Exit code 0 = safe to push, 1 = something is broken. Pure stdlib, no network unless --deep.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

_LINK = re.compile(r'(?:href|src)="([^"]+)"')
_DATAPL = re.compile(r'data-pl="([^"]+)"')
_EXTERNAL = re.compile(r'"(https://[^"]+?\.(?:mp4|MP4|png|jpg|jpeg))(?:\?[^"]*)?"')
_SKIP = ("http://", "https://", "data:", "#", "mailto:", "javascript:")


def _pages(root):
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in files:
            if f.endswith(".html"):
                yield os.path.join(dirpath, f)


def check(root, deep=False, sample=6):
    errors, warnings = [], []
    pages = list(_pages(root))
    if not pages:
        return [f"no HTML found under {root}"], []
    linked_files, n_links = set(), 0

    for p in pages:
        rel_page = os.path.relpath(p, root)
        html = open(p, encoding="utf-8", errors="replace").read()
        base = os.path.dirname(p)

        # 1 — every internal href/src resolves to a real file
        for raw in _LINK.findall(html):
            if raw.startswith(_SKIP) or not raw.strip():
                continue
            n_links += 1
            frag = raw.split("#", 1)[1] if "#" in raw else ""
            rel = urllib.parse.unquote(raw.split("#")[0].split("?")[0])
            if not rel:
                continue
            tgt = os.path.normpath(os.path.join(base, rel))
            if not os.path.exists(tgt):
                errors.append(f"{rel_page}: dead link -> {raw}")
                continue
            linked_files.add(os.path.normpath(tgt))
            if os.path.isfile(tgt) and os.path.getsize(tgt) == 0:
                errors.append(f"{rel_page}: links an EMPTY file -> {raw}")
            # 2 — a #fragment must exist in the page it points at
            if frag and tgt.endswith(".html"):
                tgt_html = open(tgt, encoding="utf-8", errors="replace").read()
                if f'"{frag}"' not in tgt_html and f'id="{frag}"' not in tgt_html:
                    errors.append(f"{rel_page}: link -> {raw} but '{frag}' is not in that page")

        # 3 — a play button must have a playlist behind it, and it must not be empty
        for key in set(_DATAPL.findall(html)):
            if f'"{key}"' not in html:
                errors.append(f"{rel_page}: play button '{key}' has no playlist on the page")
            elif re.search(rf'"{re.escape(key)}"\s*:\s*\[\s*\]', html):
                errors.append(f"{rel_page}: play button '{key}' opens an EMPTY playlist")

    # 4 — pages nobody links to (an orphan is usually a leftover carrying a stale breadcrumb)
    entry = {os.path.normpath(os.path.join(root, "index.html")),
             os.path.normpath(os.path.join(root, "players", "index.html"))}
    for p in pages:
        if os.path.normpath(p) not in linked_files and os.path.normpath(p) not in entry:
            warnings.append(f"orphan page, nothing links it: {os.path.relpath(p, root)}")

    # 5 — external media actually serves (catches an expired video SAS)
    if deep:
        urls = []
        for p in pages:
            urls += _EXTERNAL.findall(open(p, encoding="utf-8", errors="replace").read())
        seen, checked = set(), 0
        for u in urls:
            host = urllib.parse.urlparse(u).netloc
            if host in seen and checked >= sample:
                continue
            seen.add(host)
            checked += 1
            if checked > sample * max(len(seen), 1):
                break
            try:
                req = urllib.request.Request(u, method="HEAD")
                with urllib.request.urlopen(req, timeout=25) as r:
                    if r.status != 200:
                        errors.append(f"media {r.status}: {u[:110]}")
            except Exception as e:
                errors.append(f"media unreachable ({type(e).__name__}): {u[:110]}")
        print(f"  checked {checked} external media urls across {len(seen)} host(s)")

    print(f"  {len(pages)} pages, {n_links} internal links")
    return errors, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle", help="assembled bundle dir, e.g. player_pack_site")
    ap.add_argument("--deep", action="store_true", help="also HEAD a sample of media urls")
    ap.add_argument("--sample", type=int, default=6, help="media urls to test per host")
    a = ap.parse_args()
    root = a.bundle if os.path.isabs(a.bundle) else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), a.bundle)
    print(f"checking {root}")
    errors, warnings = check(root, deep=a.deep, sample=a.sample)
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  FAIL  {e}")
    if errors:
        print(f"\n{len(errors)} problem(s) — DO NOT PUSH")
        sys.exit(1)
    print(f"\nclean{' (' + str(len(warnings)) + ' warning(s))' if warnings else ''} — safe to push")


if __name__ == "__main__":
    main()
