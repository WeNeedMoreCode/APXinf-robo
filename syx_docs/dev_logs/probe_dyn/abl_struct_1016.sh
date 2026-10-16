#!/bin/bash
# abl_struct_1016.sh — T4R 结构消融终裁（「怪 GE 还是怪组装」）
#   V1 GEB_ABL_BIAS=1    静态+gear 式 bias 注册（90 悬空行不注册——预期零差异=排除）
#   V2 GEB_ABL_ROPE=1    静态+qswap_c/kswap_c 转 Data（隔离 rope/qswap Data 化）
#   V4 GEB_ABL_SMCONST=1 静态+smooth 烤 Const（隔离 126 个被消费输入的注册差异）
#   V3（dims -1 通路）≡ E1 桶 tl_dyn_g154（LLIST=154,200），已有数据不重烤。
#   矩阵修正（2026-10-16 晨）：原 V0（权重 Const 化）作废——静态桶与 dyn OM
#   在 GEB_WCONST=1 下权重同为 Const，非差异维度。
# 判读：每变体 vs torch golden 跑 dump；l0 kvk 从 0.9%（static 基线）跳
#   1.6%+（dyn 档位）= 元凶。事后与 dump_static_t4 离线互差看逐层形态。
# chip5 串行单进程（共享主机纪律：一次只加载一份）。
set -e
exec > /data/apxinf/golden/abl_driver.log 2>&1
TOKENS=154
OM=/data/apxinf/om_cache
SRC=$OM/tl154_i8
G=/data/apxinf/golden/frame0_t4v1b.safetensors
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
FUS="GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json"

variant() { # variant <tag> <gateEnv>
  # ⚠ local 多赋值必须逐行写：单行 local a=$1 b=x_$a 的 $a 取外层值（空）
  #   ——2026-10-16 首发射实锤（tag 展开空 → OM 全落 tl154_、v2rope 载错 OM 崩）
  local tag=$1 gate=$2
  local dir=$OM/tl154_$tag
  local dd=/data/apxinf/golden/dump_$tag
  mkdir -p "$dir" "$dd"
  [ -f "$dir/vision_real.om" ] || cp "$SRC/vision_real.om" "$dir/"
  [ -f "$dir/flow_real.om" ] || cp "$SRC/flow_real.om" "$dir/"
  if [ ! -f "$dir/prefix_real.om" ]; then
    echo "[abl] bake $tag start $(date -u +%T)"
    env "$FUS" ASCEND_RT_VISIBLE_DEVICES=5 \
      GEB_SEG=prefix GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
      GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
      GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$TOKENS GEB_CKPT=$CKPT \
      $gate GEB_SAVE=$dir/prefix_real.om "$BIN" > /data/apxinf/golden/abl_bake_$tag.log 2>&1
    echo "[abl] bake $tag done rc=$? $(date -u +%T)"
  fi
  echo "[abl] run $tag vs torch $(date -u +%T)"
  rm -f "$dd"/*.f16
  env "$FUS" ASCEND_RT_VISIBLE_DEVICES=5 \
    GEB_SEG=e2e GEB_E2E_GOLDEN=$G GEB_TOKENS=$TOKENS GEB_OM_DIR=$dir \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
    GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
    GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
    GEB_E2E_DUMP_MID=$dd $gate "$BIN" > /data/apxinf/golden/abl_run_$tag.log 2>&1
  echo "[abl] run $tag done rc=$? $(date -u +%T)"
}

# 用法: abl_struct_1016.sh [tag] —— 传 tag 只跑该变体（修复后单点重跑用）
ONLY=${1:-}
if [ -z "$ONLY" ] || [ "$ONLY" = v1bias ]; then variant v1bias "GEB_ABL_BIAS=1"; fi
if [ -z "$ONLY" ] || [ "$ONLY" = v2rope ]; then variant v2rope "GEB_ABL_ROPE=1"; fi
if [ -z "$ONLY" ] || [ "$ONLY" = v4sm ]; then variant v4sm "GEB_ABL_SMCONST=1"; fi
echo "[abl] ALL DONE $(date -u '+%F %T')"
