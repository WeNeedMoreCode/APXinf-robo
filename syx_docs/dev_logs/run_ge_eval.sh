#!/bin/bash
# GEB_E2E_SERVE 闭环 eval（apxinf_npu 跑 torch 前处理 + env；引擎 serve 在
# apxinf_rust）。用法：run_ge_eval.sh <tasks> [tag]
TASKS=${1:?tasks 比如 0 或 all}
TAG=${2:-t${TASKS}}
cd /data/apxinf
export MUJOCO_GL=egl
export ASCEND_RT_VISIBLE_DEVICES=${GE_EVAL_CHIP:-7}
export PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH
python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_object --tasks "$TASKS" --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl /data/apxinf/serve/eval_${TAG}.jsonl \
  --summary-json /data/apxinf/serve/eval_${TAG}_summary.json
