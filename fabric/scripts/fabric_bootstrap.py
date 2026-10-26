"""Deploy and run the FootballIQ Fabric pipeline: check | deploy | run | all | debug <nb> | catalog | realtime.

Items live in one workspace folder and are updated in place; a same-named item outside it stops the script.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

API = "https://api.fabric.microsoft.com/v1"
ONELAKE = "https://onelake.dfs.fabric.microsoft.com"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
STORAGE_SCOPE = "https://storage.azure.com/.default"
REPO = Path(__file__).resolve().parents[2]

FOLDER_NAME = os.environ.get("FABRIC_FOLDER_NAME", "FootballIQ")
LAKEHOUSE_NAME = os.environ.get("FABRIC_LAKEHOUSE_NAME", "lh_football_intelligence")
# pre-created so MLflow logs into the folder, not the workspace root
ML_EXPERIMENT = "exp_footballiq_models"
ML_MODELS = ["fiq_xg", "fiq_xpass", "fiq_goal_10m", "fiq_corner_2m", "fiq_penalty_5m", "fiq_goal_rate"]
NOTEBOOKS = ["nb_statsbomb_ingest", "nb_pff_ingest", "nb_gold_build", "nb_gold_tracking", "nb_gold_possession", "nb_gold_tactical", "nb_ml_train", "nb_ml_score", "nb_ml_xpass_tracking", "nb_idsse_ingest", "nb_skillcorner_ingest", "nb_table_catalog", "nb_debug_runner"]
PIPELINE_NAME = "pl_football_medallion"
FABRIC_DIR = REPO / "fabric"
# local path -> lakehouse Files/ path
CONFIG_FILES = {FABRIC_DIR / "config" / "pff_wc2022_manifest.json": "config/pff_wc2022_manifest.json"}
EXPECTED_TABLES = [
    "silver_match", "silver_match_event", "silver_freeze_frame", "silver_player",
    "silver_pff_match", "silver_pff_roster", "silver_pff_player", "silver_pff_event",
    "silver_tracking_period", "silver_tracking_event",
    "silver_tracking_frame", "silver_player_position",
    "gold_team_metrics_5s", "gold_player_match_metrics", "gold_match_summary", "gold_match_history",
    "gold_player_metrics_1s", "gold_player_physical_match", "gold_team_shape_5s", "gold_tracking_coverage_1m",
    "gold_possession_sample", "gold_possession_benchmark",
    "gold_tactical_window", "gold_passing_network", "gold_heatmap", "gold_regains",
    "ml_model_registry", "gold_model_evaluation", "gold_model_calibration", "gold_event_model_values", "gold_prediction_log",
]


class RetryClient(httpx.Client):
    """httpx client that retries transport errors and renews expired tokens; long jobs outlive the ~1 h token."""

    def __init__(self, *args, token_scope: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.token_scope = token_scope

    def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        for attempt in range(6):
            try:
                resp = super().send(request, **kwargs)
            except httpx.TransportError:
                if attempt == 5:
                    raise
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 401 and self.token_scope and attempt < 5:
                token = get_token(self.token_scope)
                self.headers["Authorization"] = request.headers["Authorization"] = f"Bearer {token}"
                continue
            return resp
        raise AssertionError("unreachable")


def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        sys.exit(f"missing environment variable {name} (see .env.example)")
    return val


def get_token(scope: str) -> str:
    tenant = env("FABRIC_TENANT_ID")
    resp = RetryClient().post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": env("FABRIC_CLIENT_ID"),
            "client_secret": env("FABRIC_CLIENT_SECRET"),
            "scope": scope,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        sys.exit(f"token request failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()["access_token"]


class Fabric:
    def __init__(self, token: str):
        self.http = RetryClient(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=60, token_scope=FABRIC_SCOPE)
        self.ws = ""

    def _check(self, resp: httpx.Response) -> httpx.Response:
        if resp.status_code >= 400:
            sys.exit(f"{resp.request.method} {resp.request.url} -> {resp.status_code}: {resp.text[:500]}")
        return resp

    def _wait(self, resp: httpx.Response) -> dict:
        """Follow Fabric long-running operations (202 + Location)."""
        self._check(resp)
        if resp.status_code != 202:
            return resp.json() if resp.content else {}
        op_url = resp.headers["Location"]
        delay = int(resp.headers.get("Retry-After", "3"))
        for _ in range(200):
            time.sleep(delay)
            op = self._check(self.http.get(op_url))
            status = op.json().get("status")
            if status == "Failed":
                sys.exit(f"operation failed: {op.text[:500]}")
            if status == "Succeeded":
                return op.json()
        sys.exit("timed out waiting for Fabric operation")

    def _paged(self, url: str, params: dict | None = None) -> list[dict]:
        out, token = [], None
        while True:
            p = dict(params or {})
            if token:
                p["continuationToken"] = token
            body = self._check(self.http.get(url, params=p)).json()
            out += body.get("value", body.get("data", []))  # most APIs use "value"; lakehouse tables use "data"
            token = body.get("continuationToken")
            if not token:
                return out

    def resolve_workspace(self) -> dict:
        wid = os.environ.get("FABRIC_WORKSPACE_ID")
        name = os.environ.get("FABRIC_WORKSPACE_NAME")
        workspaces = self._paged("/workspaces")
        match = next((w for w in workspaces if (wid and w["id"] == wid) or (name and w["displayName"] == name)), None)
        if match is None:
            visible = ", ".join(w["displayName"] for w in workspaces) or "none"
            sys.exit(f"workspace {name or wid!r} not visible to the service principal "
                     f"(add it as Contributor). Visible: {visible}")
        self.ws = match["id"]
        return match

    def ensure_folder(self, name: str) -> str:
        folders = self._paged(f"/workspaces/{self.ws}/folders")
        existing = next((f for f in folders if f["displayName"] == name and not f.get("parentFolderId")), None)
        if existing:
            return existing["id"]
        return self._check(self.http.post(f"/workspaces/{self.ws}/folders", json={"displayName": name})).json()["id"]

    def items(self, item_type: str | None = None) -> list[dict]:
        return self._paged(f"/workspaces/{self.ws}/items", {"type": item_type} if item_type else None)

    def find(self, item_type: str, name: str, folder_id: str | None = None) -> dict | None:
        """Find an item by name; with folder_id, exit if the only match is outside that folder."""
        hits = [i for i in self.items(item_type) if i["displayName"] == name]
        if folder_id is None:
            return hits[0] if hits else None
        inside = [i for i in hits if i.get("folderId") == folder_id]
        if inside:
            return inside[0]
        if hits:
            sys.exit(f"{item_type} {name!r} already exists outside folder {FOLDER_NAME!r} - not touching it. "
                     "Rename it or set FABRIC_FOLDER_NAME/FABRIC_LAKEHOUSE_NAME.")
        return None

    def ensure_lakehouse(self, name: str, folder_id: str) -> dict:
        lh = self.find("Lakehouse", name, folder_id)
        if lh is None:
            print(f"  creating lakehouse {name}")
            self._wait(self.http.post(f"/workspaces/{self.ws}/lakehouses",
                                      json={"displayName": name, "folderId": folder_id}))
            lh = self.find("Lakehouse", name, folder_id)
        return lh

    def upsert_item(self, item_type: str, name: str, definition: dict, folder_id: str) -> dict:
        item = self.find(item_type, name, folder_id)
        if item is None:
            print(f"  creating {item_type} {name}")
            self._wait(self.http.post(f"/workspaces/{self.ws}/items", json={
                "displayName": name, "type": item_type, "folderId": folder_id, "definition": definition}))
            item = self.find(item_type, name, folder_id)
        else:
            print(f"  updating {item_type} {name}")
            self._wait(self.http.post(f"/workspaces/{self.ws}/items/{item['id']}/updateDefinition",
                                      json={"definition": definition}))
        return item

    def ensure_item(self, item_type: str, name: str, folder_id: str) -> dict:
        """Create a definition-less item (ML experiment or model) if missing."""
        item = self.find(item_type, name, folder_id)
        if item is None:
            print(f"  creating {item_type} {name}")
            self._wait(self.http.post(f"/workspaces/{self.ws}/items", json={"displayName": name, "type": item_type, "folderId": folder_id}))
            item = self.find(item_type, name, folder_id)
        return item

    def definition_matches(self, item: dict, part_path: str, content: bytes) -> bool:
        """True when the item's deployed definition part equals `content` (JSON-normalised)."""
        resp = self._check(self.http.post(f"/workspaces/{self.ws}/items/{item['id']}/getDefinition"))
        body = self._wait(resp) if resp.status_code == 202 else resp.json()
        if "definition" not in body and resp.status_code == 202:
            body = self._check(self.http.get(resp.headers["Location"] + "/result")).json()
        part = next((p for p in body.get("definition", {}).get("parts", []) if p["path"] == part_path), None)
        if part is None:
            return False
        try:
            deployed = json.loads(base64.b64decode(part["payload"]))
            wanted = json.loads(content)
        except ValueError:
            return False
        def strip(d):  # ignore server-assigned node ids
            if isinstance(d, dict):
                return {k: strip(v) for k, v in d.items() if k != "id"}
            if isinstance(d, list):
                return [strip(v) for v in d]
            return d
        return strip(deployed) == strip(wanted)

    def run_job(self, item: dict, job_type: str, timeout_s: int = 3 * 3600, parameters: dict | None = None,
                fail_hard: bool = True) -> bool:
        body = {"executionData": {"parameters": {k: {"value": v, "type": "string"} for k, v in parameters.items()}}} \
            if parameters else None
        resp = self._check(self.http.post(
            f"/workspaces/{self.ws}/items/{item['id']}/jobs/instances", params={"jobType": job_type}, json=body))
        job_url = resp.headers["Location"]
        print(f"  running {item['displayName']} ({job_type}) ...", flush=True)
        start = time.time()
        while time.time() - start < timeout_s:
            time.sleep(20)
            job = self._check(self.http.get(job_url)).json()
            status = job.get("status")
            if status == "Completed":
                print(f"  {item['displayName']} completed in {int(time.time() - start)}s")
                return True
            if status in ("Failed", "Cancelled", "Deduped"):
                msg = f"{item['displayName']} {status}: {json.dumps(job.get('failureReason'))[:1500]}"
                if fail_hard:
                    sys.exit(msg)
                print("  " + msg)
                return False
        sys.exit(f"{item['displayName']} still running after {timeout_s}s")

    def tables(self, lakehouse_id: str) -> list[str]:
        return [t["name"] for t in self._paged(f"/workspaces/{self.ws}/lakehouses/{lakehouse_id}/tables")]


