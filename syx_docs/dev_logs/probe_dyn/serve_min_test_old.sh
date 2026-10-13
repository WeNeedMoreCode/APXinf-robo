#!/bin/bash
# serve_min_test_1013.sh — chip4 零物化骨架 serve-min 测试 serve（计时+bit 对拍；验证后杀）
exec > /data/apxinf/serve_min_test.log 2>&1
BIN=/data/apxinf/ge_model_probe_old
CKPT=/data/apxinf/weights/pi05_libero_finetuned
OM=/data/apxinf/om_cache
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
LLIST="133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,200"
DYN=$OM/tl_dyn
spool=/data/apxinf/serve_gear_test/chip${CHIP:-4}
mkdir -p "$spool"
rm -f "$spool"/pid "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.req_*.tmp "$spool"/.resp_*.tmp "$spool/ready"
date -u +%T
env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 GEB_CKPT_SERVE_MIN=1 GEB_SM_ZSCOPE=${ZSCOPE:-} \
  "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
  ASCEND_RT_VISIBLE_DEVICES=${CHIP:-4} \
  GEB_SEG=e2e GEB_E2E_SERVE=$spool GEB_TOKENS=200 GEB_DYN_LLIST=$LLIST GEB_OM_DIR=$DYN \
  GEB_FLOW_POOL=$OM \
  GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
  GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
  GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
  GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
  "$BIN" > "$spool/stdout.log" 2>&1 &
echo $! > "$spool/pid"
echo "spawned pid $(cat $spool/pid)"
