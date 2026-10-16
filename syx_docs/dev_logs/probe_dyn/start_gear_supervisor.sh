#!/bin/bash
# start_gear_supervisor.sh — supervisor 启动器（宿主侧入口；唯一启动姿势）
# 2026-10-16 起 = range padding 版（serve_range_supervisor.sh：grid8 九桶 +
# GEB_POOL_GRID 映射 + ATTN_MASK）。回滚 = 改回 serve_gear_supervisor.sh
# （per-L 精确桶，26 只 tl{L}_i8 仍在 om_cache）。
# 关键事实（2026-10-14 取证）：supervisor + serve 全家住 apxinf_rust 容器
# （宿主 /usr/local/Ascend 只有 driver——宿主起必然 spawn 失败）。
# 用法: bash /data/apxinf/start_gear_supervisor.sh   （幂等：已有实例拒绝启动）
SUP=/data/apxinf/serve_range_supervisor.sh
if docker exec apxinf_rust pgrep -f "^bash ${SUP}$" >/dev/null 2>&1; then
  echo "already running in apxinf_rust: pid=$(docker exec apxinf_rust pgrep -f "^bash ${SUP}$")"
  exit 1
fi
docker exec -d apxinf_rust bash "$SUP"
sleep 3
if docker exec apxinf_rust pgrep -f "^bash ${SUP}$" >/dev/null 2>&1; then
  echo LAUNCHED
else
  echo LAUNCH_FAILED; exit 1
fi
