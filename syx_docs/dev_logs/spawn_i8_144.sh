#!/bin/bash
# int8 隔离 spool serve（不触碰共享 serve/tl144 与 supervisor）：
# 桶根 /data/apxinf/serve_i8（eval 侧 APXINF_GE_SERVE_ROOT 指同处）。
# 用法：bash spawn_i8_144.sh [chip]
set -e
CHIP=${1:-6}
ROOT=/data/apxinf/serve_i8
OM=/data/apxinf/om_cache
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
spool=$ROOT/tl144
mkdir -p "$spool"
rm -f "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.resp_*.tmp "$spool"/.req_*.tmp \
      "$spool/ready" "$spool/shutdown" "$spool/pid"
env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 \
  "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
  ASCEND_RT_VISIBLE_DEVICES=$CHIP \
  LD_LIBRARY_PATH="/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}" \
  PYTHONPATH="/usr/local/Ascend/ascend-toolkit/latest/python/site-packages:${PYTHONPATH:-}" \
  GEB_SEG=e2e GEB_E2E_SERVE=$spool GEB_TOKENS=144 GEB_OM_DIR=$OM/tl144_i8 \
  GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
  GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
  GEB_PREFIX_INT8=1 \
  GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v2_engine.safetensors \
  nohup "$BIN" > "$spool/stdout.log" 2>&1 &
echo $! > "$spool/pid"
echo "spawned ISOLATED int8 serve: spool=$spool chip=$CHIP pid=$(cat "$spool/pid")"
