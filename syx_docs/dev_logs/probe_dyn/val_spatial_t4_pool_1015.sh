#!/bin/bash
# val_spatial_t4_pool_1015.sh — T4R ④：prefix 静态池化后 spatial t4 ×5 复验
# （门限 ≥4/5 = 达到静态路径水平 → 回退桶真退役定案）
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
  --results-jsonl /data/apxinf/serve_gear/val_spatial_t4_pool.jsonl \
  --summary-json /data/apxinf/serve_gear/val_spatial_t4_pool_summary.json \
  > /data/apxinf/serve_gear/val_spatial_t4_pool.log 2>&1
echo "VAL_RC=$? $(date -u '+%F %T')" >> /data/apxinf/serve_gear/val_spatial_t4_pool.log
