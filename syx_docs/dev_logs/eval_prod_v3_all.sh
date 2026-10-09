#!/bin/bash
# eval_prod_v3_all.sh — v3 生产化切换后的全量复验（libero_object，goal ①）。
# 生产根 /data/apxinf/serve（npu_ge.py 默认根；显式设 APXINF_GE_SERVE_ROOT
# 以防歧义）。前置：serve_supervisor_v3.sh 已启动、用户已批准切换。
# 预期 = 10/10 @ per-call ~232ms（serve_i8 隔离根同配置 2026-10-09 已验）。
cd /data/apxinf
BASE=/data/apxinf/serve
run_one() {
  T=$1
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=2 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=$BASE \
  timeout 1800 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite libero_object --tasks "$T" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_prodv3_t$T.jsonl \
    --summary-json $BASE/eval_prodv3_t${T}_summary.json \
    >> $BASE/eval_prod_v3_all.log 2>&1
  echo "=== task $T rc=$? $(date -u +%T)" >> $BASE/eval_prod_v3_all.log
}
for T in 0 1 2 3 4 5 6 7 8 9; do
  run_one "$T"
done
cat $BASE/eval_prodv3_t[0-9].jsonl > $BASE/eval_prod_v3_all.jsonl 2>/dev/null
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=2 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=$BASE \
timeout 600 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_object --tasks all --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl $BASE/eval_prod_v3_all.jsonl \
  --summary-json $BASE/eval_prod_v3_all_summary.json \
  >> $BASE/eval_prod_v3_all.log 2>&1
echo "FINAL_RC=$?" >> $BASE/eval_prod_v3_all.log
cat $BASE/eval_prod_v3_all_summary.json >> $BASE/eval_prod_v3_all.log 2>&1
echo PROD_V3_VERIFY_DONE >> $BASE/eval_prod_v3_all.log
