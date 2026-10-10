#!/bin/bash
# serve_supervisor_gear.sh — 动态分档（dynamic gear）版 supervisor：每芯一只
# 常驻 serve（单只多档 prefix/flow OM，请求按 L 选档），替代 per-L 桶拓扑。
# 与 serve_supervisor_v3.sh 的差异：
#   ① OM = om_cache/tl_dyn（prefix/flow 各一只全档 OM，vision 静态拷贝）
#   ② spawn 粒度 = 芯（spool 目录 chip<N>，supervisor 全量保活）
#   ③ serve env 带 GEB_DYN_LLIST 档表 + GEB_TOKENS=200（= max L，binds 按
#      max 物化）；请求 L 由 payload 头携带，档表外 L 引擎侧 panic 拒绝
#   ④ 首启先烤档 OM（bake_dyn 一次，全档 int8 v3 同 v3 配方）
# 单实例纪律：启动前 pgrep -f "supervisor_gea[r]" 锚定无残留。
ROOT=/data/apxinf/serve_gear
OM=/data/apxinf/om_cache
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
# 档表 = 三谱系观测全集 137-157 + 200（22 档 ≪ 100 上限）
LLIST="137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,200"
LMAX=200
CHIPS="6 4 7 5"
DYN=$OM/tl_dyn
LOG=$ROOT/supervisor.log
mkdir -p "$ROOT/ctrl" "$DYN"

alive() {
  [ -f "$1" ] || return 1
  local p
  p=$(cat "$1")
  [ -n "$p" ] || return 1
  kill -0 "$p" 2>/dev/null || return 1
  [ "$(awk '{print $3}' /proc/$p/stat 2>/dev/null)" = "Z" ] && return 1
  return 0
}

bake_dyn() { # 全档 OM 一次烤（int8 v3 同配方；vision 静态拷贝）
  mkdir -p "$DYN"
  [ -f "$DYN/vision_real.om" ] || cp "$OM/t712fix/vision_real.om" "$DYN/vision_real.om"
  if [ ! -f "$DYN/prefix_real.om" ]; then
    echo "[supg] bake tl_dyn prefix（全档）$(date)" >> "$LOG"
    env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
      ASCEND_RT_VISIBLE_DEVICES=6 \
      GEB_SEG=prefix GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 \
      GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$LMAX GEB_DYN_LLIST=$LLIST GEB_CKPT=$CKPT \
      GEB_SAVE=$DYN/prefix_real.om "$BIN" >> "$LOG" 2>&1
  fi
  if [ ! -f "$DYN/flow_real.om" ]; then
    echo "[supg] bake tl_dyn flow（全档）$(date)" >> "$LOG"
    env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
      ASCEND_RT_VISIBLE_DEVICES=6 \
      GEB_SEG=flow GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
      GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 \
      GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$LMAX GEB_DYN_LLIST=$LLIST GEB_CKPT=$CKPT \
      GEB_SAVE=$DYN/flow_real.om "$BIN" >> "$LOG" 2>&1
  fi
}

spawn_chip() { # spawn_chip <chip>
  local c=$1 spool=$ROOT/chip$c
  mkdir -p "$spool"
  rm -f "$spool"/pid "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.resp_*.tmp \
        "$spool"/.req_*.tmp "$spool/ready" "$spool/shutdown"
  echo "[supg] spawn chip$c gear serve $(date)" >> "$LOG"
  env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 \
    "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
    ASCEND_RT_VISIBLE_DEVICES=$c \
    GEB_SEG=e2e GEB_E2E_SERVE=$spool GEB_TOKENS=$LMAX GEB_DYN_LLIST=$LLIST GEB_OM_DIR=$DYN \
    GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 GEB_WCONST=1 \
    GEB_PREFIX_DROP_EMPTY=256 GEB_CKPT=$CKPT \
    GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 \
    GEB_FLOW_INT8=1 GEB_FLOW_PROJS=gate,up,down GEB_FLOW_SMOOTH=$F8 \
    "$BIN" > "$spool/stdout.log" 2>&1 &
  echo $! > "$spool/pid"
  touch "$ROOT/gear_mode"  # 客户端 gear 路由标记
}

declare -A LAST_RESPAWN
bake_dyn
for c in $CHIPS; do
  alive "$ROOT/chip$c/pid" || spawn_chip "$c"
  LAST_RESPAWN[$c]=$(date +%s)
done

while true; do
  for f in "$ROOT"/ctrl/ensure_chip*; do
    [ -e "$f" ] || continue
    c=${f##*ensure_chip}
    if alive "$ROOT/chip$c/pid"; then
      touch "$ROOT/chip$c/ready" 2>/dev/null
    else
      echo "[supg] ensure chip$c（未活）$(date)" >> "$LOG"
      spawn_chip "$c"
      LAST_RESPAWN[$c]=$(date +%s)
    fi
    rm -f "$f"
  done
  for f in "$ROOT"/ctrl/stop_chip*; do
    [ -e "$f" ] || continue
    c=${f##*stop_chip}
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
      echo "[supg] daemon: chip$c dead, respawn $(date)" >> "$LOG"
      spawn_chip "$c"
      LAST_RESPAWN[$c]=$(date +%s)
    fi
  done
  sleep 1
done
