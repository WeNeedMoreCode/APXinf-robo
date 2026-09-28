#!/bin/bash
# spatial 补跑 t7/8/9（OOM 清场后——全桶已 touch shutdown 防 mini-sup 盲目
# respawn；客户端 ensure 会按需清标记拉起正确的桶）+ 合并终 summary。
cd /data/apxinf
BASE=/data/apxinf/serve
for T in 7 8 9; do
  echo "=== makeup task $T start $(date)" >> /tmp/spatial_makeup.log
  MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=7 \
  PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
  APXINF_GE_SERVE_ROOT=/data/apxinf/serve_f16iso \
  timeout 1200 python3 -m apxinf_robo.cli eval-libero \
    --backend in-process --engine npu-ge --precision fp16 \
    --suite libero_spatial --tasks "$T" --trials-per-task 1 --seed 7 \
    --replan-steps 5 \
    --model-dir /data/apxinf/weights/pi05_libero_finetuned \
    --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
    --results-jsonl $BASE/eval_spatial_t$T.jsonl \
    --summary-json $BASE/eval_spatial_t${T}_summary.json \
    >> /tmp/spatial_makeup.log 2>&1
  echo "=== makeup task $T rc=$? $(date)" >> /tmp/spatial_makeup.log
done
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
  >> /tmp/spatial_makeup.log 2>&1
echo "=== FINAL_SUMMARY rc=$? $(date)" >> /tmp/spatial_makeup.log
echo MAKEUP_DONE >> /tmp/spatial_makeup.log
