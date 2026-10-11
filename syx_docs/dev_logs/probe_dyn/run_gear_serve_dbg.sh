#!/bin/bash
# run_gear_serve_dbg.sh — 手动前台抓一只 gear serve 全程日志（chip0，日志
# /tmp/gear_serve_dbg2.log——supervisor 的 respawn 会覆盖 stdout.log，排障
# 用独立文件）
source /data/apxinf/rust_env.sh
p=$(pgrep -f "E2E_SERVE=/data/apxinf/serve_gear/chip0" | head -1)
[ -n "$p" ] && kill "$p" && sleep 2
rm -f /data/apxinf/serve_gear/chip0/shutdown
env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 \
  GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json \
  ASCEND_RT_VISIBLE_DEVICES=0 \
  GEB_SEG=e2e GEB_E2E_SERVE=/data/apxinf/serve_gear/chip0 \
  GEB_TOKENS=200 \
  GEB_DYN_LLIST=137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,200 \
  GEB_OM_DIR=/data/apxinf/om_cache/tl_dyn \
  GEB_FLOW_POOL=/data/apxinf/om_cache \
  GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
  GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
  GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors \
  GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors \
  /data/apxinf/apxinf_engine/target/release/examples/ge_model_probe > /tmp/gear_serve_dbg2.log 2>&1
