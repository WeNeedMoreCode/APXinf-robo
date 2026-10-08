#!/bin/bash
# mini_sup_i8_v3.sh — serve_i8 隔离 mini-supervisor 的校准 v3 位
# （prefix v3 多帧因子 + flow int8 v3 gud 子集——行为梯用）。
# 与 mini_sup_i8.sh（回滚位：prefix v2 + flow f16）的差异：
#   ① 因子文件全部指向 v3（smooth_calib_v3{,_flow}_engine.safetensors）
#   ② serve env 加 GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=v3
#   ③ bake 不再从 tl$L 拷 f16 flow（回滚语义）——flow 缺失时按 v3 int8 补烤
# 单实例纪律：启动前确认无其他 mini_sup 实例（pgrep -f "mini_sup_i[8]"）。
ROOT=/data/apxinf/serve_i8
OM=/data/apxinf/om_cache
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
CHIPS="6 4 7 5"
LOG=$ROOT/mini_sup_v3.log
mkdir -p "$ROOT/ctrl"
declare -A LAST_RESPAWN
ci=0
nchip=4

alive() {
  [ -f "$1" ] || return 1
  local p
  p=$(cat "$1")
  [ -n "$p" ] || return 1
  kill -0 "$p" 2>/dev/null || return 1
  [ "$(awk '{print $3}' /proc/$p/stat 2>/dev/null)" = "Z" ] && return 1
  return 0
}
next_chip() { echo $CHIPS | cut -d' ' -f$(( (ci - 1) % nchip + 1 )); }

bake_bucket() { # bake_bucket <L> <chip>：vision 拷贝 + prefix/flow v3 补烤
  local L=$1 c=$2 d=$OM/tl${L}_i8
  mkdir -p "$d"
  [ -f "$OM/tl$L/vision_real.om" ] && cp -n "$OM/tl$L/vision_real.om" "$d/"
  if [ ! -f "$d/prefix_real.om" ]; then
    echo "[v3sup] bake tl${L}_i8 prefix (chip$c) $(date)" >> "$LOG"
    env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
      ASCEND_RT_VISIBLE_DEVICES=$c \
      GEB_SEG=prefix GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 \
      GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$L GEB_CKPT=$CKPT \
      GEB_SAVE=$d/prefix_real.om "$BIN" >> "$LOG" 2>&1
  fi
  if [ ! -f "$d/flow_real.om" ]; then
    echo "[v3sup] bake tl${L}_i8 flow int8 v3 (chip$c) $(date)" >> "$LOG"
    env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
      ASCEND_RT_VISIBLE_DEVICES=$c \
      GEB_SEG=flow GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
      GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 \
      GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$L GEB_CKPT=$CKPT \
      GEB_SAVE=$d/flow_real.om "$BIN" >> "$LOG" 2>&1
  fi
}

spawn_bucket() { # spawn_bucket <L>
  local L=$1 spool=$ROOT/tl$L c
  mkdir -p "$spool"
  rm -f "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.resp_*.tmp "$spool"/.req_*.tmp \
        "$spool/ready" "$spool/shutdown"
  bake_bucket "$L" "6"
  ci=$((ci + 1)); c=$(next_chip)
  echo "[v3sup] spawn tl$L v3 int8+flow (chip$c) $(date)" >> "$LOG"
  env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 \
    "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
    ASCEND_RT_VISIBLE_DEVICES=$c \
    GEB_SEG=e2e GEB_E2E_SERVE=$spool GEB_TOKENS=$L GEB_OM_DIR=$OM/tl${L}_i8 \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
    GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
    GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
    "$BIN" > "$spool/stdout.log" 2>&1 &
  echo $! > "$spool/pid"
  LAST_RESPAWN[$L]=$(date +%s)
}

while true; do
  for f in "$ROOT"/ctrl/ensure_*; do
    [ -e "$f" ] || continue
    L=${f##*ensure_}
    if alive "$ROOT/tl$L/pid"; then
      touch "$ROOT/tl$L/ready" 2>/dev/null
    else
      spawn_bucket "$L"
    fi
    rm -f "$f"
  done
  for f in "$ROOT"/ctrl/stop_*; do
    [ -e "$f" ] || continue
    L=${f##*stop_}
    touch "$ROOT/tl$L/shutdown" 2>/dev/null
    rm -f "$f"
  done
  now=$(date +%s)
  for piddir in "$ROOT"/tl*/; do
    [ -f "$piddir/pid" ] || continue
    [ -f "$piddir/shutdown" ] && continue
    alive "$piddir/pid" && continue
    L=${piddir%/}; L=${L##*tl}
    [ -n "${LAST_RESPAWN[$L]:-}" ] || LAST_RESPAWN[$L]=0
    if [ $((now - ${LAST_RESPAWN[$L]})) -ge 60 ]; then
      echo "[v3sup] daemon: tl$L dead, respawn $(date)" >> "$LOG"
      spawn_bucket "$L"
    fi
  done
  sleep 1
done
