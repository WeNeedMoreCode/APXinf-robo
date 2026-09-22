#!/bin/bash
# GEB_E2E_SERVE 桶生命周期管理（apxinf_rust 容器内 nohup 常驻）
# 控制（/data/apxinf/serve/ctrl/）：
#   ensure_<L> —— 保证 tl<L> serve 进程活着（缺 OM 先烤 ~4min/段，再 spawn）
#   stop_<L>   —— 优雅停 tl<L>
# 守护：每轮扫描已 spawn 桶，进程死（含 zombie——kill -0 对 defunct 也返回
# 0，须读 /proc state 排除）自动 respawn（60s 退避防崩循环）——并发启动
# 风暴下的间歇加载崩靠这里自愈，python 端 mtime 判定自动接上新 ready。
# 状态：tl<L>/pid（supervisor 子进程 pid）、tl<L>/ready（engine 自写）、
#       tl<L>/stdout.log（engine 输出）
# 芯片：SERVE_CHIPS 空格列表轮转（默认 "6 4 7 5"）
ROOT=/data/apxinf/serve
CTRL=$ROOT/ctrl
OM=/data/apxinf/om_cache
REPLAY=/data/apxinf/replay
BIN=/data/apxinf/apxinf_engine/target/release/examples/ge_model_probe
CKPT=/data/apxinf/weights/pi05_libero_finetuned
CHIPS=${SERVE_CHIPS:-"6 4 7 5"}
LOG=$ROOT/supervisor.log
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
# ⚠ ci 自增必须在主 shell：命令替换是子 shell，函数内改 ci 不回传——
# 首版全 spawn 到 chip6 把显存挤爆（2026-09-22 实踩）
next_chip() { echo "$CHIPS" | cut -d' ' -f$(( (ci - 1) % nchip + 1 )); }

spawn_bucket() { # spawn_bucket <L>：清残留→缺 OM 烤→spawn（bake 串行全局）
  local L=$1 spool=$ROOT/tl$L c
  mkdir -p "$spool"
  rm -f "$spool"/pid "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.resp_*.tmp \
        "$spool"/.req_*.tmp "$spool/ready" "$spool/shutdown"
  if [ ! -f "$OM/tl$L/prefix_real.om" ] || [ ! -f "$OM/tl$L/flow_real.om" ]; then
    ci=$((ci + 1)); c=$(next_chip)
    echo "[sup] bake tl$L (chip$c) start $(date)" >> "$LOG"
    bash "$REPLAY/bake_one.sh" prefix "$L" "$c" >> "$LOG" 2>&1
    bash "$REPLAY/bake_one.sh" flow "$L" "$c" >> "$LOG" 2>&1
    echo "[sup] bake tl$L done $(date)" >> "$LOG"
  fi
  # vision 段与 token 无关——复制 t712fix 产物（bake_one 约定）
  [ -f "$OM/tl$L/vision_real.om" ] || cp "$OM/t712fix/vision_real.om" "$OM/tl$L/vision_real.om"
  ci=$((ci + 1)); c=$(next_chip)
  echo "[sup] spawn tl$L (chip$c) $(date)" >> "$LOG"
  env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
    ASCEND_RT_VISIBLE_DEVICES=$c \
    LD_LIBRARY_PATH="/data/apxinf/ascendc/ge_builder/build:/usr/local/Ascend/ascend-toolkit/latest/lib64:${LD_LIBRARY_PATH:-}" \
    PYTHONPATH="/usr/local/Ascend/ascend-toolkit/latest/python/site-packages:${PYTHONPATH:-}" \
    GEB_SEG=e2e GEB_E2E_SERVE=$spool GEB_TOKENS=$L GEB_OM_DIR=$OM/tl$L \
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
      # 已活：刷新 ready mtime（python 端以 mtime>ensure 时刻判定就绪）
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
  # 守护：死桶自动 respawn（60s 退避；shutdown 等待退出的不算）
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
