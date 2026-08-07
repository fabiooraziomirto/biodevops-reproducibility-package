#!/usr/bin/env bash
# Matched-strict scaling sweep driver (si_scaling_sweep_2026).
#
# Runs the 40-scenario (20 dev + 20 held-out) matched-strict protocol via
# evaluate_batch.py for every model size in ascending order across the
# qwen3.5 and gemma3 families. think=False is the generate_risk_report()
# default (patched into rag_pipeline.py in this workspace) so every call is
# non-reasoning by default; no extra flag is needed here.
#
# Usage: nohup bash run_matched_strict_sweep.sh > sweep.log 2>&1 &
set -euo pipefail

ROOT="/root/Desktop/BioDevOps/si_scaling_sweep_2026"
RAG="$ROOT/biodevops_rag"
RESULTS="$ROOT/results/matched_strict"
mkdir -p "$RESULTS"

export BIODEVOPS_OLLAMA_TIMEOUT_SECONDS=900
export BIODEVOPS_NO_MOCK_FALLBACK=1

# Ascending order, interleaved by family so small models complete first.
MODELS=(
  "qwen3.5:0.8b"
  "gemma3:1b"
  "qwen3.5:2b"
  "gemma3:4b"
  "qwen3.5:4b"
  "gemma3:12b"
  "qwen3.5:9b"
  "gemma3:27b"
  "qwen3.5:27b"
)

cd "$RAG"

for MODEL in "${MODELS[@]}"; do
  SAFE_NAME=$(echo "$MODEL" | tr ':' '_')
  OUT_DIR="$RESULTS/$SAFE_NAME"
  DONE_MARKER="$OUT_DIR/.done"
  if [ -f "$DONE_MARKER" ]; then
    echo "[skip] $MODEL already completed ($DONE_MARKER present)"
    continue
  fi
  mkdir -p "$OUT_DIR"

  echo "=== $(date -u +%FT%TZ) pulling $MODEL ==="
  ollama pull "$MODEL"

  DIGEST=$(ollama show "$MODEL" --modelfile 2>/dev/null | sha256sum | cut -d' ' -f1)
  echo "$MODEL digest(modelfile_sha256)=$DIGEST" >> "$OUT_DIR/model_digest.txt"

  MODEL_FAILED=0
  for SPLIT in development held_out; do
    echo "=== $(date -u +%FT%TZ) $MODEL split=$SPLIT ==="
    set +e
    venv/bin/python scripts/evaluate_batch.py \
      --mode rag \
      --dataset corpus/synthetic_maude_arrhythmia_independent_40.json \
      --split "$SPLIT" \
      --split-file corpus/independent_40_split.json \
      --ollama-model "$MODEL" \
      --prompt-condition baseline \
      --output-dir "$OUT_DIR/$SPLIT" \
      --clinical-facts-bundle ontology/clinical_concepts_independent_40.json \
      --paper-grade \
      > "$OUT_DIR/${SPLIT}.log" 2>&1
    STATUS=$?
    set -e
    if [ $STATUS -ne 0 ]; then
      echo "!!! $(date -u +%FT%TZ) $MODEL split=$SPLIT FAILED (exit $STATUS) — see $OUT_DIR/${SPLIT}.log"
      tail -20 "$OUT_DIR/${SPLIT}.log"
      MODEL_FAILED=1
    fi
  done

  if [ "$MODEL_FAILED" -eq 1 ]; then
    echo "!!! $(date -u +%FT%TZ) $MODEL INCOMPLETE — not marking done, continuing to next model" > "$OUT_DIR/.failed"
    continue
  fi

  date -u +%FT%TZ > "$DONE_MARKER"
  echo "=== $(date -u +%FT%TZ) $MODEL COMPLETE ==="
done

echo "=== $(date -u +%FT%TZ) SWEEP COMPLETE ==="
