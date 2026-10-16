#!/bin/bash
# ab_range_1016.sh — range padding 桶版 vs torch golden 对拍（L=154 → 桶 160）
# 桶版 = grid8/tl160_i8（GEB_ATTN_MASK=1 烤）；日志内 BISECT = vs torch
#（cmp_mid 截断比前 666 行 = 真行）；离线互差对照 dump_static_t4 走
# cmp_range_1016.py。判据：l0 ≈ 0.9%（static 档位）= mask 数学精确实证
set -e
G=/data/apxinf/golden/frame0_t4v1b.safetensors
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
DD=/data/apxinf/golden/dump_range160
mkdir -p "$DD"; rm -f "$DD"/*.f16
env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
  ASCEND_RT_VISIBLE_DEVICES=5 \
  GEB_SEG=e2e GEB_E2E_GOLDEN=$G GEB_TOKENS=160 GEB_E2E_PAD_TOKENS=154 \
  GEB_OM_DIR=/data/apxinf/om_cache/grid8/tl160_i8 \
  GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_ATTN_MASK=1 \
  GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
  GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors \
  GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors \
  GEB_E2E_DUMP_MID=$DD "$BIN" > /data/apxinf/golden/ab_range160.log 2>&1
echo "RANGE_AB_DONE rc=$? $(date -u +%T)"
