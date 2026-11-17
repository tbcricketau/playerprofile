"""variations_source.py — which file a series reads its Variations reels from.

An analyst's hand-cut variations are published per series as `data/variations_<key>.json`
(videobuilder/scripts/publish_variations.py). A series can read ANOTHER series' file when the
bowlers and the clips are the same: England's T20I cards carry the reels cut for the ODI series
(Tom, atq 17-11-2026), for the bowlers in both squads. The file is read, never written or copied,
so a later publish to the ODI set reaches both.
"""
import os

READS_FROM = {"england_t20i": "england_odi"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def path(key):
    """The variations file for a series' opp key: its own if it has one, else the one it reads from."""
    own = os.path.join(DATA, f"variations_{key}.json")
    if os.path.exists(own) or key not in READS_FROM:
        return own
    return os.path.join(DATA, f"variations_{READS_FROM[key]}.json")
