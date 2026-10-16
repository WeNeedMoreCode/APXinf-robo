#!/bin/bash
# val_spatial_t4_range_1016.sh — range padding 生产切换后 t4 ×5 行为复验
# 与 val_spatial_t4_pool_1015.sh 同口径（spatial task4 ×5 trial、seed 7），
# 换新 results-jsonl。判读：≥ 4/5 且无挣扎步（对照 pool 时代 5/5：
# 120/124/116/130/127）
cd /data/apxinf
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=4 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=/data/apxinf/serve_gear \
timeout 1800 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_spatial --tasks 4 --trials-per-task 5 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl /data/apxinf/serve_gear/val_spatial_t4_range.jsonl \
  --summary-json /data/apxinf/serve_gear/val_spatial_t4_range_summary.json \
  > /data/apxinf/serve_gear/val_spatial_t4_range.log 2>&1
echo "T4_RANGE_RC=$?"
tail -3 /data/apxinf/serve_gear/val_spatial_t4_range_summary.json 2>/dev/null
