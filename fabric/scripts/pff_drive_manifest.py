"""Build fabric/config/pff_wc2022_manifest.json: the Drive file id of each PFF World Cup 2022 file.

Reads Drive's public embedded folder view (no API key); re-run when the folder changes.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import httpx

ROOT_FOLDER_ID = "1_a_q1e9CXeEPJ3GdCv_3-rNO3gPqacfa"
OUT = Path(__file__).resolve().parents[1] / "config" / "pff_wc2022_manifest.json"
ENTRY = re.compile(
    r'href="https://drive.google.com/(file/d|drive/folders)/([^/"?]+)[^"]*"[^>]*>.*?flip-entry-title">([^<]+)<', re.S)
FOLDERS = {"Metadata": "metadata", "Rosters": "rosters", "Event Data": "events", "Tracking Data": "tracking"}


def ls(client: httpx.Client, folder_id: str) -> list[tuple[str, str, str]]:
    r = client.get("https://drive.google.com/embeddedfolderview", params={"id": folder_id})
    r.raise_for_status()
    return [("folder" if k.startswith("drive") else "file", i, html.unescape(n).strip())
            for k, i, n in ENTRY.findall(r.text)]


def main() -> None:
    games: dict[str, dict[str, str]] = {}
    extra: dict[str, str] = {}
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        root = ls(client, ROOT_FOLDER_ID)
        if not root:
            sys.exit("could not list the Drive folder - is it still shared publicly?")
        for kind, fid, name in root:
            if kind == "file":
                extra[name] = fid
            elif name in FOLDERS:
                key = FOLDERS[name]
                for k2, fid2, name2 in ls(client, fid):
                    m = re.fullmatch(r"(\d+)\.(json|jsonl\.bz2)", name2)
                    if k2 == "file" and m:
                        games.setdefault(m.group(1), {})[key] = fid2
                    elif k2 == "file":
                        extra[f"{name}/{name2}"] = fid2
    manifest = {
        "source": f"https://drive.google.com/drive/folders/{ROOT_FOLDER_ID}",
        "provider": "PFF FC (Gradient Sports) FIFA World Cup 2022: metadata, rosters, event data, tracking (~30 Hz)",
        "download_url_template": "https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t",
        "files": extra,
        "games": dict(sorted(games.items(), key=lambda kv: int(kv[0]))),
    }
    OUT.write_text(json.dumps(manifest, indent=2) + "\n")
    complete = sum(1 for g in games.values() if len(g) == 4)
    print(f"{OUT}: {len(games)} games ({complete} with metadata+rosters+events+tracking), {len(extra)} extra files")


if __name__ == "__main__":
    main()
