# Microsoft Fabric: data platform

Every Fabric item for FootballIQ lives in this folder and is deployed from here. Nothing is edited only in the portal.
`scripts/fabric_bootstrap.py` builds the items from these sources and creates or updates them through the Fabric REST
API with the Entra ID service principal. Credentials come only from environment variables; see `../.env.example`.

Architecture diagram: [../docs/architecture/02-lld-data-ingestion.png](../docs/architecture/02-lld-data-ingestion.png).

## Items (workspace folder `FootballIQ`)

| Item | Source in repo | Role |
|---|---|---|
| Lakehouse `lh_football_intelligence` | created by `scripts/fabric_bootstrap.py` | OneLake storage: `Files/` (bronze, config, wheels, models) and Delta `Tables/` (silver, gold) |
| Ingest notebooks | `notebooks/nb_*_ingest.py` | One per feed: the match event feed (64 tournament matches plus earlier competitions), broadcast tracking (64 matches, 30 fps), optical tracking (club matches, 25 fps) and club broadcast tracking (10 fps). Each writes bronze files, then the `silver_match*`, `silver_player*` and `silver_tracking_*` tables in one common spatial schema |
| Notebook `nb_gold_build` | `notebooks/nb_gold_build.py` | Event gold: `gold_team_metrics_5s`, `gold_player_match_metrics`, `gold_match_summary`, `gold_match_history` |
| Notebook `nb_gold_tracking` | `notebooks/nb_gold_tracking.py` | Tracking gold: `gold_player_metrics_1s`, `gold_player_physical_match`, `gold_team_shape_5s`, `gold_tracking_coverage_1m` |
| Notebook `nb_gold_possession` | `notebooks/nb_gold_possession.py` | Possession from tracking (5 Hz ball-control model, dead-ball aware): `gold_possession_sample`, `gold_possession_benchmark` |
| Notebook `nb_gold_tactical` | `notebooks/nb_gold_tactical.py` | Tactical windows (possession, links, motifs, lane clearance, detected vs team-sheet shape), `gold_passing_network`, `gold_heatmap`, `gold_regains` |
| Notebook `nb_ml_train` | `notebooks/nb_ml_train.py` | Model training (on demand), see below. Writes `Files/models/<version>/`, MLflow runs, `ml_model_registry`, `gold_model_evaluation`, `gold_model_calibration` |
| Notebook `nb_ml_xpass_tracking` | `notebooks/nb_ml_xpass_tracking.py` | Tracking-based xPass that also sees defender positions: `gold_pass_xpass` |
| Notebook `nb_ml_score` | `notebooks/nb_ml_score.py` | Scores every match: `gold_event_model_values`, `gold_prediction_log` (15 s grid), `gold_prediction_features` |
| ML experiment `exp_footballiq_models`, ML models `fiq_*` | created by `scripts/fabric_bootstrap.py` | MLflow tracking and model registry |
| Notebook `nb_table_catalog` | `notebooks/nb_table_catalog.py` | Data dictionary: `meta_table_catalog` and `Files/catalog/tables.json`, which generates [`SCHEMA.md`](SCHEMA.md) |
| Notebook `nb_debug_runner` | `notebooks/nb_debug_runner.py` | Ops helper: runs a notebook cell by cell and writes tracebacks to `Files/logs/` |
| Data pipeline `pl_football_medallion` | `pipelines/pl_football_medallion.json` | Orchestration (see below) |
| Eventstream `es_football_replay` | `eventstream/es_football_replay.json` | Custom endpoint `replay-api` that receives replay events from the API |
| Eventhouse `eh_football_rt` | `kql/football_rt.kql` | KQL database: `ReplayRaw` and update policies into `TrackingSecond`, `MatchEvents`, `MatchState`, `MatchPredictions`, `ReplayTelemetry` |
| Real-Time Dashboard `rtd_football_live` | `dashboards/rtd_football_live.json` | Live replay sessions, camera coverage, team shape, pipeline lag, key events |
| Files `config/` | `config/` | Source-file manifests for the tracking feed |
| Files `wheels/footballiq-*.whl` | built from `../backend` | The same normalisation code as the API, imported by the notebooks |

