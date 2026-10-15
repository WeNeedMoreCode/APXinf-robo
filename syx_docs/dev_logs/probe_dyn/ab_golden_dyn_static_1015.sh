#!/bin/bash
# ab_golden_dyn_static_1015.sh — I10 后续·回退桶根因：动态 OM vs 静态 OM 各自 vs
# torch golden（L=200 真帧 frame0_v3b，含 18 层 kvk 逐层对拍 + 段边界中间量）。
# 同芯背靠背直调（chip5 已清空），环境与生产 serve 完全同款。
source /data/apxinf/rust_env.sh
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
G=/data/apxinf/golden/frame0_v3b.safetensors
LLIST=133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,200

run() { # run <tag> <om_dir> [extra env...]
  local tag=$1 omdir=$2; shift 2
  echo "===== $tag ====="
  env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
    ASCEND_RT_VISIBLE_DEVICES=5 \
    GEB_SEG=e2e GEB_E2E_GOLDEN=$G GEB_TOKENS=200 \
    GEB_OM_DIR=$omdir GEB_FLOW_POOL=/data/apxinf/om_cache \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
    GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
    GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
    "$@" "$BIN" 2>&1 | grep -iE "golden|parity|kvk|mid|bisect|max_diff|rel=|prefix|vision|step0|actions" | head -50
}

run STATIC_tl200 /data/apxinf/om_cache/tl200_i8
run DYN_tl200 /data/apxinf/om_cache/tl_dyn GEB_DYN_LLIST=$LLIST
echo "AB_DONE $(date -u +%T)"
