#!/bin/bash
# eval_goal_v3_all.sh — libero_goal 新任务集泛化验收（goal ③ 行为面）。
# 生产根 /data/apxinf/serve（v3 int8 位运行中，npu_ge.py 默认根）。
# 前置：sweep_v3_goal.json 判 transfer 成立（object 因子直接用，无需重烤）。
# goal 谱系 task0 实测 L=200（截断支，桶已在）；新 L 由 lazy-bake 兜底。
cd /data/apxinf
BASE=/data/apxinf/serve
run_one() {
  T=$1
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=2 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=$BASE \
  timeout 1800 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite libero_goal --tasks "$T" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_goal_t$T.jsonl \
    --summary-json $BASE/eval_goal_t${T}_summary.json \
    >> $BASE/eval_goal_v3_all.log 2>&1
  echo "=== task $T rc=$? $(date -u +%T)" >> $BASE/eval_goal_v3_all.log
}
for T in 0 1 2 3 4 5 6 7 8 9; do
  run_one "$T"
done
cat $BASE/eval_goal_t[0-9].jsonl > $BASE/eval_goal_all.jsonl 2>/dev/null
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=2 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=$BASE \
timeout 600 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_goal --tasks all --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl $BASE/eval_goal_all.jsonl \
  --summary-json $BASE/eval_goal_all_summary.json \
  >> $BASE/eval_goal_v3_all.log 2>&1
echo "FINAL_RC=$?" >> $BASE/eval_goal_v3_all.log
cat $BASE/eval_goal_all_summary.json >> $BASE/eval_goal_v3_all.log 2>&1
echo GOAL_V3_EVAL_DONE >> $BASE/eval_goal_v3_all.log
