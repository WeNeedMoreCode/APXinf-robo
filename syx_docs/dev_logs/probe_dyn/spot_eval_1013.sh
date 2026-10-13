#!/bin/bash
# spot_eval_1013.sh — 晨间 spot eval（稳定性长跑）：object t0 + spatial t4
# （t4 走 tl151-157 静态回退——同时验证回退桶过夜状态）。新 jsonl（resume 语义）。
cd /data/apxinf
BASE=/data/apxinf/serve_gear
run_suite() { # run_suite <suite> <tasks...>
  SUITE=$1; shift
  TASKS="$*"
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=2 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=$BASE \
  timeout 1800 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite "$SUITE" --tasks "$TASKS" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_${SUITE}_gear_spot1013.jsonl \
    --summary-json $BASE/eval_${SUITE}_gear_spot1013_summary.json \
    >> $BASE/spot_eval_1013.log 2>&1
  echo "=== $SUITE rc=$? $(date -u +%T)" >> $BASE/spot_eval_1013.log
  tail -3 $BASE/eval_${SUITE}_gear_spot1013_summary.json 2>/dev/null
}
run_suite libero_object 0
run_suite libero_spatial 4
echo SPOT_DONE