## Pipeline `pl_football_medallion`

```
events → bronze/silver ──► tracking → bronze/silver ──► gold_tracking ──► gold_possession ──► gold_tactical ──┐
            │                                                                                                ├──► table_catalog
            └────────────► gold_events ──────────────────────────────────────────────────────────────────────┘
```

The `game_ids` parameter (default `all`) limits the tracking notebooks to a comma list of matches. Every notebook is
idempotent: a full run replaces its tables, and a partial run replaces only the listed matches (`replaceWhere`).

## Machine learning

Models are trained and scored on demand, outside the medallion pipeline, with the shared code in
`backend/footballiq/ml/`.

| Model | Algorithm |
|---|---|
| xG | LightGBM classifier, isotonic calibration, 5 bootstrap members for the uncertainty band |
| xPass | LightGBM classifier (event-based; a tracking-based variant in `nb_ml_xpass_tracking`) |
| Goal in 10′, corner in 2′ | LightGBM classifiers, monotone in Elo difference |
| Penalty in 5′ | Logistic regression with Platt (sigmoid) calibration |
| Win probability | LightGBM Poisson regression of the remaining goals, converted into win / draw / loss odds |
| Expected threat (xT) | Markov possession-value grid, 16 × 12 |
| Formation | Hungarian assignment to 11 templates |
| Team strength | Elo ratings and recent form (pre-match priors) |

Training uses GroupKFold by match and chronological epochs: each run trains on everything before a cutoff date and
tests on competitions played after it, and each match is scored by the latest epoch before its kickoff.

```bash
python fabric/scripts/fabric_bootstrap.py debug nb_ml_train --overrides '{"CUTOFF": "2022-11-20"}'
python fabric/scripts/fabric_bootstrap.py debug nb_ml_score
```

## Commands

```bash
set -a; source .env; set +a                                  # FABRIC_* variables
python fabric/scripts/fabric_bootstrap.py check             # auth + workspace items
python fabric/scripts/fabric_bootstrap.py deploy            # folder, lakehouse, files, notebooks, pipeline
python fabric/scripts/fabric_bootstrap.py run               # run the pipeline, verify every expected table
python fabric/scripts/fabric_bootstrap.py all               # deploy + run
python fabric/scripts/fabric_bootstrap.py debug <notebook> --overrides '{"GAME_IDS": "<id>"}'
python fabric/scripts/fabric_bootstrap.py catalog           # refresh SCHEMA.md from the live tables
```

The script only creates or updates items inside the `FootballIQ` folder. It stops if an item with the same name
already exists elsewhere in the workspace. Notebooks are deployed in Fabric's native `notebook-content.py` format, so
the `# %% [parameters]` cell becomes a real parameters cell.

## Data model rules

- **Canonical frame:** 105 × 68 m, origin top-left, with the home team attacking left to right in every period.
  Source coordinates are kept in the source fields.
- **match_id** = `<date>_<home>_<away>`, identical across feeds. Clients only ever see public aliases.
- **Clock:** `match_elapsed_ms` is one monotonic clock across periods. Tracking is aligned to the event feed's period table.
- **Direction:** attacking direction comes from each goalkeeper's mean position per period (observed data).
  `direction_agrees_with_metadata` flags any disagreement with the feed's metadata.
- **Observed vs estimated:** estimated positions are kept and flagged, and never presented as observed. An unknown
  observation state stays NULL.
- **No spoilers:** gold history rows carry `as_of_time`, so pre-match features stop at kickoff.

## Current load

All 64 tournament matches: 234,637 events (64 of 64 scores reconcile), 144,541 tracking-feed events (98.9% placed on
the match clock), 11.8M tracking frames and 260.7M player positions, with no duplicate keys. The full column-level
dictionary is in [`SCHEMA.md`](SCHEMA.md).

## Known limitations

- Two matches have no tracking for extra time; events cover those periods. 61 matches have 2 tracked periods and 3 have 4.
- Event and tracking clocks drift by a few seconds in extra time.
- Physical metrics use fixed speed thresholds (see the `thresholds` column); they are not fatigue or medical measures.
- Check each data feed's licence terms before any external use.
