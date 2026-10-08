#!/bin/bash
# bake_v3_fleet.sh — serve_i8 全谱系桶 v3 重烤（prefix v3 + flow int8 v3 gud）。
# tl138-148_i8 × {prefix,flow}，chips 0-3 四路并行（每芯同时仅 1 作业——
# prefix 大 OM 装载需干净芯片，rc=-8 纪律）。vision OM 复用桶内现有。
# 前置：旧 supervisor/serve 已停（本脚本不负责杀）。
set -u
source /data/apxinf/rust_env.sh
export LD_LIBRARY_PATH=/data/apxinf/apxinf_engine/crates/apxinf-ascend/ascendc/ge_builder:$LD_LIBRARY_PATH
export PYTHONPATH=/usr/local/Ascend/python/site-packages:$PYTHONPATH
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
FUS="GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json"
LS="138 139 140 141 142 143 144 145 146 147 148"

bake_one() {
  local L=$1 c=$2 d=/data/apxinf/om_cache/tl${L}_i8 rc=0
  mkdir -p "$d"
  env $FUS ASCEND_RT_VISIBLE_DEVICES=$c \
    GEB_SEG=prefix GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$L GEB_CKPT=$CKPT \
    GEB_SAVE=$d/prefix_real.om "$BIN" > /tmp/bake_v3_p$L.log 2>&1 || rc=$?
  if [ $rc -ne 0 ]; then echo "L$L prefix FAIL rc=$rc"; return 1; fi
  env $FUS ASCEND_RT_VISIBLE_DEVICES=$c \
    GEB_SEG=flow GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$L GEB_CKPT=$CKPT \
    GEB_SAVE=$d/flow_real.om "$BIN" > /tmp/bake_v3_f$L.log 2>&1 || rc=$?
  if [ $rc -ne 0 ]; then echo "L$L flow FAIL rc=$rc"; return 1; fi
  echo "L$L OK (chip$c) $(date +%T)"
}
export -f bake_one 2>/dev/null || true

ci=0
for L in $LS; do
  c=$((ci % 4))
  bake_one "$L" "$c" &
  ci=$((ci + 1))
  if [ $((ci % 4)) -eq 0 ]; then wait; fi
done
wait
echo "FLEET_V3_DONE $(date +%T)"
ls -la /data/apxinf/om_cache/tl14?_i8/prefix_real.om | wc -l
