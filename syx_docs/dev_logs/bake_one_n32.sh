#!/bin/bash
# 服务器档：/data/apxinf/replay/bake_one_n32.sh
# NORM32 OM 重烤一段：bake_one_n32.sh <seg> <L> <chip>（GEB_NORM32=1 全套；
# vision 段无 Gemma norm 不受影响，由调用方复制 tl<L> 产物）
SEG=${1:?seg}; L=${2:?L}; CHIP=${3:-6}
D=/data/apxinf/om_cache/tl${L}n32
mkdir -p $D
source /data/apxinf/rust_env.sh
export LD_LIBRARY_PATH=/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:$LD_LIBRARY_PATH
export ASCEND_RT_VISIBLE_DEVICES=$CHIP
export GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned
export GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256
export GEB_TOKENS=$L GEB_SEG=$SEG
export GEB_NORM32=1
export GEB_SAVE=$D/${SEG}_real.om
cd /data/apxinf/apxinf_engine
env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
  ./target/release/examples/ge_model_probe \
  > /tmp/bake_n32_${SEG}_L${L}.log 2>&1
rc=$?
echo "BAKE_N32 $SEG rc=$rc (save=$GEB_SAVE)"
grep -E "OM built|OM saved|parity|panic" /tmp/bake_n32_${SEG}_L${L}.log | head -5
