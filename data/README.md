# Local data folder (git-ignored)

Used only in offline mode (`FOOTBALLIQ_SOURCE=local`). In production the API reads the Fabric lakehouse.

```
data/
  bronze/<feed>/<match_id>/      raw feed files + manifest.json (sha256, URL, download time)
  silver/<canonical_match_id>/   match.json, events.jsonl, freeze_frames.jsonl, id_map.jsonl
  cache/                         API result cache (safe to delete)
```

`footballiq-ingest` downloads the reference match into this layout. In Fabric the same layout lives in the
`lh_football_intelligence` lakehouse (`Files/bronze/...` plus the `silver_*` Delta tables).

Check each data feed's licence terms before storing or redistributing its data.
