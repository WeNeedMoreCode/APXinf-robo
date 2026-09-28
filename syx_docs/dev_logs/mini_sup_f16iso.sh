#!/bin/bash
# f16 隔离 spool mini-supervisor（spatial 泛化验收用；零触碰共享
# supervisor/serve/tl*——那些 supervisor 已僵尸 4 天，ensure 无人消费）：
#   serve_f16iso/ctrl/ensure_<L> → bake_one.sh（仓内标准烤器）+ f16 spawn
# eval 侧：APXINF_GE_SERVE_ROOT=/data/apxinf/serve_f16iso
ROOT=/data/apxinf/serve_f16iso
OM=/data/apxinf/om_cache
REPLAY=/data/apxinf/replay
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
CHIPS="6 4 7 5"
LOG=$ROOT/mini_sup.log
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

spawn_bucket() { # spawn_bucket <L>：缺 OM 用 bake_one.sh 烤（prefix+flow）
  local L=$1 spool=$ROOT/tl$L d=$OM/tl${L}iso c
  mkdir -p "$spool" "$d"
  rm -f "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.resp_*.tmp "$spool"/.req_*.tmp \
        "$spool/ready" "$spool/shutdown"
  if [ ! -f "$d/prefix_real.om" ] || [ ! -f "$d/flow_real.om" ]; then
    ci=$((ci + 1)); c=$(next_chip)
    echo "[f16iso] bake tl${L}iso (chip$c) $(date)" >> "$LOG"
    OM_DIR_BACKUP=${GEB_OM_DIR:-}
    # bake_one.sh <seg> <L> <chip>（仓内标准烤器——产出落 om_cache/tl<L>，
    # 烤完挪进 iso 目录避免污染共享桶）
    for seg in prefix flow; do
      if [ ! -f "$d/${seg}_real.om" ]; then
        bash "$REPLAY/bake_one.sh" "$seg" "$L" "$c" >> "$LOG" 2>&1
        mv "$OM/tl$L/${seg}_real.om" "$d/${seg}_real.om" 2>>"$LOG"
      fi
    done
    cp -n "$OM/t712fix/vision_real.om" "$d/vision_real.om" 2>>"$LOG"
  fi
  ci=$((ci + 1)); c=$(next_chip)
  echo "[f16iso] spawn tl$L f16 (chip$c) $(date)" >> "$LOG"
  env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 \
    "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
    ASCEND_RT_VISIBLE_DEVICES=$c \
    GEB_SEG=e2e GEB_E2E_SERVE=$spool GEB_TOKENS=$L GEB_OM_DIR=$d \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
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
      echo "[f16iso] daemon: tl$L dead, respawn $(date)" >> "$LOG"
      spawn_bucket "$L"
    fi
  done
  sleep 1
done
