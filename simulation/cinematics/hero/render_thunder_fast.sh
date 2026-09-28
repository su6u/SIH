#!/usr/bin/env bash
set -euo pipefail

# Five-hour presentation path. One independent Blender worker is started per GPU,
# because animation frames do not depend on one another.
PROJECT_DIR="${SWARM_PROJECT_DIR:-/home/ubuntu/kinesis-render}"
BLENDER_BIN="${SWARM_BLENDER_BIN:-$(command -v blender || true)}"
OUTPUT_DIR="${SWARM_OUTPUT_DIR:-$PROJECT_DIR/frames-1080p24}"
SAMPLES="${SWARM_SAMPLES:-96}"
TIME_LIMIT="${SWARM_TIME_LIMIT:-12}"
TOTAL_FRAMES=960

if [[ -z "$BLENDER_BIN" || ! -x "$BLENDER_BIN" ]]; then
  echo "Set SWARM_BLENDER_BIN to a working Blender 4.2 executable" >&2
  exit 2
fi
if [[ ! -f "$PROJECT_DIR/kinesis-hero-40s.blend" || ! -f "$PROJECT_DIR/render.py" ]]; then
  echo "Missing blend or render.py in $PROJECT_DIR" >&2
  exit 2
fi

GPU_COUNT="$(nvidia-smi --list-gpus | wc -l | tr -d ' ')"
if [[ "$GPU_COUNT" -lt 1 ]]; then
  echo "No NVIDIA GPU visible" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR" "$PROJECT_DIR/logs"
echo "Launching $GPU_COUNT frame-parallel OptiX worker(s)"

pids=()
for ((gpu=0; gpu<GPU_COUNT; gpu++)); do
  start=$((gpu * TOTAL_FRAMES / GPU_COUNT + 1))
  end=$(((gpu + 1) * TOTAL_FRAMES / GPU_COUNT))
  log="$PROJECT_DIR/logs/fast-gpu-${gpu}.log"
  echo "GPU $gpu: output frames $start-$end"
  CUDA_VISIBLE_DEVICES="$gpu" "$BLENDER_BIN" \
    --background --factory-startup --python-exit-code 1 \
    --python "$PROJECT_DIR/render.py" -- \
    --blend "$PROJECT_DIR/kinesis-hero-40s.blend" \
    --device OPTIX --format PNG --resolution 1080p \
    --samples "$SAMPLES" --adaptive-threshold .01 --time-limit "$TIME_LIMIT" \
    --output-fps 24 --start "$start" --end "$end" --output "$OUTPUT_DIR" \
    >"$log" 2>&1 &
  pids+=("$!")
done

failed=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then failed=1; fi
done

completed="$(find "$OUTPUT_DIR" -maxdepth 1 -name 'hero_*.png' | wc -l | tr -d ' ')"
echo "Completed frames: $completed/$TOTAL_FRAMES"
if [[ "$failed" -ne 0 || "$completed" -ne "$TOTAL_FRAMES" ]]; then
  echo "One or more workers did not finish; rerun this script to resume safely" >&2
  exit 1
fi
echo "Render complete: $OUTPUT_DIR"
