#!/bin/bash
# libero_object 全量（prefix+flow int8 终版）：逐任务断点续跑（spatial 配方）
# —— task0 已单独完成（eval_fi8c_t0.jsonl），本脚本跑 1-9 后合并出终 summary。
# 桶状态：tl138-148_i8 全部 int8（prefix v2 + flow gud 子集）已烤好，
# 冷桶等待风险已消除（首轮 task0 曾因 L 漂移 138 冷烤 3min 撞 timeout 1500
# 被杀——取证 2026-09-30）。
cd /data/apxinf
BASE=/data/apxinf/serve
for T in 1 2 3 4 5 6 7 8 9; do
  echo "=== task $T start $(date)" >> /tmp/object_fi8.log
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=7 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=/data/apxinf/serve_i8 \
  timeout 1800 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite libero_object --tasks "$T" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_fi8c_t$T.jsonl \
    --summary-json $BASE/eval_fi8c_t${T}_summary.json \
    >> /tmp/object_fi8.log 2>&1
  echo "=== task $T rc=$? $(date)" >> /tmp/object_fi8.log
done
cat $BASE/eval_fi8c_t[0-9].jsonl > $BASE/eval_fi8c_all.jsonl 2>/dev/null
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=7 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=/data/apxinf/serve_i8 \
timeout 300 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_object --tasks all --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl $BASE/eval_fi8c_all.jsonl \
  --summary-json $BASE/eval_fi8c_all_summary.json \
  >> /tmp/object_fi8.log 2>&1
echo "=== FINAL rc=$? $(date)" >> /tmp/object_fi8.log
cat $BASE/eval_fi8c_all_summary.json >> /tmp/object_fi8.log 2>&1
echo ALL_FI8_DONE >> /tmp/object_fi8.log
