#!/bin/bash
# cann901_eval_inproc.sh — eval 全链 inproc 验证（gear + cpu 预处理 + 9.0.1）
F=/data/apxinf/cann901_full
export ASCEND_AICPU_PATH=$F
export ASCEND_HOME_PATH=$F
export ASCEND_OPP_PATH=$F/opp
export ASCEND_TOOLKIT_HOME=$F
export TOOLCHAIN_HOME=$F/toolkit
export LD_PRELOAD=$F/lib64/libgraph.so:$F/lib64/libge_common.so:$F/lib64/libge_runner.so:$F/lib64/libge_compiler.so
export LD_LIBRARY_PATH=$F/lib64:$F/lib64/plugin/opskernel:$F/lib64/plugin/nnengine:$F/opp/built-in/op_impl/ai_core/tbe/op_tiling:/data/apxinf/ascendc/ge_builder:/usr/local/Ascend/driver/lib64:/usr/local/Ascend/driver/lib64/common:/usr/local/Ascend/driver/lib64/driver
export APXINF_GE_TRANSPORT=inproc
export APXINF_LEROBOT_DEVICE=cpu
export APXINF_GE_SERVE_ROOT=/data/apxinf/serve_gear
export ASCEND_RT_VISIBLE_DEVICES=4
export GEB_SEG=e2e
export GEB_TOKENS=200
export GEB_DYN_LLIST=133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,200
export GEB_OM_DIR=/data/apxinf/om_cache/tl_dyn
export GEB_FLOW_POOL=/data/apxinf/om_cache
export GEB_ATTN=manual
export GEB_QKV3=1
export GEB_ROPEFLAT=1
export GEB_WCONST=1
export GEB_PREFIX_DROP_EMPTY=256
export GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned
export GEB_CKPT_SERVE_MIN=1
export GEB_PREFIX_INT8=1
export GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
export GEB_FLOW_INT8=1
export GEB_FLOW_PROJS=gate,up,down
export GEB_FLOW_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
export PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$F/python/site-packages:$F/opp/built-in/op_impl/ai_core/tbe
export MUJOCO_GL=egl
cd /data/apxinf
timeout 1800 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_object --tasks 0 --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl /data/apxinf/serve_gear/eval_inproc_t0.jsonl \
  --summary-json /data/apxinf/serve_gear/eval_inproc_t0_summary.json
echo "=== inproc eval rc=$? $(date -u +%T)"
