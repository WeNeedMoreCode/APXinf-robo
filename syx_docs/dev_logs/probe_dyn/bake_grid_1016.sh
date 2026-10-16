#!/bin/bash
# bake_grid_1016.sh — range padding 网格桶烤制（GEB_ATTN_MASK=1，2026-10-16）
# 用法: bake_grid_1016.sh [P ...]   默认九桶 136..200 stride 8
# chip5 串行单进程（共享主机纪律）；每桶 prefix ~2.2min + flow ~1min
# 桶语义：GEB_TOKENS=P 是桶界（语言 token 含 pad 到 P）；真 L 由 serve/probe
# 侧 pad + mask 表达。tl{P}_i8 命名与池约定一致（prefix/flow 池直读）
set -e
exec > /data/apxinf/golden/bake_grid_driver.log 2>&1
OM=/data/apxinf/om_cache
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
FUS="GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json"
[ $# -gt 0 ] || set -- 136 144 152 160 168 176 184 192 200
for P in "$@"; do
  d=$OM/grid8/tl${P}_i8
  mkdir -p "$d"
  [ -f "$d/vision_real.om" ] || cp $OM/t712fix/vision_real.om "$d/"
  if [ ! -f "$d/prefix_real.om" ]; then
    echo "[grid] bake prefix P=$P start $(date -u +%T)"
    env "$FUS" ASCEND_RT_VISIBLE_DEVICES=5 \
      GEB_SEG=prefix GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
      GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_ATTN_MASK=1 \
      GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$P GEB_CKPT=$CKPT \
      GEB_SAVE=$d/prefix_real.om "$BIN" > /data/apxinf/golden/bake_grid_pfx_$P.log 2>&1
    echo "[grid] bake prefix P=$P rc=$? $(date -u +%T)"
  fi
  if [ ! -f "$d/flow_real.om" ]; then
    echo "[grid] bake flow P=$P start $(date -u +%T)"
    env "$FUS" ASCEND_RT_VISIBLE_DEVICES=5 \
      GEB_SEG=flow GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
      GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_ATTN_MASK=1 \
      GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$P GEB_CKPT=$CKPT \
      GEB_SAVE=$d/flow_real.om "$BIN" > /data/apxinf/golden/bake_grid_flw_$P.log 2>&1
    echo "[grid] bake flow P=$P rc=$? $(date -u +%T)"
  fi
  echo "[grid] P=$P done $(date -u +%T)"
done
echo "[grid] ALL DONE $(date -u '+%F %T')"
