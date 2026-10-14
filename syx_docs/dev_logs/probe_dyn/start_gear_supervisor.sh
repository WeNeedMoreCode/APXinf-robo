#!/bin/bash
# start_gear_supervisor.sh — gear supervisor 启动器（宿主侧入口）
# 关键事实（2026-10-14 取证）：gear supervisor + serve 全家住在 apxinf_rust 容器
# （v3 supervisor/回退桶 serve 同容器 cgroup 实证；容器内 CANN 9.0.1 标准路径齐全，
# 宿主 /usr/local/Ascend 只有 driver——宿主起 supervisor 必然 spawn 失败：
# 先 libascendcl 找不到，补路径后 geb init -1）。
# 用法: bash /data/apxinf/start_gear_supervisor.sh   （幂等：已有实例拒绝启动）
if docker exec apxinf_rust pgrep -f "^bash /data/apxinf/serve_gear_supervisor.sh$" >/dev/null 2>&1; then
  echo "already running in apxinf_rust: pid=$(docker exec apxinf_rust pgrep -f '^bash /data/apxinf/serve_gear_supervisor.sh$')"
  exit 1
fi
docker exec -d apxinf_rust bash /data/apxinf/serve_gear_supervisor.sh
sleep 3
if docker exec apxinf_rust pgrep -f "^bash /data/apxinf/serve_gear_supervisor.sh$" >/dev/null 2>&1; then
  echo LAUNCHED
else
  echo LAUNCH_FAILED; exit 1
fi
