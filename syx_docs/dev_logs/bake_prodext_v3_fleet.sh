#!/bin/bash
# bake_prodext_v3_fleet.sh — 生产谱系扩展桶 v3 烤制（2026-10-09 生产化切换轮）：
#   tl149-156_i8 ×8（spatial 谱系，新建）+ tl200_i8 ×1（v2/f16 → v3 重烤）
# 配置 = bake_v3_fleet.sh 同款（prefix v3 + flow int8 v3 gud）；
# chips 0-3 四路并行（每芯同时 1 作业），vision 拷 t712fix。
# 前置：chips 0-3 空闲（生产 serve 在 6/4/7/5）。
set -u
source /data/apxinf/rust_env.sh
export LD_LIBRARY_PATH=/data/apxinf/apxinf_engine/crates/apxinf-ascend/ascendc/ge_builder:$LD_LIBRARY_PATH
export PYTHONPATH=/usr/local/Ascend/python/site-packages:$PYTHONPATH
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
FUS="GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json"
LS="149 150 151 152 153 154 155 156 200"

bake_one() {
  local L=$1 c=$2 d=/data/apxinf/om_cache/tl${L}_i8 rc=0
  mkdir -p "$d"
  [ -f "$d/vision_real.om" ] || cp /data/apxinf/om_cache/t712fix/vision_real.om "$d/vision_real.om"
  env $FUS ASCEND_RT_VISIBLE_DEVICES=$c \
    GEB_SEG=prefix GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$L GEB_CKPT=$CKPT \
    GEB_SAVE=$d/prefix_real.om "$BIN" > /tmp/bake_pe_p$L.log 2>&1 || rc=$?
  if [ $rc -ne 0 ]; then echo "L$L prefix FAIL rc=$rc"; return 1; fi
  env $FUS ASCEND_RT_VISIBLE_DEVICES=$c \
    GEB_SEG=flow GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$L GEB_CKPT=$CKPT \
    GEB_SAVE=$d/flow_real.om "$BIN" > /tmp/bake_pe_f$L.log 2>&1 || rc=$?
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
echo "FLEET_PRODEXT_DONE $(date +%T)"
for L in $LS; do stat -c "%y %s %n" /data/apxinf/om_cache/tl${L}_i8/prefix_real.om /data/apxinf/om_cache/tl${L}_i8/flow_real.om 2>/dev/null; done
