# Fabric notebook source: nb_debug_runner
# Attach to Lakehouse: lh_football_intelligence
#
# Ops helper, not in the pipeline: runs Files/src/<NOTEBOOK>.py cell by cell and logs per-cell
# status and tracebacks, which the Fabric job API does not expose.

# %% [parameters]
NOTEBOOK = "nb_statsbomb_ingest"
OVERRIDES = "{}"   # JSON applied over the parameters cell, e.g. {"GAME_IDS": "10517"}
LOG_URI = ""       # abfss:// log path; default Files/logs/<NOTEBOOK>.log

# %%
import io
import json
import time
import traceback
from contextlib import redirect_stdout

import notebookutils

log_target = LOG_URI or f"Files/logs/{NOTEBOOK}.log"
lines_out = [f"runner start NOTEBOOK={NOTEBOOK} OVERRIDES={OVERRIDES}"]


def w(msg):
    # notebookutils (not the FUSE mount) so the log survives a cancelled session.
    lines_out.append(msg)
    notebookutils.fs.put(log_target, "\n".join(lines_out), True)


w("logging to " + log_target)
failed = None
try:
    src = open(f"/lakehouse/default/Files/src/{NOTEBOOK}.py").read()
    ns = {"spark": spark, "__name__": "__main__",  # noqa: F821
          "display": lambda df, *a, **k: w(df.limit(20).toPandas().to_string())}
    marker = "# " + "%%"  # a literal marker would split this notebook's own cell
    cells = [c.strip("\n") for c in src.split(marker) if c.strip()]
    for i, cell in enumerate(cells):
        lines = cell.split("\n")
        is_params = lines[0].startswith(" [parameters]")
        if lines[0].startswith(" ["):
            lines = lines[1:]
        code = "\n".join(lines)
        t0 = time.time()
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                exec(compile(code, f"{NOTEBOOK}[cell {i}]", "exec"), ns)
                if is_params:
                    ns.update(json.loads(OVERRIDES))
            w(f"[cell {i}] OK {time.time() - t0:.1f}s\n{buf.getvalue()[-3000:]}")
        except BaseException:
            w(f"[cell {i}] FAILED {time.time() - t0:.1f}s\n{buf.getvalue()[-3000:]}\n--- code ---\n{code[:1500]}"
              f"\n--- traceback ---\n{traceback.format_exc()}")
            failed = i
            break
except BaseException:
    w("runner error:\n" + traceback.format_exc())
    failed = -1
w("RESULT: " + ("SUCCESS" if failed is None else f"FAILED at cell {failed}"))
