#!/bin/bash
# dbg_percall_1015.sh — I9 取证C：逐调用计时 1 集（验证 server_processor≈186ms
# = 首调用 NPU eager 算子编译摊平均 的假设；npu-ge 无 warmup，eval_libero 只对
# npu-torch 调 warmup）。结果文件用 dbg_ 前缀，不占 spot 当日戳。
# v2：warmup 修复后复跑——文件名换 p2（resume 语义跳已录任务）。
cd /data/apxinf
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=${CHIP:-2} \
APXINF_GE_PERCALL=1 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=/data/apxinf/serve_gear \
timeout 1800 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_object --tasks 0 --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl /data/apxinf/serve_gear/dbg_percall2_1015.jsonl \
  --summary-json /data/apxinf/serve_gear/dbg_percall2_1015_summary.json \
  > /data/apxinf/serve_gear/dbg_percall2_1015.log 2>&1
echo "DBG_RC=$? $(date -u '+%F %T')" >> /data/apxinf/serve_gear/dbg_percall2_1015.log
