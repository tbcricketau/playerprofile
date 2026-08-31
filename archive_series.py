"""archive_series.py — freeze a finished series into the gated coach portal, and bring it back.

The portal is regenerated from nothing on every refresh: `publish_site.build()` clears its output
directory and re-bakes only what `series.json` lists, then `deploy_github` force-pushes, which
discards the repo's history. So a finished series has exactly two fates — keep paying to rebuild it
forever, or be frozen somewhere the build preserves. This is the second.

    .\\venv\\Scripts\\python.exe archive_series.py freeze bangladesh-home-2026
    .\\venv\\Scripts\\python.exe archive_series.py list
    .\\venv\\Scripts\\python.exe archive_series.py restore bangladesh-home-2026

`freeze` copies the BUILT pages out of `site/<slug>` into `archive/<slug>`, lifts the series entry
out of `series.json` and stores it inside the frozen copy. From then on `publish_site` stages
`archive/` into the portal under `archive/<slug>/` — gated by the same password, off the main index,
and costing nothing to rebuild. `restore` puts the entry back in `series.json`, so the next build
bakes it live again from `reports/`.

**It copies, it never moves.** The original stays in `site/` until the next build clears it, and a
`--force` re-freeze renames the old archive aside rather than deleting it.

## The SAS is why an archive can't simply be left alone

Clip URLs carry a read SAS baked into the HTML, and it lasts ~6.5 days (`DEFAULT_SAS_HOURS`). A
frozen page is therefore a page whose vision dies within the week — the state the live packs were
already in when this was written (their SAS expired 2026-08-27). `restamp_sas()` rewrites the query
string on every blob URL under a directory and touches nothing else: no warehouse, no blob probing,
no re-derivation. `publish_site.build()` runs it over the staged copy each refresh, so archived
footage keeps playing while the pages themselves stay exactly as they were baked.
"""
import argparse
import datetime
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
ARCHIVE = os.path.join(HERE, "archive")
SERIES_JSON = os.path.join(HERE, "series.json")
MANIFEST = ".archive.json"
_BANNER_MARK = "<!--archived-->"

# Any blob URL, up to the quote that ends it, capturing the container. A SAS is percent-encoded, so
# it can never contain a quote, whitespace or a backslash — the class below is a safe terminator.
# Keyed on the CONTAINER ('fairplay' / 'hawkeyeupload') rather than the storage account, so this
# needs no private cricket_core constants to know which token belongs to which URL.
_BLOB_RE = re.compile(r"https://[a-z0-9]+\.blob\.core\.windows\.net/([^/\"'\s<>\\]+)/[^\"'\s<>\\]*")


# ── SAS re-stamp ────────────────────────────────────────────────────────────────
def restamp_sas(root, sas_by_container):
    """Replace the SAS on every blob URL under `root`, leaving the rest of each page untouched.

    `sas_by_container` maps container name -> '?<sas>' (see cricket_core.video.get_fairplay_sas /
    get_hawkeye_sas). A container with no entry is left alone rather than stripped, so a missing
    Hawkeye login degrades to stale Hawkeye links instead of broken ones. Returns (files, urls)."""
    n_files = n_urls = 0

    def _sub(m):
        nonlocal n_urls
        sas = sas_by_container.get(m.group(1))
        if not sas:
            return m.group(0)
        n_urls += 1
        return m.group(0).split("?", 1)[0] + sas

    for dirpath, _dd, files in os.walk(root):
        for f in files:
            if not f.endswith(".html"):
                continue
            p = os.path.join(dirpath, f)
            text = open(p, encoding="utf-8").read()
            new, n = _BLOB_RE.subn(_sub, text)
            if n and new != text:
                open(p, "w", encoding="utf-8").write(new)
                n_files += 1
    return n_files, n_urls


# ── Manifests ───────────────────────────────────────────────────────────────────
def manifests():
    """[{slug, name, subtitle, archived, note, reports, files, bytes}] for every frozen series,
    newest first. A directory without a readable manifest is skipped rather than half-reported."""
    out = []
    if not os.path.isdir(ARCHIVE):
        return out
    for slug in sorted(os.listdir(ARCHIVE)):
        p = os.path.join(ARCHIVE, slug, MANIFEST)
        if not os.path.exists(p):
            continue
        try:
            m = json.load(open(p, encoding="utf-8"))
        except (ValueError, OSError):
            continue
        m.setdefault("slug", slug)
        out.append(m)
    return sorted(out, key=lambda m: m.get("archived", ""), reverse=True)


def _load_series():
    return json.load(open(SERIES_JSON, encoding="utf-8"))


def _save_series(cfg, why):
    """Write series.json, snapshotting the current file first. The snapshot is the undo for a
    freeze that removed the wrong slug — it is not regenerable from anything else on disk."""
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = os.path.join(HERE, f"series.json.bak-{stamp}")
    shutil.copy(SERIES_JSON, bak)
    with open(SERIES_JSON, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"  series.json {why} (previous copy kept at {os.path.basename(bak)})")


def _count(d):
    n = b = 0
    for _r, _dd, files in os.walk(d):
        for f in files:
            n += 1
            b += os.path.getsize(os.path.join(_r, f))
    return n, b


