# Matched-strict drift probe comparison (2026-08-03 vs 2026-08-06)

This probe covers ONLY the matched-strict protocol. qwen3.5:9b also appears in the in-loop revision campaign and the 2,000-run matched campaign; a clean matched-strict comparison is evidence of stability for this protocol only, not proof those other campaigns are unaffected by the digest drift found on 2026-08-06 -- do not generalize beyond matched-strict.

This probe ran on evaluate_batch.py as instrumented for provenance capture (Task 3b, 2026-08-06). Verified before running: constructed Ollama chat_kwargs are byte-identical pre/post instrumentation; only the model's own stochastic sampled content differs run-to-run, which is expected and unrelated to instrumentation.

| Model | Status | Severity exact (old->new) | Union yield (old->new) | Citation halluc. (old->new) | Genuine SHACL (old->new) | Schema fails (old->new) | Scenario disagreements |
|---|---|---|---|---|---|---|---|
| qwen3.5_2b | compared | 13/40=0.325 -> 10/40=0.250 | 29/40=0.725 -> 34/40=0.850 | 9/40=0.225 -> 8/40=0.200 | 12/40=0.300 -> 11/40=0.275 | 1 -> 4 | 0/40 |
| qwen3.5_9b | compared | 23/40=0.575 -> 22/40=0.550 | 32/40=0.800 -> 33/40=0.825 | 2/40=0.050 -> 1/40=0.025 | 5/40=0.125 -> 8/40=0.200 | 0 -> 0 | 1/40 |
| gemma3_4b | compared | 19/40=0.475 -> 19/40=0.475 | 28/40=0.700 -> 26/40=0.650 | 12/40=0.300 -> 7/40=0.175 | 14/40=0.350 -> 12/40=0.300 | 2 -> 1 | 0/40 |
| gemma3_27b | compared | 30/40=0.750 -> 29/40=0.725 | 40/40=1.000 -> 40/40=1.000 | 0/40=0.000 -> 0/40=0.000 | 3/40=0.075 -> 3/40=0.075 | 0 -> 0 | 0/40 |

## qwen3.5:0.8b failure mode

```json
{
  "model": "qwen3.5_0.8b",
  "failed_marker_present": true,
  "done_marker_present": false,
  "old_failed_marker_present": true,
  "failure_text_excerpt": "failed after 3 attempts: Schema validation failed: 1 validation error for RiskReport",
  "reproduces_known_signature": true,
  "note": "qwen3.5:0.8b did not complete the protocol on 2026-08-03 either (persistent schema-validation failures, RuntimeError after MAX_GENERATION_ATTEMPTS). Reported here as a failure-mode check only -- never folded into the qwen3.5_2b/9b or gemma3_4b/27b delta comparison."
}
```
