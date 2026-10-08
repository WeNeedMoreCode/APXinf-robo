#!/bin/bash
# eval_v3_all.sh — 校准 v3 行为梯全量（tasks 1-9 逐任务独立进程 + 合并终
# summary；task0 已单独通过）。serve_i8 v3 位（prefix v3 + flow int8 v3）。
cd /data/apxinf
BASE=/data/apxinf/serve_i8
run_one() {
  T=$1
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=3 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=$BASE \
  timeout 1800 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite libero_object --tasks "$T" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_v3_t$T.jsonl \
    --summary-json $BASE/eval_v3_t${T}_summary.json \
    >> $BASE/eval_v3_all.log 2>&1
  echo "=== task $T rc=$? $(date +%T)" >> $BASE/eval_v3_all.log
}
for T in 1 2 3 4 5 6 7 8 9; do
  run_one "$T"
done
# 合并 task0-9 → 终 summary
cat $BASE/eval_v3_t[0-9].jsonl > $BASE/eval_v3_all.jsonl 2>/dev/null
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=3 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=$BASE \
timeout 600 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_object --tasks all --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl $BASE/eval_v3_all.jsonl \
  --summary-json $BASE/eval_v3_all_summary.json \
  >> $BASE/eval_v3_all.log 2>&1
echo "FINAL_RC=$? $(date +%T)" >> $BASE/eval_v3_all.log
cat $BASE/eval_v3_all_summary.json >> $BASE/eval_v3_all.log 2>&1
echo ALL_V3_DONE >> $BASE/eval_v3_all.log
