#!/bin/bash
# eval_gear_all.sh — 动态分档（dynamic gear）拓扑三谱系行为验收。
# gear 根 /data/apxinf/serve_gear（每芯一只全档 serve，supervisor =
# /data/apxinf/serve_gear_supervisor.sh）。客户端 npu_ge.py 检测 gear_mode
# 标记 → _GearClient 芯轮询（L 走 payload，serve 按档选发）。
# 用法：eval_gear_all.sh [smoke|object|spatial|goal|all]
#   smoke = object task0 单任务（首验：档分发 + 行为不回归）
cd /data/apxinf
BASE=/data/apxinf/serve_gear
MODE=${1:-smoke}
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
    --results-jsonl $BASE/eval_${SUITE}_gear.jsonl \
    --summary-json $BASE/eval_${SUITE}_gear_summary.json \
    >> $BASE/eval_gear_all.log 2>&1
  echo "=== $SUITE rc=$? $(date -u +%T)" >> $BASE/eval_gear_all.log
  tail -3 $BASE/eval_${SUITE}_gear_summary.json 2>/dev/null
}
case $MODE in
  smoke)   run_suite libero_object 0 ;;
  object)  run_suite libero_object all ;;
  spatial) run_suite libero_spatial all ;;
  goal)    run_suite libero_goal all ;;
  all)
    run_suite libero_object all
    run_suite libero_spatial all
    run_suite libero_goal all
    ;;
  *) echo "usage: $0 [smoke|object|spatial|goal|all]"; exit 1 ;;
esac
