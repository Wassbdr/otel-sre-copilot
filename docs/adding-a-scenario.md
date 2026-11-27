# Add a scenario

1. Copy a YAML file from [`scenarios/mvp`](../scenarios/mvp) into
   [`scenarios/extended`](../scenarios/extended). Give it a unique filename,
   `metadata.scenario_id`, seed, namespace, description and fault duration.
   Set `metadata.split` to `development` or `held-out` before running it.
2. Set `fault_service` and `fault_type` under `metadata`. Make the
   `chaos_manifest` selector match one service in the demo namespace. For a
   multi-fault case, use a top-level `faults` list, where each item contains
   `fault_service`, `fault_type` and `chaos_manifest`. Keep each manifest name
   distinct.
3. Validate the YAML before applying it. The dry run writes an unvalidated
   ground-truth file, so use it only for a new scenario ID. Run captures only
   against a test cluster that you control. Wait for at least one baseline
   window after a fault before capturing the next scenario.

```bash
.venv/bin/python scripts/inject_and_snapshot.py \
  --scenario scenarios/extended/008-currency-latency.yaml --dry-run
make health-check
make fault SCENARIO=scenarios/extended/008-currency-latency.yaml
```

The capture writes telemetry and `ground_truth.json` to `snapshots/<id>/`.
Check `validation_passed`, confirm the observed signal is consistent with the
fault, and review every committed file for sensitive data. Keep each file
under 5 MB. Do not commit telemetry from a private cluster.

`make bench BENCH_SPLIT=development BENCH_RUN_ID=<new-id>` discovers validated
development snapshots. Restart with the same run ID to resume. Use a new run
ID after changing the cohort. Use `BENCH_SPLIT=held-out` only for a final
check, not to tune prompts or ranking.
