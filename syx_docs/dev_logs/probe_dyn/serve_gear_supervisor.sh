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
# 档表 = 三谱系观测全集 133-157 + 200（26 档 ≪ 100 上限；133-136 为
# goal 谱系下沿实测漂移档——L=136 曾把 22 档表外请求打崩 serve，2026-10-12）
LLIST="133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,200"
LMAX=200
# 芯表：2026-10-15 收缩为单芯（chip 4）——用户决策「常驻只占一两张卡」；
# 本机与同事 vLLM 共享（vllm-ascend 占 0-3/6-7），我们让出全部共享芯。
# 单只 gear serve 覆盖全部档位（单次推理本就单芯），代价仅并行 eval 吞吐。
# chip 4/5 是本机仅有的空芯；eval 预处理宿主同样 pin 4。
CHIPS="4"
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

bake_dyn() { # prefix 全档 OM 一次烤（int8 v3 同配方；vision 静态拷贝；
             # flow 不烤——HYBRID 用现存 per-L tl{L}_i8 静态池，GEB_FLOW_POOL）
  mkdir -p "$DYN"
  [ -f "$DYN/vision_real.om" ] || cp "$OM/t712fix/vision_real.om" "$DYN/vision_real.om"
  if [ ! -f "$DYN/prefix_real.om" ]; then
    echo "[supg] bake tl_dyn prefix（全档）$(date)" >> "$LOG"
    env "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
      ASCEND_RT_VISIBLE_DEVICES=1 \
      GEB_SEG=prefix GEB_PREFIX_INT8=1 GEB_INT8_SMOOTH=$P8 GEB_ATTN=manual GEB_QKV3=1 GEB_ROPEFLAT=1 \
      GEB_WCONST=1 GEB_PREFIX_DROP_EMPTY=256 GEB_TOKENS=$LMAX GEB_DYN_LLIST=$LLIST GEB_CKPT=$CKPT \
      GEB_SAVE=$DYN/prefix_real.om "$BIN" >> "$LOG" 2>&1
  fi
}

spawn_chip() { # spawn_chip <chip>
  local c=$1 spool=$ROOT/chip$c
  mkdir -p "$spool"
  rm -f "$spool"/pid "$spool"/req_*.bin "$spool"/resp_*.bin "$spool"/.resp_*.tmp \
        "$spool"/.req_*.tmp "$spool/ready" "$spool/shutdown"
  echo "[supg] spawn chip$c gear serve $(date)" >> "$LOG"
  # GEB_CKPT_SERVE_MIN=1：ckpt 选择性读取（styles 链+嵌入表真值，其余
  # synthetic 占位——serve 装预烤 OM 不消费占位；bake 路径 probe 侧拒绝）
  # GEB_PREFIX_POOL（T4R 2026-10-15）：prefix 段 per-L 静态 OM 池换柄执行
  # （动态图结构数值分歧根因修复）；GEB_OM_DIR 指向 tl200_i8（= max 档静态
  # prefix，warmup/预载句柄用；vision 同目录）——llist 仍传（flow 池+客户端
  # 校验），但 prefix 组装侧被 POOL env 压回静态。
  # ⚠ 池模式必须全量 ckpt（无 GEB_CKPT_SERVE_MIN）：静态桶 OM 是 260 Data
  # 输入（权重 Data 化，老静态舰队同款），serve_min 占位权重只够 170 个
  # bind——n_in 170!=260 直接 rc=-2（2026-10-15 实证）
  env GEB_SERVE_FAST=1 GEB_SERVE_TIMING=1 \
    "GEB_INIT_OPT_ge.fusionSwitchFile=/data/apxinf/fusion_off_inplace.json" \
    ASCEND_RT_VISIBLE_DEVICES=$c \
    GEB_SEG=e2e GEB_E2E_SERVE=$spool GEB_TOKENS=$LMAX GEB_DYN_LLIST=$LLIST GEB_OM_DIR=$OM/tl200_i8 \
    GEB_PREFIX_POOL=$OM \
    GEB_FLOW_POOL=$OM \
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
# 错峰 spawn（40s/芯）：4 芯齐发在 GE init/ckpt 解析/设备分配三处并发
# 竞争会静默崩（2026-10-12 26 档重启风暴取证；单服手动起稳定）
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
