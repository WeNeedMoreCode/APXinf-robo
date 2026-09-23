#!/bin/bash
# tl200 flow_real.om gate 版重烤（golden v3b 是 L=200；旧 tl200 flow 是
# pre-gate 陈旧版）。用库化后新二进制——顺带验证搬移后建图面。
# ⚠ 无 set -u：rust_env.sh 引用未定义变量会炸（bake 首跑教训）
CHIP=${1:?chip}
BIN=/data/apxinf/target_libcheck/release/examples/ge_model_probe
export LD_LIBRARY_PATH=/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}
export GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned
export GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256
export GEB_SEG=flow
export GEB_TOKENS=200
export GEB_SAVE=/data/apxinf/om_cache/tl200/flow_real.om
export ASCEND_RT_VISIBLE_DEVICES=$CHIP
cd /data/apxinf/apxinf_engine || exit 1
env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
  "$BIN" > /tmp/bake_tl200_newbin.log 2>&1
RC=$?
ls -la /data/apxinf/om_cache/tl200/flow_real.om
echo "BAKE_TL200_RC=$RC"
tail -3 /tmp/bake_tl200_newbin.log
date
