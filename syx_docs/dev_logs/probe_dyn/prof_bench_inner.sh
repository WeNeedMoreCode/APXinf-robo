#!/bin/bash
# prof_bench_inner.sh — msprof 被测程序：gear 生产 env 的 e2e bench（最小迭代 12）
# 与生产 serve spawn env 同款（抄 serve_gear_supervisor.sh spawn_chip），仅以
# GEB_E2E_BENCH=12 替代 GEB_E2E_SERVE（spool 服务模式 → 直调循环模式）。
# 跑在 apxinf_rust 容器内空芯（ASCEND_RT_VISIBLE_DEVICES=4；芯 0-3=生产 gear、
# 6/7=回退桶）。输出三段计时行到 stdout。
env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
  ASCEND_RT_VISIBLE_DEVICES=4 \
  GEB_SEG=e2e GEB_TOKENS=200 \
  GEB_DYN_LLIST=133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,200 \
  GEB_OM_DIR=/data/apxinf/om_cache/tl_dyn \
  GEB_FLOW_POOL=/data/apxinf/om_cache \
  GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
  GEB_PREFIX_DROP_EMPTY=256 \
  GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
  GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors \
  GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down \
  GEB_FLOW_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors \
  GEB_E2E_BENCH=12 \
  /data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
