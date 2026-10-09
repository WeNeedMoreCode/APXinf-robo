#!/bin/bash
# eval_spatial_v3_all.sh — spatial 谱系 v3 行为梯全量（goal ③ 验收）：
# 逐任务独立进程 + 合并终 summary（ledger scope 纪律）；serve_i8 v3 位，
# tl149-156_i8 全谱系桶热（bake_prodext_v3_fleet 产物）。timeout 1800 纪律。
cd /data/apxinf
BASE=/data/apxinf/serve_i8
run_one() {
  T=$1
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=2 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=$BASE \
  timeout 1800 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite libero_spatial --tasks "$T" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_spv3_t$T.jsonl \
    --summary-json $BASE/eval_spv3_t${T}_summary.json \
    >> $BASE/eval_spv3_all.log 2>&1
  echo "=== task $T rc=$? $(date -u +%T)" >> $BASE/eval_spv3_all.log
}
for T in 0 1 2 3 4 5 6 7 8 9; do
  run_one "$T"
done
cat $BASE/eval_spv3_t[0-9].jsonl > $BASE/eval_spv3_all.jsonl 2>/dev/null
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=2 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=$BASE \
timeout 600 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_spatial --tasks all --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl $BASE/eval_spv3_all.jsonl \
  --summary-json $BASE/eval_spv3_all_summary.json \
  >> $BASE/eval_spv3_all.log 2>&1
echo "FINAL_RC=$?" >> $BASE/eval_spv3_all.log
cat $BASE/eval_spv3_all_summary.json >> $BASE/eval_spv3_all.log 2>&1
echo SPATIAL_V3_ALL_DONE >> $BASE/eval_spv3_all.log
