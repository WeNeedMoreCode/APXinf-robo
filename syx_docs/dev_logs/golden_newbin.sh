#!/bin/bash
# 库化后新二进制 golden 对拍（验证梯第 1 档：搬移零行为变化）。
# 用法：golden_newbin.sh <chip>；期望与旧二进制同数字：
#   vision_out 0.1% / step0_x1 0.0% / actions ~0.9%（frame0_v3b gate 版基线）
set -u
CHIP=${1:?chip}
BIN=/data/apxinf/target_libcheck/release/examples/ge_model_probe
cd /data/apxinf/apxinf_engine
env ASCEND_RT_VISIBLE_DEVICES=$CHIP \
  LD_LIBRARY_PATH="/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}" \
  GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json \
  GEB_SEG=e2e GEB_CKPT=/data/apxinf/weights/pi05_libero_finetuned \
  GEB_TOKENS=200 GEB_OM_DIR=/data/apxinf/om_cache/tl200 \
  GEB_E2E_GOLDEN=/data/apxinf/golden/frame0_v3b.safetensors \
  GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
  GEB_PREFIX_DROP_EMPTY=256 \
  "$BIN" 2>&1 | grep -E "\[e2e\]|GE_E2E|BISECT|panic"
echo "GOLDEN_NEWBIN_DONE"
date
