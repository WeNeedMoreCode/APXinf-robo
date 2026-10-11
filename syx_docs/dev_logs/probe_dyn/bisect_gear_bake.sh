#!/bin/bash
# bisect_gear_bake.sh — prefix gear 烤编译 rc=-7 三变量微分离（depth2 快烤）
# 用法：bisect_gear_bake.sh <tag> [GEB_SM_DYN] [GEB_G_DYN] [GEB_BIAS_REG]
source /data/apxinf/rust_env.sh
TAG=$1; SM=${2:-0}; GD=${3:-0}; BR=${4:-0}
echo "== variant $TAG SM=$SM GD=$GD BR=$BR $(date +%T)"
env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
  ASCEND_RT_VISIBLE_DEVICES=1 \
  GEB_SEG=prefix GEB_PREFIX_INT8=1 \
  GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors \
  GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
  GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=200 \
  GEB_DYN_LLIST=137,138,150,200 \
  GEB_DEPTH_PREFIX=2 \
  GEB_SM_DYN=$SM GEB_G_DYN=$GD GEB_BIAS_REG=$BR \
  GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
  GEB_SAVE=/tmp/bisect_${TAG}.om \
  /data/apxinf/apxinf_engine/target/release/examples/ge_model_probe \
  > /tmp/bisect_${TAG}.log 2>&1
rc=$?
grep -aE "OM saved|panicked|rc=-7|PROBE_OK" /tmp/bisect_${TAG}.log | head -2
echo "== $TAG rc=$rc $(date +%T)"
