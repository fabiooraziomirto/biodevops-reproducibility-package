#!/usr/bin/env bash
# Orchestrates the full RQ2 bounded-agent matched campaign (development + held_out,
# 20 scenarios x 5 replicates x 4 arms each) across all 9 scaling-sweep models,
# smallest first for fast feedback. Continues past a whole-model crash (logged,
# not fatal) so one bad model doesn't block the rest of the queue.
set -uo pipefail

export BIODEVOPS_OLLAMA_TIMEOUT_SECONDS=600
export BIODEVOPS_CHROMA_DB=/root/Desktop/BioDevOps/biodevops_rag/chroma_db_independent_40
export OLLAMA_HOST=http://localhost:11434

PY=/root/Desktop/BioDevOps/biodevops_rag/venv/bin/python
SCRIPT=/root/Desktop/BioDevOps/si_scaling_sweep_2026/scripts/run_bounded_agent_multimodel.py
OUT_ROOT=/root/Desktop/BioDevOps/si_scaling_sweep_2026/results/rq2_multimodel_bounded_agent
LOG_DIR="$OUT_ROOT/logs"
mkdir -p "$LOG_DIR"

# model:digest:safe_name, smallest first
MODELS=(
  "qwen3.5:0.8b:f3817196d142:qwen3.5_0.8b"
  "gemma3:1b:8648f39daa8f:gemma3_1b"
  "qwen3.5:2b:324d162be6ca:qwen3.5_2b"
  "gemma3:4b:a2af6cc3eb7f:gemma3_4b"
  "qwen3.5:4b:2a654d98e6fb:qwen3.5_4b"
  "qwen3.5:9b:6488c96fa5fa:qwen3.5_9b"
  "gemma3:12b:f4031aab637d:gemma3_12b"
  "gemma3:27b:a418f5838eaf:gemma3_27b"
  "qwen3.5:27b:7653528ba5cb:qwen3.5_27b"
)

MASTER_LOG="$OUT_ROOT/queue_master.log"
echo "=== RQ2 multimodel queue started $(date -u +%FT%TZ) ===" | tee -a "$MASTER_LOG"

for entry in "${MODELS[@]}"; do
  IFS=":" read -r model_family model_size digest safe_name <<< "$entry"
  model="${model_family}:${model_size}"
  for split in development held_out; do
    out_dir="$OUT_ROOT/$safe_name/$split"
    if [ -f "$out_dir/analysis.json" ]; then
      echo "SKIP (already complete): $model / $split" | tee -a "$MASTER_LOG"
      continue
    fi
    log_file="$LOG_DIR/${safe_name}_${split}.log"
    echo "--- START $model / $split $(date -u +%FT%TZ) ---" | tee -a "$MASTER_LOG"
    start_ts=$(date +%s)
    if "$PY" "$SCRIPT" --model "$model" --model-digest "$digest" --split "$split" --output-dir "$out_dir" > "$log_file" 2>&1; then
      status="OK"
    else
      status="FAILED(exit=$?)"
    fi
    end_ts=$(date +%s)
    elapsed=$((end_ts - start_ts))
    echo "--- END $model / $split status=$status elapsed=${elapsed}s $(date -u +%FT%TZ) ---" | tee -a "$MASTER_LOG"
  done
done

echo "=== RQ2 multimodel queue finished $(date -u +%FT%TZ) ===" | tee -a "$MASTER_LOG"