def _stamp_banner(index_path, when, note):
    """Mark the frozen series index so a coach opening it knows what they are looking at. Done once,
    at freeze time, and guarded by a marker so a re-freeze doesn't stack banners."""
    if not os.path.exists(index_path):
        return
    text = open(index_path, encoding="utf-8").read()
    if _BANNER_MARK in text:
        return
    extra = f" {note}" if note else ""
    banner = (f'{_BANNER_MARK}<p class="note">Archived {when} — a frozen copy of this series as it '
              f'stood at the end of it. The pages and numbers do not change; the vision links are '
              f'kept current.{extra}</p>')
    if "</p>" in text:                       # straight after the lead paragraph
        head, sep, tail = text.partition("</p>")
        text = head + sep + banner + tail
    else:
        text = text.replace("<h1>", banner + "<h1>", 1)
    open(index_path, "w", encoding="utf-8").write(text)


# ── Commands ────────────────────────────────────────────────────────────────────
def freeze(slug, note="", force=False):
    src = os.path.join(SITE, slug)
    if not os.path.isdir(src) or not os.path.exists(os.path.join(src, "index.html")):
        raise SystemExit(f"not built: {src}\n"
                         f"freeze copies the BUILT pages — run publish_site.py first.")
    dst = os.path.join(ARCHIVE, slug)
    if os.path.isdir(dst):
        if not force:
            raise SystemExit(f"already archived: {dst}\n"
                             f"Pass --force to replace it (the existing copy is renamed aside).")
        aside = f"{dst}.bak-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        os.rename(dst, aside)
        print(f"  existing archive renamed to {os.path.basename(aside)}")

    cfg = _load_series()
    entry = next((s for s in cfg.get("series", []) if s.get("slug") == slug), None)
    if entry is None:
        print(f"  ! {slug} is not in series.json — freezing the built pages anyway")

    os.makedirs(ARCHIVE, exist_ok=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git"))
    n_files, n_bytes = _count(dst)
    when = datetime.datetime.now().strftime("%d-%m-%Y")

    json.dump({
        "slug": slug,
        "name": (entry or {}).get("name", slug),
        "subtitle": (entry or {}).get("subtitle", ""),
        "archived": datetime.datetime.now().strftime("%Y-%m-%d"),
        "note": note,
        "reports": sum(len(g.get("reports", [])) for g in (entry or {}).get("groups", [])),
        "files": n_files,
        "bytes": n_bytes,
        # The whole series.json entry, so `restore` needs nothing but this file.
        "series_entry": entry,
    }, open(os.path.join(dst, MANIFEST), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    _stamp_banner(os.path.join(dst, "index.html"), when, note)
    print(f"  froze {slug}: {n_files} files, {n_bytes / 1048576:.1f} MB -> archive/{slug}")

    if entry is not None:
        cfg["series"] = [s for s in cfg["series"] if s.get("slug") != slug]
        _save_series(cfg, f"— {slug} removed ({len(cfg['series'])} series still live)")
    print(f"\nNext: rebuild and deploy the portal so the frozen copy is served —\n"
          f"  .\\venv\\Scripts\\python.exe deploy_scouting.py "
          f"--repo https://github.com/tbcricketau/scouting-reports.git")


def restore(slug):
    p = os.path.join(ARCHIVE, slug, MANIFEST)
    if not os.path.exists(p):
        raise SystemExit(f"no archive for {slug} (looked for archive/{slug}/{MANIFEST})")
    m = json.load(open(p, encoding="utf-8"))
    entry = m.get("series_entry")
    if not entry:
        raise SystemExit(f"archive/{slug} has no stored series.json entry — it was frozen from a "
                         f"series that wasn't listed. Re-add it to series.json by hand.")
    cfg = _load_series()
    if any(s.get("slug") == slug for s in cfg.get("series", [])):
        raise SystemExit(f"{slug} is already live in series.json — nothing to restore.")
    cfg.setdefault("series", []).insert(0, entry)
    _save_series(cfg, f"— {slug} restored ({len(cfg['series'])} series live)")
    print(f"  restored {slug} ({m.get('reports', '?')} reports)\n"
          f"\nThe frozen copy in archive/{slug} was left in place — delete it once the rebuilt\n"
          f"series is verified, or leave it as the record of how the series ended.\n"
          f"The reports must still be in reports/ for the build to bake them.")


def _list():
    ms = manifests()
    if not ms:
        print("nothing archived")
        return
    for m in ms:
        d = m.get("archived", "")
        d = f"{d[8:10]}-{d[5:7]}-{d[:4]}" if len(d) == 10 else d
        print(f"  {m['slug']:<28} archived {d}  {m.get('reports', 0):>3} reports  "
              f"{m.get('files', 0):>4} files  {m.get('bytes', 0) / 1048576:>6.1f} MB")
    live = {s.get("slug") for s in _load_series().get("series", [])}
    clash = [m["slug"] for m in ms if m["slug"] in live]
    if clash:
        print(f"\n  ! also live in series.json: {', '.join(clash)} — the build will bake the live "
              f"copy AND stage the frozen one.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze", help="copy a built series into archive/ and drop it from series.json")
    f.add_argument("slug")
    f.add_argument("--note", default="", help="one line shown on the archived series index")
    f.add_argument("--force", action="store_true", help="replace an existing archive (renamed aside)")
    r = sub.add_parser("restore", help="put an archived series back into series.json")
    r.add_argument("slug")
    sub.add_parser("list", help="show what is archived")
    a = ap.parse_args()

    if a.cmd == "freeze":
        freeze(a.slug, a.note, a.force)
    elif a.cmd == "restore":
        restore(a.slug)
    else:
        _list()


if __name__ == "__main__":
    main()
