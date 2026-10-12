#!/bin/bash
# bake_flow_pool_edge.sh — 补烤 flow 池档表下沿 OM（tl133-136_i8；gear 表
# 扩到 133 后池缺这 4 只，装载即 panic——2026-10-12 取证）
source /data/apxinf/rust_env.sh
for spec in "133 0" "134 1" "135 2" "136 3"; do
  set -- $spec; L=$1; C=$2
  d=/data/apxinf/om_cache/tl${L}_i8
  mkdir -p "$d"
  [ -f "$d/vision_real.om" ] || cp /data/apxinf/om_cache/t712fix/vision_real.om "$d/vision_real.om"
  if [ ! -f "$d/flow_real.om" ]; then
    echo "[bake-edge] tl${L}_i8 flow (chip$C) $(date)"
    env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
      ASCEND_RT_VISIBLE_DEVICES=$C \
      GEB_SEG=flow GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down \
      GEB_FLOW_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors \
      GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 \
      GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$L GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
      GEB_SAVE=$d/flow_real.om /data/apxinf/apxinf_engine/target/release/examples/ge_model_probe \
      > /tmp/bake_edge_$L.log 2>&1 &
  fi
done
wait
echo BAKE_EDGE_ALL_DONE
