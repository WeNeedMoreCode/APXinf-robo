#!/bin/bash
# spawn_fallback_bucket.sh — 手动把 v3 per-L 桶 spawn 到指定芯（chip4/5 满溢
# 场景；pid 文件入生产根 → v3 supervisor 认养：alive 则 touch ready/死后
# respawn（其芯轮换可能再撞满芯——已知限制，观察项））
# 用法：spawn_fallback_bucket.sh <L> <chip>
source /data/apxinf/rust_env.sh
L=$1; C=$2
ROOT=/data/apxinf/serve
OM=/data/apxinf/om_cache
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
SPOOL=$ROOT/tl$L
mkdir -p "$SPOOL"
rm -f "$SPOOL"/req_*.bin "$SPOOL"/resp_*.bin "$SPOOL"/.resp_*.tmp "$SPOOL"/.req_*.tmp \
      "$SPOOL/ready" "$SPOOL/shutdown"
echo "[fallback] spawn tl$L (chip$C) $(date)"
env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 GEB_PRELOAD_EARLY=1 \
  "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
  ASCEND_RT_VISIBLE_DEVICES=$C \
  GEB_SEG=e2e GEB_E2E_SERVE=$SPOOL GEB_TOKENS=$L GEB_OM_DIR=$OM/tl${L}_i8 \
  GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
  GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
  GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
  GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
  "$BIN" > "$SPOOL/stdout.log" 2>&1 &
echo $! > "$SPOOL/pid"
echo "[fallback] tl$L pid=$(cat $SPOOL/pid)"
