#!/bin/bash
# spot_eval_range.sh — range padding 切换后三谱系 spot 复验（与基线同任务集，
# 独立 jsonl 后缀 spot${STAMP}r——同日跳过纪律与晨间基线互不干扰）
cd /data/apxinf
BASE=/data/apxinf/serve_gear
CHIP=${CHIP:-4}
STAMP=$(date +%m%d)
ARGS=("$@")
[ $# -eq 0 ] && ARGS=(object:0 spatial:4 goal:9)
for spec in "${ARGS[@]}"; do
  SUITE="libero_${spec%%:*}"; TASKS="${spec#*:}"
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=$CHIP \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=$BASE \
  timeout 1800 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite "$SUITE" --tasks "$TASKS" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_${SUITE}_gear_spot${STAMP}r.jsonl \
    --summary-json $BASE/eval_${SUITE}_gear_spot${STAMP}r_summary.json \
    >> $BASE/spot_eval.log 2>&1
  echo "=== RANGE $SUITE tasks=$TASKS rc=$? $(date -u '+%F %T')" >> $BASE/spot_eval.log
  tail -4 $BASE/eval_${SUITE}_gear_spot${STAMP}r_summary.json 2>/dev/null
done
echo SPOT_RANGE_DONE