def upload_file(ws_id: str, lakehouse_id: str, rel_path: str, data: bytes) -> None:
    """Write to the lakehouse Files area through OneLake's ADLS Gen2 API."""
    token = get_token(STORAGE_SCOPE)
    url = f"{ONELAKE}/{ws_id}/{lakehouse_id}/Files/{rel_path}"
    h = {"Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03"}
    with RetryClient(timeout=120) as c:
        for step in (
            c.put(url, params={"resource": "file"}, headers=h),
            c.patch(url, params={"action": "append", "position": 0}, headers=h, content=data),
            c.patch(url, params={"action": "flush", "position": len(data)}, headers=h),
        ):
            if step.status_code >= 400:
                sys.exit(f"OneLake upload failed {step.status_code}: {step.text[:300]}")


def download_file(ws_id: str, lakehouse_id: str, rel_path: str) -> bytes | None:
    token = get_token(STORAGE_SCOPE)
    r = RetryClient().get(f"{ONELAKE}/{ws_id}/{lakehouse_id}/Files/{rel_path}",
                  headers={"Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03"}, timeout=120)
    return r.content if r.status_code == 200 else None


def build_wheel() -> Path:
    out = REPO / "dist"
    subprocess.run([sys.executable, "-m", "pip", "wheel", str(REPO / "backend"), "-w", str(out), "--no-deps", "-q"],
                   check=True)
    return max(out.glob("footballiq-*.whl"), key=lambda p: p.stat().st_mtime)


