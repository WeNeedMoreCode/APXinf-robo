#!/bin/bash
# 服务器档：/data/apxinf/serve/supervisor_n32.sh
# supervisor.sh 的 NORM32 变体：OM 缓存 tl<L>n32、bake 走 bake_one_n32.sh、
# serve 进程加 GEB_NORM32=1（2026-09-22 NORM32 v2 落地）。控制接口/守护
# 逻辑与原版相同（ctrl/ensure_<L>、stop_<L>，spool 复用 tl<L>/ 目录——
# python 客户端按 spool 找桶，对 n32 无感知）
ROOT=/data/apxinf/serve
CTRL=$ROOT/ctrl
OM=/data/apxinf/om_cache
REPLAY=/data/apxinf/replay
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
CHIPS=${SERVE_CHIPS:-"6 4 7 5"}
LOG=$ROOT/supervisor_n32.log
mkdir -p "$CTRL"
declare -A LAST_RESPAWN
ci=0
nchip=$(echo $CHIPS | wc -w)

alive() {
  [ -f "$1" ] || return 1
  local p
  p=$(cat "$1")
  [ -n "$p" ] || return 1
  kill -0 "$p" 2>/dev/null || return 1
  [ "$(awk '{print $3}' /proc/$p/stat 2>/dev/null)" = "Z" ] && return 1
  return 0
}
next_chip() { echo "$CHIPS" | cut -d' ' -f$(( (ci - 1) % nchip + 1 )); }

spawn_bucket() { # spawn_bucket <L>
  local L=$1 spool=$ROOT/tl$L c
  mkdir -p "$spool"
  rm -f "$spool"/pid "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.resp_*.tmp \
        "$spool"/.req_*.tmp "$spool/ready" "$spool/shutdown"
  if [ ! -f "$OM/tl${L}n32/prefix_real.om" ] || [ ! -f "$OM/tl${L}n32/flow_real.om" ]; then
    ci=$((ci + 1)); c=$(next_chip)
    echo "[sup] bake-n32 tl$L (chip$c) start $(date)" >> "$LOG"
    bash "$REPLAY/bake_one_n32.sh" prefix "$L" "$c" >> "$LOG" 2>&1
    bash "$REPLAY/bake_one_n32.sh" flow "$L" "$c" >> "$LOG" 2>&1
    echo "[sup] bake-n32 tl$L done $(date)" >> "$LOG"
  fi
  [ -f "$OM/tl${L}n32/vision_real.om" ] || cp "$OM/t712fix/vision_real.om" "$OM/tl${L}n32/vision_real.om"
  ci=$((ci + 1)); c=$(next_chip)
  echo "[sup] spawn-n32 tl$L (chip$c) $(date)" >> "$LOG"
  env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
    ASCEND_RT_VISIBLE_DEVICES=$c \
    LD_LIBRARY_PATH="/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}" \
    PYTHONPATH="/usr/local/Ascend/ascend-toolkit/latest/python/site-packages:${PYTHONPATH:-}" \
    GEB_SEG=e2e GEB_E2E_SERVE=$spool GEB_TOKENS=$L GEB_OM_DIR=$OM/tl${L}n32 \
    GEB_NORM32=1 \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
    "$BIN" > "$spool/stdout.log" 2>&1 &
  echo $! > "$spool/pid"
  LAST_RESPAWN[$L]=$(date +%s)
}

while true; do
  for f in "$CTRL"/ensure_*; do
    [ -e "$f" ] || continue
    L=${f##*ensure_}
    if alive "$ROOT/tl$L/pid"; then
      touch "$ROOT/tl$L/ready" 2>/dev/null
    else
      spawn_bucket "$L"
    fi
    rm -f "$f"
  done
  for f in "$CTRL"/stop_*; do
    [ -e "$f" ] || continue
    L=${f##*stop_}
    echo "[sup] stop tl$L $(date)" >> "$LOG"
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
      echo "[sup] daemon: tl$L dead, respawn $(date)" >> "$LOG"
      spawn_bucket "$L"
    fi
  done
  sleep 1
done
