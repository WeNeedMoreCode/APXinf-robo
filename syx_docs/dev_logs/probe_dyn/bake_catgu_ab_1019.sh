#!/bin/bash
# bake_catgu_ab_1019.sh — GEB_FI8_CATGU（gate/up 拼接一发 qmd）A/B 烤制
# 双臂同新二进制烤 flow OM @ tl160（base = 不设 CATGU；catgu = 设 1），
# prefix/vision 复用 grid8/tl160_i8（catgu 只动 flow MLP）。
# chip5 串行（共享主机纪律）；每臂 ~1min。产出后跑 ab 两轮 golden 对拍。
set -e
exec > /data/apxinf/golden/bake_catgu_ab.log 2>&1
# 用法: bake_catgu_ab_1019.sh <arm> ...（base | catgu | catgu2）
OM=/data/apxinf/om_cache
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
FUS="GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json"
for arm in "$@"; do
  d=$OM/ab_catgu/$arm/tl160_i8
  mkdir -p "$d"
  cp $OM/grid8/tl160_i8/vision_real.om $OM/grid8/tl160_i8/prefix_real.om "$d/"
  if [ ! -f "$d/flow_real.om" ]; then
    echo "[catgu-ab] bake $arm flow start $(date -u +%T)"
    EXTRA=""
    case "$arm" in
      catgu) EXTRA="GEB_FI8_CATGU=1" ;;
      catgu2) EXTRA="GEB_FI8_CATGU=2" ;;
    esac
    env "$FUS" ASCEND_RT_VISIBLE_DEVICES=5 $EXTRA \
      GEB_SEG=flow GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
      GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_ATTN_MASK=1 \
      GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=160 GEB_CKPT=$CKPT \
      GEB_SAVE=$d/flow_real.om "$BIN" > /data/apxinf/golden/bake_catgu_${arm}.log 2>&1
    echo "[catgu-ab] bake $arm flow rc=$? $(date -u +%T)"
  fi
done
echo "[catgu-ab] ALL DONE $(date -u '+%F %T')"
