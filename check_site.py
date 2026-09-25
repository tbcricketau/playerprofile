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
# The clips sidecar a page fetches by script (cricket_core.video): no href points at it, so
# nothing else in this file would notice it missing.
_CLIP_SRC = re.compile(r'const (?:VM_SRC|PL_SRC) = "([^"]+)"')
# The query string is INSIDE the group. It used to sit outside, so --deep HEADed every Fairplay
# clip with its SAS stripped off — which storage refuses whether the token is fresh or expired. The
# check meant to catch an expired SAS could therefore never pass a Fairplay bundle at all, and it
# refused the Zimbabwe packs on 2026-09-11 with a token that served 200 when probed directly.
_EXTERNAL = re.compile(r'"(https://[^"]+?\.(?:mp4|MP4|png|jpg|jpeg)(?:\?[^"]*)?)"')
_SKIP = ("http://", "https://", "data:", "#", "mailto:", "javascript:")


def _pages(root):
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in files:
            if f.endswith(".html"):
                yield os.path.join(dirpath, f)


def _sidecar_keys(html, base, cache):
    """The playlist keys a page can open from its clips sidecar, or None if it has no sidecar
    (the clips are inline, and the caller falls back to searching the page text)."""
    m = _CLIP_SRC.search(html)
    if not m:
        return None
    path = os.path.normpath(os.path.join(base, urllib.parse.unquote(m.group(1))))
    if path not in cache:
        try:
            cache[path] = set(json.load(open(path, encoding="utf-8")))
        except Exception:
            cache[path] = set()          # missing/unreadable is reported by rule 3, not here
    return cache[path]


def check(root, deep=False, sample=6):
    errors, warnings = [], []
    _side_cache = {}
    sidecars = set()          # clips files the pages name — where the media urls now live
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
            # 2 — a #fragment must exist in the page it points at. A play-button fragment names a
            #     playlist, which since 24-09-2026 lives in the page's clips sidecar rather than in
            #     its text — so ask the sidecar where there is one.
            if frag and tgt.endswith(".html"):
                tgt_html = open(tgt, encoding="utf-8", errors="replace").read()
                side_keys = _sidecar_keys(tgt_html, os.path.dirname(tgt), _side_cache)
                if side_keys is not None:
                    if frag not in side_keys and f'id="{frag}"' not in tgt_html:
                        errors.append(f"{rel_page}: link -> {raw} but '{frag}' is in neither that "
                                      f"page nor its clips file")
                elif f'"{frag}"' not in tgt_html and f'id="{frag}"' not in tgt_html:
                    errors.append(f"{rel_page}: link -> {raw} but '{frag}' is not in that page")

        # 3 — a play button must have a playlist behind it, and it must not be empty.
        #     The clips live either inline or in a sidecar the page fetches by script — and a
        #     script-fetched file is invisible to rule 1, so a missing one would be a page full of
        #     dead buttons that nothing else here would notice.
        keys = set(_DATAPL.findall(html))
        m_src = _CLIP_SRC.search(html)
        if m_src:
            side = os.path.normpath(os.path.join(base, urllib.parse.unquote(m_src.group(1))))
            if not os.path.exists(side):
                errors.append(f"{rel_page}: clips file missing -> {m_src.group(1)} "
                              f"({len(keys)} play button(s) dead)")
            else:
                linked_files.add(side)
                sidecars.add(side)
                try:
                    data = json.load(open(side, encoding="utf-8"))
                except Exception as exc:
                    errors.append(f"{rel_page}: clips file unreadable -> {m_src.group(1)} "
                                  f"({type(exc).__name__})")
                    data = None
                if data is not None:
                    for key in sorted(keys):
                        if key not in data:
                            errors.append(f"{rel_page}: play button '{key}' is not in {m_src.group(1)}")
                        elif not (data[key] or {}).get("items"):
                            errors.append(f"{rel_page}: play button '{key}' opens an EMPTY playlist")
        else:
            for key in keys:
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
        # The clips sidecars are where the video urls live since 24-09-2026. Reading the pages
        # alone still finds the field images, so --deep would report "checked 6 urls" and prove
        # nothing about the footage — which is the one thing this rule exists for.
        # Sampled per (source kind, host, extension), not off one flat list. A flat list stops on
        # whichever urls come first, and the field images and the clips are on the SAME blob host —
        # so a page-ordered sample could spend its whole budget on .png and report the footage
        # clean without having asked for a single clip.
        groups = {}
        for kind, files in (("page", pages), ("clips", sorted(sidecars))):
            for p in files:
                for u in _EXTERNAL.findall(open(p, encoding="utf-8", errors="replace").read()):
                    ext = u.split("?", 1)[0].rsplit(".", 1)[-1].lower()
                    groups.setdefault((kind, urllib.parse.urlparse(u).netloc, ext), []).append(u)
        urls, seen = [], set()
        for key in sorted(groups):
            urls += groups[key][:sample]
            seen.add(key[1])
        checked = 0
        for u in urls:
            checked += 1
            try:
                req = urllib.request.Request(u, method="HEAD")
                with urllib.request.urlopen(req, timeout=25) as r:
                    if r.status != 200:
                        errors.append(f"media {r.status}: {u.split('?', 1)[0][:110]}")
            except Exception as e:
                # The url now carries its token — print the path only, and the status, which is
                # what tells an expired SAS (403) from a missing clip (404).
                code = getattr(e, "code", None)
                errors.append(f"media unreachable ({type(e).__name__}{f' {code}' if code else ''}): "
                              f"{u.split('?', 1)[0][:110]}")
        print(f"  checked {checked} external media urls across {len(seen)} host(s), "
              f"{len(groups)} kind(s): "
              + ", ".join(f"{k[0]}/{k[2]} {min(len(v), sample)}/{len(v)}"
                          for k, v in sorted(groups.items())))

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
