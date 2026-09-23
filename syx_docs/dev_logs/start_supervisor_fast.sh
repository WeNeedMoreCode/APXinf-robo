#!/bin/bash
# 起 fast 版 supervisor（GEB_SERVE_FAST 全桶生效）。幂等：先杀旧 supervisor。
for p in $(pgrep -f "supervisor.s[h]"); do kill "$p" 2>/dev/null; done
sleep 1
cd /data/apxinf/serve
GEB_SERVE_FAST=1 SERVE_CHIPS="6 4 7 5" nohup bash /data/apxinf/serve/supervisor.sh >> /data/apxinf/serve/supervisor.log 2>&1 &
echo "SUPERVISOR_PID=$!"
sleep 2
for p in $(pgrep -f "supervisor.s[h]"); do
  echo "alive pid=$p fast=$(tr '\0' '\n' < /proc/$p/environ 2>/dev/null | grep -c GEB_SERVE_FAST)"
done
date
