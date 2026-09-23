#!/bin/bash
# A/B 冒烟：直起 tl144 serve 桶（不走 supervisor——单桶单芯可控）。
# 用法：ab_serve_fast.sh <legacy|fast> <chip>
#   legacy = 旧 host 中转路径（同二进制，基线）
#   fast   = GEB_SERVE_FAST=1（kv d2d 直连 + styles 驻留 + x 驻留零 sync）
set -u
MODE=${1:?legacy|fast}
CHIP=${2:?chip}
ROOT=/data/apxinf/serve
SPOOL=$ROOT/tl144
OM=/data/apxinf/om_cache
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned

# 三件套新鲜度（gate 版 = 2026-09-22 之后重烤）+ 清残留协议文件
for f in vision_real.om prefix_real.om flow_real.om; do
  ls -la "$OM/tl144/$f" || exit 1
done
mkdir -p "$SPOOL"
rm -f "$SPOOL"/req_*.bin "$SPOOL"/resp_*.bin "$SPOOL"/.resp_*.tmp "$SPOOL"/.req_*.tmp \
      "$SPOOL/ready" "$SPOOL/shutdown" "$SPOOL/pid"

FASTE=()
[ "$MODE" = fast ] && FASTE=(GEB_SERVE_FAST=1)
cd /data/apxinf/apxinf_engine
env "${FASTE[@]}" \
  "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
  ASCEND_RT_VISIBLE_DEVICES=$CHIP \
  LD_LIBRARY_PATH="/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}" \
  PYTHONPATH="/usr/local/Ascend/ascend-toolkit/latest/python/site-packages" \
  GEB_SEG=e2e GEB_E2E_SERVE=$SPOOL GEB_TOKENS=144 GEB_OM_DIR=$OM/tl144 \
  GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
  GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
  "$BIN" > "$SPOOL/stdout.log" 2>&1 &
echo $! > "$SPOOL/pid"
echo "AB_SERVE_SPAWNED mode=$MODE chip=$CHIP pid=$(cat "$SPOOL/pid")"
date
