#!/bin/bash
# eval_v3_t0.sh — 校准 v3 行为梯 task0（serve_i8 v3 位：prefix v3 + flow int8 v3）
# apxinf_npu 容器内 docker exec -d 跑（脚本文件形态——内联进程随断连死）。
cd /data/apxinf
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=3 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=/data/apxinf/serve_i8 \
timeout 1800 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_object --tasks 0 --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl /data/apxinf/serve_i8/eval_v3_t0.jsonl \
  --summary-json /data/apxinf/serve_i8/eval_v3_t0_summary.json \
  > /data/apxinf/serve_i8/eval_v3_t0.log 2>&1
echo "T0_RC=$? $(date +%T)" >> /data/apxinf/serve_i8/eval_v3_t0.log
