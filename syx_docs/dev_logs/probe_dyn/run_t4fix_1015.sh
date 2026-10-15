#!/bin/bash
# run_t4fix_1015.sh — T4R ①补：剥 pad 重放（apxinf_npu 容器，chip 5）
cd /data/apxinf/golden
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=5 HF_ENDPOINT=https://hf-mirror.com \
PYTHONPATH=/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  python3 /data/apxinf/golden/golden_fix_t4_1015.py \
  > /data/apxinf/golden/t4fix.log 2>&1
echo "RC=$? $(date -u '+%F %T')" >> /data/apxinf/golden/t4fix.log
