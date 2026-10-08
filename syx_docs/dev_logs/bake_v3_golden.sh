#!/bin/bash
# bake_v3_golden.sh — 校准 v3 因子 OM 三件套 + e2e golden 数值门（tl200 语义）。
# 前置：int8_factors_v3_sweep.py 已产出 smooth_calib_v3{,_flow}.npz +
# convert 已产出 *_engine.safetensors。apxinf_rust 容器内跑；chip 由调用方给。
# 用法：bash bake_v3_golden.sh <chip>
set -e
CHIP=${1:-3}
CKPT=/data/apxinf/weights/pi05_libero_finetuned
D=/data/apxinf/om_cache/probe_v3
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
GOLD=/data/apxinf/golden/frame0_v3b.safetensors
source /data/apxinf/rust_env.sh
export LD_LIBRARY_PATH=/data/apxinf/apxinf_engine/crates/apxinf-ascend/ascendc/ge_builder:$LD_LIBRARY_PATH
export PYTHONPATH=/usr/local/Ascend/python/site-packages:$PYTHONPATH
export ASCEND_RT_VISIBLE_DEVICES=$CHIP
mkdir -p $D
[ -f $D/vision_real.om ] || cp /data/apxinf/om_cache/tl200/vision_real.om $D/
FUS="GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json"
COMMON="GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=200 GEB_CKPT=$CKPT"

echo "== bake prefix v3 int8 =="
env $FUS GEB_SEG=prefix GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 $COMMON GEB_SAVE=$D/prefix_real.om $BIN 2>&1 | tail -3
echo "== bake flow v3 int8 (gud subset) =="
env $FUS GEB_SEG=flow GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 $COMMON GEB_SAVE=$D/flow_real.om $BIN 2>&1 | tail -3
ls -la $D/
echo "== e2e golden parity（actions 数值门；v2 基线 10.1% prefix-only / ~10% +flow-int8）=="
env $FUS GEB_SEG=e2e GEB_OM_DIR=$D GEB_E2E_GOLDEN=$GOLD \
  GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
  GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
  $COMMON $BIN 2>&1 | grep -E "GOLDEN PARITY|e2e\]|kvk|step0" | head -20
echo V3_GOLDEN_DONE
