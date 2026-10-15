#!/bin/bash
# spot_eval.sh — 参数化晨间 spot eval（运维例行化；spot_eval_1013.sh 的泛化版）
# 用法: bash spot_eval.sh [suite:tasks ...]   默认 = object:0 spatial:4 goal:9
#   suite 省略 libero_ 前缀（object→libero_object）；tasks 逗号分隔多任务
# 例:   bash spot_eval.sh object:0,1 spatial:4 goal:9
# 必须容器内跑: docker exec -d apxinf_npu bash /data/apxinf/spot_eval.sh
# 纪律: results-jsonl 按天戳（%m%d）——同日重跑同任务会被 resume 语义跳过
cd /data/apxinf
BASE=/data/apxinf/serve_gear
# 2026-10-15 拓扑收缩：单 gear serve 在 chip 4（空芯，与同事 vLLM 的 0-3/6-7 分开）
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
    --results-jsonl $BASE/eval_${SUITE}_gear_spot${STAMP}.jsonl \
    --summary-json $BASE/eval_${SUITE}_gear_spot${STAMP}_summary.json \
    >> $BASE/spot_eval.log 2>&1
  echo "=== $SUITE tasks=$TASKS rc=$? $(date -u '+%F %T')" >> $BASE/spot_eval.log
  tail -4 $BASE/eval_${SUITE}_gear_spot${STAMP}_summary.json 2>/dev/null
done
echo SPOT_DONE
