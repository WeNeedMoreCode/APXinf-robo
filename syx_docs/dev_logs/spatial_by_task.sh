#!/bin/bash
# libero_spatial 逐任务断点续跑 v2：每任务独立进程 + 独立 ledger（cli 的
# scope 校验拒绝跨任务条目——v1 循环死因），跑完合并 + --tasks all 生成
# 终 summary（resumable 跳过已完成，不重跑 episode）。
cd /data/apxinf
BASE=/data/apxinf/serve
for T in 1 2 3 4 5 6 7 8 9; do
  echo "=== task $T start $(date)" >> /tmp/spatial_by_task2.log
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=7 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=/data/apxinf/serve_f16iso \
  timeout 900 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite libero_spatial --tasks "$T" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_spatial_t$T.jsonl \
    --summary-json $BASE/eval_spatial_t${T}_summary.json \
    >> /tmp/spatial_by_task2.log 2>&1
  echo "=== task $T rc=$? $(date)" >> /tmp/spatial_by_task2.log
done
# 合并 + 终 summary（--tasks all 读到 10 条已完成 → 只写 summary）
cat $BASE/eval_spatial_f16.jsonl $BASE/eval_spatial_t[1-9].jsonl > $BASE/eval_spatial_all.jsonl 2>/dev/null
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=7 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=/data/apxinf/serve_f16iso \
timeout 300 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_spatial --tasks all --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl $BASE/eval_spatial_all.jsonl \
  --summary-json $BASE/eval_spatial_all_summary.json \
  >> /tmp/spatial_by_task2.log 2>&1
echo "=== FINAL rc=$? $(date)" >> /tmp/spatial_by_task2.log
cat $BASE/eval_spatial_all_summary.json >> /tmp/spatial_by_task2.log 2>&1
echo ALL_V2_DONE >> /tmp/spatial_by_task2.log
