"""Print flow-ingredient percentiles over 5-minute windows, for tuning flow.RANGES and RULES.

Usage: python scripts/calibrate_flow.py [competition substring, default "World Cup"]
"""

from __future__ import annotations

import sys
from collections import defaultdict

import numpy as np

from footballiq import config
from footballiq.matchday.flow import FlowIndex, scale
from footballiq.replay.timeline import MatchTimeline
from footballiq.store import _event_from_row, default_store
from footballiq.fabric_source import sql_str


def main() -> None:
    config.load_dotenv()
    comp = sys.argv[1] if len(sys.argv) > 1 else "World Cup"
    st = default_store()
    st.match_ids()
    mids = [m for m, match in st._matches.items() if comp in match.competition]
    print(f"{len(mids)} matches for {comp!r}")
    rows = st.lh.query(f"select * from e where match_id in ({', '.join(sql_str(m) for m in mids)})", {"e": "silver_match_event"}).to_pylist()
    by_match = defaultdict(list)
    for r in rows:
        by_match[r["match_id"]].append(_event_from_row(r))
    vals = defaultdict(list)
    patterns = defaultdict(int)
    for mid in mids:
        idx = FlowIndex(MatchTimeline(st._matches[mid], by_match[mid]))
        for t in range(300_000, idx.duration_ms + 1, 30_000):
            r = idx.raw(t)
            for k in ("turnovers", "duels", "transitions", "long_share", "tempo", "bip"):
                vals[k].append(r[k])
            if r["avg_seq"] is not None:
                vals["avg_seq"].append(r["avg_seq"])
            for a in r["pass_acc"]:
                if a is not None:
                    vals["pass_acc"].append(a)
            f3 = sum(r["final_third"])
            vals["tilt"].append((r["final_third"][0] + 0.5) / (f3 + 1))
            patterns[scale(r)["pattern"]] += 1
    for k, v in vals.items():
        a = np.array(v)
        print(f"{k:12} n={len(a):6d}  p10={np.percentile(a, 10):7.3f}  p25={np.percentile(a, 25):7.3f}  p50={np.percentile(a, 50):7.3f}"
              f"  p75={np.percentile(a, 75):7.3f}  p90={np.percentile(a, 90):7.3f}")
    tot = sum(patterns.values())
    print("patterns with current RULES:", {k: f"{100 * v / tot:.0f}%" for k, v in sorted(patterns.items(), key=lambda kv: -kv[1])})


if __name__ == "__main__":
    main()
