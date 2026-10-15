#!/bin/bash
# val_spatial_t4_gear_1015.sh — 静态路径对照：spatial t4 ×5 全走静态桶（路由文件临时恢复）
# （static_fallback_llist 已摘除；当年 2026-10-12 gear 数值在此任务二连败）。
# 门限：≥4/5 过 → 回退桶永久退役（常驻单卡）；<4 → 补回退到 chip 5。
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
  --results-jsonl /data/apxinf/serve_gear/val_spatial_t4_static5.jsonl \
  --summary-json /data/apxinf/serve_gear/val_spatial_t4_static5_summary.json \
  > /data/apxinf/serve_gear/val_spatial_t4_static5.log 2>&1
echo "VAL_RC=$? $(date -u '+%F %T')" >> /data/apxinf/serve_gear/val_spatial_t4_static5.log
