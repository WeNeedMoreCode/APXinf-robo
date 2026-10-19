#!/bin/bash
# ensure_supervisor_1019.sh — 容器在跑但 supervisor 缺席时自动拉起
# host cron 每 5min 调用（用户批准 2026-10-19；舰队趴窝 2.7 天教训）。
# 语义边界：容器停止 = 尊重人工决定，不自动 docker start；
# 只做「容器活着 + supervisor 不在 → start_gear_supervisor.sh」。
docker ps --format '{{.Names}}' | grep -q '^apxinf_rust$' || exit 0
docker exec apxinf_rust pgrep -f '^bash /data/apxinf/serve_range_supervisor.sh$' >/dev/null 2>&1 && exit 0
echo "[ensure] $(date -u '+%F %T') supervisor missing, starting"
bash /data/apxinf/start_gear_supervisor.sh
