#!/bin/bash
# gate 版 flow 并行预烤（eval 桶准备）：删过期 flow → 9 个 L × chips 4/6/7
for L in 138 139 140 141 142 143 144 145 147; do
  rm -f /data/apxinf/om_cache/tl$L/flow_real.om
done
source /data/apxinf/rust_env.sh
export LD_LIBRARY_PATH=/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:$LD_LIBRARY_PATH
export GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned
export GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256
export GEB_SEG=flow
cd /data/apxinf/apxinf_engine || exit 1
CHIPS=(4 6 7)
i=0
for L in 138 139 140 141 142 143 144 145 147; do
  C=${CHIPS[$((i % 3))]}
  ASCEND_RT_VISIBLE_DEVICES=$C GEB_TOKENS=$L GEB_SAVE=/data/apxinf/om_cache/tl$L/flow_real.om \
    env GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json \
    ./target/release/examples/ge_model_probe > /tmp/bake_gate_L$L.log 2>&1 &
  i=$((i+1))
  if [ $((i % 3)) -eq 0 ]; then wait; fi
done
wait
date > /tmp/prebake_gate.done
echo PREBAKE_GATE_ALL_DONE
