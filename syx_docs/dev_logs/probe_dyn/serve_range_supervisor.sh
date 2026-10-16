#!/bin/bash
# serve_range_supervisor.sh — range padding 版 supervisor（2026-10-16）：
#   与 serve_gear_supervisor.sh 的差异（其余运维骨架不变）：
#   ① 池根 = om_cache/grid8（九桶 stride-8，GEB_ATTN_MASK=1 烤）
#   ② llist = 网格档表 {136..200}——flow 池装载 9 只（原 26 只 per-L 退役）
#   ③ spawn env + GEB_POOL_GRID=8（L→桶界引擎侧映射）+ GEB_ATTN_MASK=1
#   客户端零改动：仍发真 L（任意 L≤200 均有归属——表外 L 根除）
# 单实例纪律：启动前 pgrep 锚定无残留。
ROOT=/data/apxinf/serve_gear
OM=/data/apxinf/om_cache
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
# stride-8 网格九桶（覆盖观测全集 133-157 的上取整 + max 档 200）
LLIST="136,144,152,160,168,176,184,192,200"
LMAX=200
GRID=$OM/grid8
CHIPS="4"
LOG=$ROOT/supervisor.log
mkdir -p "$ROOT/ctrl"

alive() {
  [ -f "$1" ] || return 1
  local p
  p=$(cat "$1")
  [ -n "$p" ] || return 1
  kill -0 "$p" 2>/dev/null || return 1
  [ "$(awk '{print $3}' /proc/$p/stat 2>/dev/null)" = "Z" ] && return 1
  return 0
}

spawn_chip() { # spawn_chip <chip>
  local c=$1 spool=$ROOT/chip$c
  mkdir -p "$spool"
  rm -f "$spool"/pid "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.resp_*.tmp \
        "$spool"/.req_*.tmp "$spool/ready" "$spool/shutdown"
  echo "[range] spawn chip$c range serve $(date)" >> "$LOG"
  # range padding：GEB_POOL_GRID 引擎侧 L→桶界（token 补 0 + padmask）；
  # 池 = grid8 九桶；OM_DIR = tl200 桶（warmup/预载 + vision）。无 SERVE_MIN
  env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 \
    "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
    ASCEND_RT_VISIBLE_DEVICES=$c \
    GEB_SEG=e2e GEB_E2E_SERVE=$spool GEB_TOKENS=$LMAX GEB_DYN_LLIST=$LLIST GEB_OM_DIR=$GRID/tl200_i8 \
    GEB_PREFIX_POOL=$GRID \
    GEB_FLOW_POOL=$GRID \
    GEB_POOL_GRID=8 GEB_POOL_GRID_MIN=136 GEB_POOL_GRID_MAX=200 \
    GEB_ATTN_MASK=1 \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
    GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
    GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
    "$BIN" > "$spool/stdout.log" 2>&1 &
  echo $! > "$spool/pid"
  touch "$ROOT/gear_mode"  # 客户端 gear 路由标记（不变）
}

declare -A LAST_RESPAWN
for c in $CHIPS; do
  alive "$ROOT/chip$c/pid" || spawn_chip "$c"
  LAST_RESPAWN[$c]=$(date +%s)
  sleep 40
done

while true; do
  for f in "$ROOT"/ctrl/ensure_chip*; do
    [ -e "$f" ] || continue
    c=${f##*ensure_chip}
    if alive "$ROOT/chip$c/pid"; then
      touch "$ROOT/chip$c/ready" 2>/dev/null
    else
      echo "[range] ensure chip$c（未活）$(date)" >> "$LOG"
      spawn_chip "$c"
      LAST_RESPAWN[$c]=$(date +%s)
    fi
    rm -f "$f"
  done
  for f in "$ROOT"/ctrl/stop_chip*; do
    [ -e "$f" ] || continue
    touch "$ROOT/chip$c/shutdown" 2>/dev/null
    rm -f "$f"
  done
  now=$(date +%s)
  for c in $CHIPS; do
    piddir="$ROOT/chip$c"
    [ -f "$piddir/shutdown" ] && continue
    alive "$piddir/pid" && continue
    [ -n "${LAST_RESPAWN[$c]:-}" ] || LAST_RESPAWN[$c]=0
    if [ $((now - ${LAST_RESPAWN[$c]})) -ge 60 ]; then
      echo "[range] daemon: chip$c dead, respawn $(date)" >> "$LOG"
      spawn_chip "$c"
      LAST_RESPAWN[$c]=$(date +%s)
    fi
  done
  sleep 1
done
