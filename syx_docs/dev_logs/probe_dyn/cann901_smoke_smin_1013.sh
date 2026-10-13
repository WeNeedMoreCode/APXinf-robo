#!/bin/bash
# cann901_smoke_smin_1013.sh — inproc serve-min 冒烟（GEB_CKPT_SERVE_MIN=1 经 PyO3 open）
# 与 cann901_full_smoke.sh 同 env，仅加 SERVE_MIN —— 测 open 冷启动降幅
export ASCEND_AICPU_PATH=/data/apxinf/cann901_full
export ASCEND_HOME_PATH=/data/apxinf/cann901_full
export ASCEND_OPP_PATH=/data/apxinf/cann901_full/opp
export ASCEND_TOOLKIT_HOME=/data/apxinf/cann901_full
export TOOLCHAIN_HOME=/data/apxinf/cann901_full/toolkit
export LD_PRELOAD=/data/apxinf/cann901_full/lib64/libgraph.so:/data/apxinf/cann901_full/lib64/libge_common.so:/data/apxinf/cann901_full/lib64/libge_runner.so:/data/apxinf/cann901_full/lib64/libge_compiler.so
export LD_LIBRARY_PATH=/data/apxinf/cann901_full/lib64:/data/apxinf/cann901_full/lib64/plugin/opskernel:/data/apxinf/cann901_full/lib64/plugin/nnengine:/data/apxinf/cann901_full/opp/built-in/op_impl/ai_core/tbe/op_tiling:/data/apxinf/ascendc/ge_builder:/usr/local/Ascend/driver/lib64:/usr/local/Ascend/driver/lib64/common:/usr/local/Ascend/driver/lib64/driver
export PYTHONPATH=/data/apxinf/engine_py/apxinf:/data/apxinf/cann901_full/python/site-packages:/data/apxinf/cann901_full/opp/built-in/op_impl/ai_core/tbe
export PATH=/data/apxinf/cann901_full/bin:/data/apxinf/cann901_full/tools/ccec_compiler/bin:$PATH
export ASCEND_RT_VISIBLE_DEVICES=5
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
export GEB_PREFIX_INT8=1
export GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
export GEB_FLOW_INT8=1
export GEB_FLOW_PROJS=gate,up,down
export GEB_FLOW_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
export GEB_CKPT_SERVE_MIN=1
date -u +%T
cd /data/apxinf
python3 /data/apxinf/cann901/inproc_smoke.py
echo "SMOKE_RC=$?"
date -u +%T
