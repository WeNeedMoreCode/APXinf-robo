#!/bin/bash
# serve_supervisor_v3.sh — 生产根 /data/apxinf/serve 的 v3 int8 supervisor
# （2026-10-09 v3 生产化切换：prefix v3 多帧因子 + flow int8 v3 gud 子集）。
# 与 mini_sup_i8_v3.sh（serve_i8 隔离根，行为梯用）同配置不同根；
# 与 serve_supervisor.sh（旧 f16 位，Oct 4 断电后未重启）的差异：
#   ① OM 指向 tl${L}_i8（int8 v3 桶；f16 桶 tl$L 保留为回退资产）
#   ② serve env 带 GEB_PREFIX_INT8/GEB_INT8_SMOOTH=v3 + GEB_FLOW_INT8/gud
#   ③ vision OM 统一拷 t712fix（tl149-156 plain 桶无 vision）
#   ④ bake_bucket 按轮转芯烤（mini_sup 版硬编码 6）
# 单实例纪律：启动前确认无其他 supervisor（pgrep -f "sup_i8_v[3]|supervisor_v[3]"）；
# 启动前须 touch 全部 tl*/shutdown（防 stale pid 自动复活风暴——2026-10-08 教训）。
ROOT=/data/apxinf/serve
OM=/data/apxinf/om_cache
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
P8=/data/apxinf/pyo3_check/smooth_calib_v3_engine.safetensors
F8=/data/apxinf/pyo3_check/smooth_calib_v3_flow_engine.safetensors
CHIPS="6 4 7 5"
LOG=$ROOT/supervisor_v3.log
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
next_chip() { echo "$CHIPS" | cut -d' ' -f$(( (ci - 1) % nchip + 1 )); }

bake_bucket() { # bake_bucket <L> <chip>：vision 拷贝 + prefix/flow v3 补烤
  local L=$1 c=$2 d=$OM/tl${L}_i8
  mkdir -p "$d"
  [ -f "$d/vision_real.om" ] || cp "$OM/t712fix/vision_real.om" "$d/vision_real.om"
  if [ ! -f "$d/prefix_real.om" ]; then
    echo "[supv3] bake tl${L}_i8 prefix (chip$c) $(date)" >> "$LOG"
    env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
      ASCEND_RT_VISIBLE_DEVICES=$c \
      GEB_SEG=prefix GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 \
      GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$L GEB_CKPT=$CKPT \
      GEB_SAVE=$d/prefix_real.om "$BIN" >> "$LOG" 2>&1
  fi
  if [ ! -f "$d/flow_real.om" ]; then
    echo "[supv3] bake tl${L}_i8 flow int8 v3 (chip$c) $(date)" >> "$LOG"
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
  rm -f "$spool"/pid "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.resp_*.tmp \
        "$spool"/.req_*.tmp "$spool/ready" "$spool/shutdown"
  ci=$((ci + 1)); c=$(next_chip)
  bake_bucket "$L" "$c"
  ci=$((ci + 1)); c=$(next_chip)
  echo "[supv3] spawn tl$L v3 int8+flow (chip$c) $(date)" >> "$LOG"
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
      echo "[supv3] daemon: tl$L dead, respawn $(date)" >> "$LOG"
      spawn_bucket "$L"
    fi
  done
  sleep 1
done
