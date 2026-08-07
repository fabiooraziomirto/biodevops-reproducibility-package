# New 9-model matched_strict sweep decomposition (corrected classifier)

| Model | n | OPA-only | SHACL-only | Overlap | Neither | Overlap: structural | Overlap: genuine | Overlap: mixed | Raw union yield | Structural share of union |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| qwen3.5_0.8b | FAILED/MISSING | - | - | - | - | - | - | - | - | - |
| gemma3_1b | 40 | 5 | 0 | 27 | 8 | 27 | 0 | 0 | 32/40=0.800 | 27/32=0.844 |
| qwen3.5_2b | 40 | 2 | 5 | 22 | 11 | 15 | 7 | 0 | 29/40=0.725 | 15/29=0.517 |
| gemma3_4b | 40 | 10 | 12 | 6 | 12 | 3 | 2 | 0 | 28/40=0.700 | 3/28=0.107 |
| qwen3.5_4b | 40 | 0 | 3 | 37 | 0 | 37 | 0 | 0 | 40/40=1.000 | 37/40=0.925 |
| gemma3_12b | 40 | 11 | 14 | 9 | 6 | 9 | 0 | 0 | 34/40=0.850 | 9/34=0.265 |
| qwen3.5_9b | 40 | 7 | 3 | 22 | 8 | 20 | 2 | 0 | 32/40=0.800 | 20/32=0.625 |
| gemma3_27b | 40 | 2 | 3 | 35 | 0 | 35 | 0 | 0 | 40/40=1.000 | 35/40=0.875 |
| qwen3.5_27b | 40 | 4 | 0 | 1 | 35 | 0 | 0 | 0 | 5/40=0.125 | 0/5=0.000 |
