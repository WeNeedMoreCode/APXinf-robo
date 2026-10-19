#!/bin/bash
# ab_catgu_1019.sh — GEB_FI8_CATGU A/B golden 对拍（双臂 tl160 桶，L=154）
# base = 新二进制无 CATGU；catgu = GEB_FI8_CATGU=1 烤的 flow OM。
# 判据：① BIASE...BISECT vs torch（catgu 只动 MLP → kvk_l0 应与 base 同；
# 深层/actions 允许小带漂）② dump 互差（cmp_range_1016.py base vs catgu）
# ③ [e2e] replay flow 计时（量化流水省流的直接读数）
set -e
G=/data/apxinf/golden/frame0_t4v1b.safetensors
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
# ⚠ catgu 臂 run 时也要 GEB_FI8_CATGU=1：池模式 = 进程内建图（binds/
# 名字）+ OM 换柄——建图 env 必须与烤制一致（307≠289 断言即此坑）
[ $# -gt 0 ] || set -- base catgu
for arm in "$@"; do
  EXTRA=""
  case "$arm" in
    catgu) EXTRA="GEB_FI8_CATGU=1" ;;
    catgu2) EXTRA="GEB_FI8_CATGU=2" ;;
  esac
  DD=/data/apxinf/golden/dump_ab_${arm}
  mkdir -p "$DD"; rm -f "$DD"/*.f16
  env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
    $EXTRA \
    ASCEND_RT_VISIBLE_DEVICES=5 \
    GEB_SEG=e2e GEB_E2E_GOLDEN=$G GEB_TOKENS=160 GEB_E2E_PAD_TOKENS=154 \
    GEB_OM_DIR=/data/apxinf/om_cache/ab_catgu/$arm/tl160_i8 \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_ATTN_MASK=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
    GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors \
    GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors \
    GEB_E2E_DUMP_MID=$DD "$BIN" > /data/apxinf/golden/ab_catgu_${arm}.log 2>&1
  echo "[ab-catgu] $arm rc=$? $(date -u +%T)"
done
echo "[ab-catgu] ALL DONE $(date -u '+%F %T')"
