#!/bin/bash
# retry_gear_failed.sh — gear 舰队失败任务重试（object t3/t7 + spatial t4；
# 环境与 eval_gear_all.sh 完全同式——tbe import 依赖 cd /data/apxinf）
cd /data/apxinf
BASE=/data/apxinf/serve_gear
run_retry() {
  SUITE=$1; TASKS=$2; TAG=$3
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=2 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=$BASE \
  timeout 1800 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite "$SUITE" --tasks "$TASKS" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_${TAG}_retry.jsonl \
    --summary-json $BASE/eval_${TAG}_retry_summary.json \
    >> $BASE/eval_retry.log 2>&1
  echo "=== retry $TAG rc=$? $(date -u +%T)" >> $BASE/eval_retry.log
}
run_retry libero_object 3,7 obj
run_retry libero_spatial 4 spatial
echo RETRY_ALL_DONE >> $BASE/eval_retry.log
