#!/bin/bash
# 新二进制（库化后）serve 桶直起：BIN = target_libcheck。用法：
#   ab_serve_newbin.sh <legacy|fast> <chip>
# 与 ab_serve_fast.sh（旧二进制）对照——同 OM 同帧，输出须 bit 级一致。
set -u
MODE=${1:?legacy|fast}
CHIP=${2:?chip}
ROOT=/data/apxinf/serve
SPOOL=$ROOT/tl144
OM=/data/apxinf/om_cache
BIN=/data/apxinf/target_libcheck/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned

for f in vision_real.om prefix_real.om flow_real.om; do
  ls "$OM/tl144/$f" >/dev/null || exit 1
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
echo "AB_NEWBIN_SPAWNED mode=$MODE chip=$CHIP pid=$(cat "$SPOOL/pid")"
date
