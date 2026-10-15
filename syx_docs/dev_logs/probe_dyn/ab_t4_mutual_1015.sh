#!/bin/bash
# ab_t4_mutual_1015.sh — T4R ②：t4 真帧 golden 下 static/dyn 背靠背三连
#   run1 static vs torch（dump kv/actions 出来）
#   run2 dyn    vs torch（漂移参照——与 static 剖面比形态）
#   run3 dyn    vs static-合并-golden（cmp_mid = 逐层 dyn-vs-static 互差，
#               GOLDEN PARITY = actions 级互差）
# 契约（2026-10-15 踩坑修正）：
#   static：不带 GEB_DYN_LLIST/GEB_FLOW_POOL——flow 从 GEB_OM_DIR/flow_real.om
#           直载；带了 llist 会走 run_gear 对静态 OM 调 SetInputDynamicDims（rc=-2）
#   dyn   ：GEB_DYN_LLIST=$TOKENS（单值档表，SetInputDynamicDims 按 dims 值匹配
#           烤好的 154 档）+ GEB_FLOW_POOL（flow 池按 llist 装 tl154_i8 一只）
# chip5 空卡顺序跑（同芯同时代）；probe 直调不碰生产 spool。
set -e
TOKENS=${TOKENS:-151}
G=/data/apxinf/golden/frame0_t4v1b.safetensors
MG=/data/apxinf/golden/frame0_t4v1b_staticgold.safetensors
DA=/data/apxinf/golden/dump_static_t4
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe

run() { # run <tag> <omdir> <dumpdir> <golden> <mode: static|dyn> [extra env...]
  local tag=$1 omdir=$2 ddir=$3 gold=$4 mode=$5; shift 5
  local poolenv=""
  if [ "$mode" = dyn ]; then
    poolenv="GEB_FLOW_POOL=/data/apxinf/om_cache GEB_DYN_LLIST=$TOKENS"
  fi
  mkdir -p "$ddir"; rm -f "$ddir"/*.f16
  docker exec apxinf_rust bash -c "
    source /data/apxinf/rust_env.sh && \
    env GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json \
    ASCEND_RT_VISIBLE_DEVICES=5 \
    GEB_SEG=e2e GEB_E2E_GOLDEN=$gold GEB_TOKENS=$TOKENS \
    GEB_OM_DIR=$omdir $poolenv \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
    GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors \
    GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down \
    GEB_FLOW_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors \
    GEB_E2E_DUMP_MID=$ddir $* \
    $BIN" \
    > "/data/apxinf/golden/ab_t4_${tag}.log" 2>&1
  echo "== $tag done rc=$? $(date -u +%T) =="
}

if [ -f "$MG" ]; then
  echo "[AB] run1 static + merge 已完成（$MG 在），跳过"
else
  echo "[AB] run1 static vs torch (dump kv/actions)"
  run static /data/apxinf/om_cache/tl154_i8 "$DA" "$G" static
  echo "[AB] merge static dumps -> staticgold"
  docker exec apxinf_npu python3 /data/apxinf/golden/mk_merged_golden_t4_1015.py "$DA" "$MG"
fi
echo "[AB] run2 dyn vs torch"
run dyn_torch /data/apxinf/om_cache/tl_dyn /data/apxinf/golden/dump_dyn_torch "$G" dyn
echo "[AB] run3 dyn vs static (merged golden = 互差)"
run dyn_static /data/apxinf/om_cache/tl_dyn /data/apxinf/golden/dump_dyn_t4 "$MG" dyn
echo "[AB] ALL DONE $(date -u '+%F %T')"
