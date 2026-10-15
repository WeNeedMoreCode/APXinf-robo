#!/bin/bash
# ab_t4_mutual_1015.sh — T4R ②：t4 真帧 golden 下 static/dyn 背靠背三连
#   run1 static vs torch（dump kv/actions 出来）
#   run2 dyn    vs torch（漂移参照——与 static 剖面比形态）
#   run3 dyn    vs static-合并-golden（cmp_mid = 逐层 dyn-vs-static 互差，
#               GOLDEN PARITY = actions 级互差）
# chip5 空卡顺序跑（同芯同时代）；probe 直调不碰生产 spool。
# TOKENS 由 frame0_t4v1 实际 L 决定（t4 预期 151，跑前核对 t4gen.log）
set -e
TOKENS=${TOKENS:-151}
# llist 必须 = tl_dyn 烤桶时的完整 26 档表（桶选择按位置映射，错位 = 选错档）
LLIST=${LLIST:-133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,200}
G=/data/apxinf/golden/frame0_t4v1b.safetensors
MG=/data/apxinf/golden/frame0_t4v1b_staticgold.safetensors
DA=/data/apxinf/golden/dump_static_t4
DB=/data/apxinf/golden/dump_dyn_t4

run() { # run <tag> <omdir> <dumpdir> <golden> [extra env...]
  local tag=$1 omdir=$2 ddir=$3 gold=$4; shift 4
  mkdir -p "$ddir"; rm -f "$ddir"/*.f16
  docker exec apxinf_rust bash -c "
    source /data/apxinf/rust_env.sh && \
    GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json \
    ASCEND_RT_VISIBLE_DEVICES=5 \
    GEB_SEG=e2e GEB_E2E_GOLDEN=$gold GEB_TOKENS=$TOKENS \
    GEB_OM_DIR=$omdir GEB_FLOW_POOL=/data/apxinf/om_cache GEB_DYN_LLIST=$LLIST \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
    GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors \
    GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down \
    GEB_FLOW_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors \
    GEB_E2E_DUMP_MID=$ddir $* \
    /data/apxinf/apxinf_engine/target/release/examples/ge_model_probe" \
    > "/data/apxinf/golden/ab_t4_${tag}.log" 2>&1
  echo "== $tag done $(date -u +%T) =="
}

echo "[AB] run1 static vs torch (dump kv/actions)"
run static /data/apxinf/om_cache/tl151_i8 "$DA" "$G"
echo "[AB] merge static dumps -> staticgold"
docker exec apxinf_npu python3 /data/apxinf/golden/mk_merged_golden_t4_1015.py "$DA" "$MG"
echo "[AB] run2 dyn vs torch"
run dyn_torch /data/apxinf/om_cache/tl_dyn /data/apxinf/golden/dump_dyn_torch "$G"
echo "[AB] run3 dyn vs static (merged golden = 互差)"
run dyn_static /data/apxinf/om_cache/tl_dyn "$DB" "$MG"
echo "[AB] ALL DONE $(date -u '+%F %T')"
