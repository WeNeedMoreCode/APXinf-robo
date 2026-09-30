#!/bin/bash
# serve_ab 看门狗：A/B 隔离实验用（prefix int8 v2 + flow f16，tl144_ab OM）。
# docker exec -d bash -c 内联形态的 serve 会随 ssh 断连无声死（2026-09-30
# 取证：ready 后停写、无错误行）——脚本文件形态 + 死重拉（mini_sup 语义）。
ROOT=/data/apxinf/serve_ab
OM=/data/apxinf/om_cache/tl144_ab
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
LOG=$ROOT/watchdog.log
mkdir -p $ROOT/tl144
while true; do
  if ! [ -f $ROOT/tl144/pid ] || ! kill -0 "$(cat $ROOT/tl144/pid)" 2>/dev/null; then
    echo "[ab] spawn $(date)" >> $LOG
    rm -f $ROOT/tl144/req_*.bin $ROOT/tl144/resp_*.bin $ROOT/tl144/ready $ROOT/tl144/shutdown
    env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 \
      GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json \
      ASCEND_RT_VISIBLE_DEVICES=6 \
      GEB_SEG=e2e GEB_E2E_SERVE=$ROOT/tl144 GEB_TOKENS=144 GEB_OM_DIR=$OM \
      GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
      GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
      GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=/data/apxinf/pyo3_check/smooth_calib_v2_engine.safetensors \
      "$BIN" >> $ROOT/tl144/stdout.log 2>&1 &
    echo $! > $ROOT/tl144/pid
    echo "[ab] spawned pid=$(cat $ROOT/tl144/pid)" >> $LOG
  fi
  # ready 保鲜（supervisor touch ready 同语义；serve 死则重拉窗口内 ready 缺失）
  [ -f $ROOT/tl144/ready ] && touch $ROOT/tl144/ready
  sleep 3
done