CELL_META = '# META {\n# META   "language": "python",\n# META   "language_group": "synapse_pyspark"\n# META }'


def py_to_fabric_source(src: str, lakehouse: dict, workspace_id: str) -> str:
    """Convert '# %%' cells to Fabric notebook-content.py; '# %% [parameters]' becomes the PARAMETERS CELL."""
    meta = {
        "kernel_info": {"name": "synapse_pyspark"},
        "dependencies": {"lakehouse": {
            "default_lakehouse": lakehouse["id"],
            "default_lakehouse_name": lakehouse["displayName"],
            "default_lakehouse_workspace_id": workspace_id,
            "known_lakehouses": [{"id": lakehouse["id"]}],
        }},
    }
    out = ["# Fabric notebook source", "", "# METADATA ********************", ""]
    out += ["# META " + line for line in json.dumps(meta, indent=2).split("\n")]
    for chunk in src.split("# %%"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        lines = chunk.split("\n")
        header = "# PARAMETERS CELL ********************" if lines[0].startswith(" [parameters]") \
            else "# CELL ********************"
        if lines[0].startswith(" ["):
            lines = lines[1:]
        code = "\n".join(lines).strip("\n")
        out += ["", header, "", code, "", "# METADATA ********************", "", CELL_META]
    return "\n".join(out) + "\n"


LAYER_TITLES = {"silver": "Silver - conformed, canonical frame", "gold": "Gold - analytics-ready",
                "meta": "Metadata", "bronze": "Bronze"}


def render_schema_md(cat: dict, workspace: str) -> str:
    """Markdown data dictionary from nb_table_catalog output."""
    out = [f"# Lakehouse schema: `{LAKEHOUSE_NAME}`", "",
           f"Generated from the live tables in workspace **{workspace}** (folder `{FOLDER_NAME}`) at "
           f"{cat['generated_at_utc'][:19]}Z by `python fabric/scripts/fabric_bootstrap.py catalog`. Do not edit by hand.",
           "", "Bronze is raw files under `Files/bronze/` (event-feed JSON; tracking JSON and JSONL.bz2), not tables.", "",
           "| Table | Layer | Rows | Columns | Partitioned by |", "|---|---|---:|---:|---|"]
    for t in cat["tables"]:
        out.append(f"| [`{t['table']}`](#{t['table']}) | {t['layer']} | {t['rows']:,} | {len(t['columns'])} | "
                   f"{', '.join(t['partition_columns']) or '-'} |")
    for layer in ("silver", "gold", "meta"):
        tables = [t for t in cat["tables"] if t["layer"] == layer]
        if not tables:
            continue
        out += ["", f"## {LAYER_TITLES.get(layer, layer)}"]
        for t in tables:
            out += ["", f"### {t['table']}", "",
                    f"{t['rows']:,} rows, {t['num_files']} files, {t['size_bytes'] / 1e6:,.1f} MB"
                    + (f", partitioned by `{', '.join(t['partition_columns'])}`" if t["partition_columns"] else ""),
                    "", "| # | Column | Type | Nullable |", "|---:|---|---|---|"]
            out += [f"| {i} | `{c['name']}` | `{c['type']}` | {'yes' if c['nullable'] else 'no'} |"
                    for i, c in enumerate(t["columns"])]
    return "\n".join(out) + "\n"


EVENTHOUSE_NAME = os.environ.get("FABRIC_EVENTHOUSE_NAME", "eh_football_rt")
EVENTSTREAM_NAME = os.environ.get("FABRIC_EVENTSTREAM_NAME", "es_football_replay")
DASHBOARD_NAME = "rtd_football_live"


def apply_kql(cluster_uri: str, database: str, path: Path) -> None:
    """Run each `//--`-separated management command (all idempotent)."""
    token = get_token(f"{cluster_uri}/.default")
    with RetryClient(timeout=120) as c:
        for cmd in path.read_text().split("\n//--\n"):
            body = "\n".join(l for l in cmd.split("\n") if not l.lstrip().startswith("//")).strip()
            if not body:
                continue
            r = c.post(f"{cluster_uri}/v1/rest/mgmt", headers={"Authorization": f"Bearer {token}"},
                       json={"db": database, "csl": body})
            if r.status_code != 200:
                sys.exit(f"KQL command failed ({r.status_code}): {body.splitlines()[0][:100]}\n{r.text[:400]}")
    print(f"  applied {path.name} to {database}")


def deploy_realtime(fab: "Fabric") -> dict:
    folder_id = fab.ensure_folder(FOLDER_NAME)
    eh = fab.find("Eventhouse", EVENTHOUSE_NAME, folder_id)
    if eh is None:
        print(f"  creating eventhouse {EVENTHOUSE_NAME}")
        fab._wait(fab.http.post(f"/workspaces/{fab.ws}/eventhouses", json={"displayName": EVENTHOUSE_NAME, "folderId": folder_id}))
        eh = fab.find("Eventhouse", EVENTHOUSE_NAME, folder_id)
    props = fab._check(fab.http.get(f"/workspaces/{fab.ws}/eventhouses/{eh['id']}")).json()["properties"]
    cluster = props["queryServiceUri"]
    db_id = props["databasesItemIds"][0]
    db_name = fab._check(fab.http.get(f"/workspaces/{fab.ws}/kqlDatabases/{db_id}")).json()["displayName"]
    print(f"eventhouse {EVENTHOUSE_NAME}: {cluster} db={db_name}")
    apply_kql(cluster, db_name, FABRIC_DIR / "kql" / "football_rt.kql")

    subst = {"workspace_id": fab.ws, "kql_database_id": db_id, "cluster_uri": cluster}

    def render(path: Path) -> bytes:
        text = path.read_text()
        for k, v in subst.items():
            text = text.replace("{{" + k + "}}", v)
        if "{{" in text:
            sys.exit(f"unresolved placeholder in {path}")
        return text.encode()

    es_json = render(FABRIC_DIR / "eventstream" / f"{EVENTSTREAM_NAME}.json")
    es = fab.find("Eventstream", EVENTSTREAM_NAME, folder_id)
    if es is not None and fab.definition_matches(es, "eventstream.json", es_json):
        # updating a live eventstream re-provisions its destination and pauses ingestion: skip if unchanged
        print(f"  eventstream {EVENTSTREAM_NAME} unchanged")
    else:
        es = fab.upsert_item("Eventstream", EVENTSTREAM_NAME, {"parts": [
            {"path": "eventstream.json", "payload": b64(es_json), "payloadType": "InlineBase64"}]}, folder_id)
    topo = fab._check(fab.http.get(f"/workspaces/{fab.ws}/eventstreams/{es['id']}/topology")).json()
    print("  eventstream:", ", ".join(f"{n['name']}={n.get('status')}" for n in topo["sources"] + topo["destinations"]))
    fab.upsert_item("KQLDashboard", DASHBOARD_NAME, {"parts": [
        {"path": "RealTimeDashboard.json", "payload": b64(render(FABRIC_DIR / "dashboards" / f"{DASHBOARD_NAME}.json")),
         "payloadType": "InlineBase64"}]}, folder_id)
    return {"cluster": cluster, "database": db_name, "eventstream_id": es["id"]}


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def deploy(fab: Fabric) -> tuple[dict, dict]:
    folder_id = fab.ensure_folder(FOLDER_NAME)
    print(f"folder {FOLDER_NAME}: {folder_id}")
    lh = fab.ensure_lakehouse(LAKEHOUSE_NAME, folder_id)
    print(f"lakehouse {LAKEHOUSE_NAME}: {lh['id']}")

    wheel = build_wheel()
    upload_file(fab.ws, lh["id"], f"wheels/{wheel.name}", wheel.read_bytes())
    print(f"  uploaded Files/wheels/{wheel.name}")
    for nb_src in sorted((FABRIC_DIR / "notebooks").glob("*.py")):  # sources for nb_debug_runner
        upload_file(fab.ws, lh["id"], f"src/{nb_src.name}", nb_src.read_bytes())
    for local, remote in CONFIG_FILES.items():
        upload_file(fab.ws, lh["id"], remote, local.read_bytes())
        print(f"  uploaded Files/{remote}")

    ids = {"workspace_id": fab.ws}
    for name in NOTEBOOKS:
        src = (FABRIC_DIR / "notebooks" / f"{name}.py").read_text()
        content = py_to_fabric_source(src, lh, fab.ws).encode()
        nb = fab.upsert_item("Notebook", name, {"parts": [
            {"path": "notebook-content.py", "payload": b64(content), "payloadType": "InlineBase64"}]}, folder_id)
        ids[name] = nb["id"]
    fab.ensure_item("MLExperiment", ML_EXPERIMENT, folder_id)
    for name in ML_MODELS:
        fab.ensure_item("MLModel", name, folder_id)

    pipeline_json = (FABRIC_DIR / "pipelines" / f"{PIPELINE_NAME}.json").read_text()
    for key, val in ids.items():
        pipeline_json = pipeline_json.replace("{{" + key + "}}", val)
    if "{{" in pipeline_json:
        sys.exit("unresolved placeholder in pipeline template")
    pl = fab.upsert_item("DataPipeline", PIPELINE_NAME, {"parts": [
        {"path": "pipeline-content.json", "payload": b64(pipeline_json.encode()), "payloadType": "InlineBase64"}]},
        folder_id)
    return lh, pl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["check", "deploy", "run", "all", "debug", "catalog", "realtime"])
    ap.add_argument("notebook", nargs="?", help="debug: notebook to run through nb_debug_runner")
    ap.add_argument("--overrides", default="{}", help='debug: JSON parameter overrides, e.g. {"GAME_IDS": "10517"}')
    args = ap.parse_args()

    fab = Fabric(get_token(FABRIC_SCOPE))
    ws = fab.resolve_workspace()
    items = fab.items()
    print(f"workspace {ws['displayName']} ({ws['id']}): {len(items)} items")
    if args.command == "check":
        for i in items:
            print(f"  {i['type']:<22} {i['displayName']}")
        return

    if args.command == "realtime":
        deploy_realtime(fab)
        print("real-time path deployed. Start the API with FABRIC_* set; it resolves the Eventstream connection itself.")
        return

    if args.command == "catalog":
        folder_id = fab.ensure_folder(FOLDER_NAME)
        lh = fab.find("Lakehouse", LAKEHOUSE_NAME, folder_id) or sys.exit("lakehouse missing - run deploy first")
        fab.run_job(fab.find("Notebook", "nb_table_catalog", folder_id), "RunNotebook")
        cat = json.loads(download_file(fab.ws, lh["id"], "catalog/tables.json"))
        (FABRIC_DIR / "SCHEMA.md").write_text(render_schema_md(cat, ws["displayName"]))
        print(f"wrote {FABRIC_DIR / 'SCHEMA.md'} ({len(cat['tables'])} tables)")
        return

    if args.command == "debug":
        lh, _ = deploy(fab)
        runner = fab.find("Notebook", "nb_debug_runner", fab.ensure_folder(FOLDER_NAME))
        ok = fab.run_job(runner, "RunNotebook", parameters={"NOTEBOOK": args.notebook, "OVERRIDES": args.overrides,
                                     "LOG_URI": f"abfss://{fab.ws}@onelake.dfs.fabric.microsoft.com/{lh['id']}"
                                                f"/Files/logs/{args.notebook}.log"},
                         fail_hard=False)
        log = download_file(fab.ws, lh["id"], f"logs/{args.notebook}.log")
        text = log.decode(errors="replace") if log else "(no log written - runner failed before logging)"
        print(text[-12000:])
        sys.exit(0 if ok and "RESULT: SUCCESS" in text else 1)

    if args.command in ("deploy", "all"):
        lh, pl = deploy(fab)
        deploy_realtime(fab)
    else:
        folder_id = fab.ensure_folder(FOLDER_NAME)
        lh = fab.find("Lakehouse", LAKEHOUSE_NAME, folder_id) or sys.exit("lakehouse missing - run deploy first")
        pl = fab.find("DataPipeline", PIPELINE_NAME, folder_id) or sys.exit("pipeline missing - run deploy first")

    if args.command in ("run", "all"):
        fab.run_job(pl, "Pipeline")
        present = set(fab.tables(lh["id"]))
        missing = [t for t in EXPECTED_TABLES if t not in present]
        print(f"tables present: {sorted(present & set(EXPECTED_TABLES))}")
        if missing:
            sys.exit(f"missing tables: {missing}")
        print("bronze/silver/gold verified.")


if __name__ == "__main__":
    main()
