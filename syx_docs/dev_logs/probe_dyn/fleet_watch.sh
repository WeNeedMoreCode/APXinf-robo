#!/bin/bash
# fleet_watch.sh — gear 舰队 + 回退桶健康快照（运维留观，可反复跑/cron）
# 输出: 4 芯 pid+ready mtime / 回退桶 tl151-157 / 双 supervisor / 内存水位 /
#       apxinf_rust 容器孤儿 serve 计数 / supervisor.log 增量（对比上次运行）
BASE=/data/apxinf/serve_gear
STATE=/tmp/fleet_watch.state
echo "==== fleet_watch $(date -u '+%F %T') ===="
# 存活判定 = environ 指纹（/proc/PID/environ 的 GEB_E2E_SERVE 精确匹配）：
# pid 文件法有两个已知坑——pid 回收假阳（2026-10-14 取证：444797 系死后
# pid 文件失真，supervisor daemon 不动作）与容器 pid/宿主 pid namespace 错位
# （回退桶 serve 由 v3 supervisor docker exec spawn，pid 文件是容器内 pid）。
# 单次遍历：只对 cmdline 含 ge_model_probe 的活进程读 environ（serve 专属），
# 产出 "spool_root pid" 清单供各段 grep 统计——避免全进程表逐个 strings
SVLIST=$(mktemp)
ps -eo pid,stat,args --no-headers | awk '$2 !~ /Z/ && /ge_model_prob[e]/ {print $1}' | while read p; do
  r=$(strings /proc/$p/environ 2>/dev/null | grep "^GEB_E2E_SERVE=" | cut -d= -f2)
  [ -n "$r" ] && echo "$r $p"
done > "$SVLIST"
echo "-- gear fleet (environ 指纹) --"
for c in 0 1 2 3; do
  n=$(grep -c "^$BASE/chip$c " "$SVLIST")
  [ "$n" -ge 2 ] && st="ALIVE(${n}p)" || st="DEAD(${n}p)"
  echo "chip$c $st pidfile=$(cat $BASE/chip$c/pid 2>/dev/null) ready=$(stat -c %y $BASE/chip$c/ready 2>/dev/null | cut -d. -f1)"
done
echo "-- fallback tl151-157 (environ 指纹) --"
n=0
for L in 151 152 153 154 155 156 157; do
  m=$(grep -c "^/data/apxinf/serve/tl$L " "$SVLIST")
  [ "$m" -ge 2 ] && { st="ALIVE(${m}p)"; n=$((n+1)); } || st="DEAD(${m}p)"
  echo "tl$L $st"
done
echo "fallback_alive=$n/7"
rm -f "$SVLIST"
echo "-- supervisors --"
ps -eo pid,etime,args | grep "supervis[o]r"
# 主循环心跳：supervisor 应每秒 fork sleep 1（无活 sleep 子进程 = 主循环卡死）
for sp in $(pgrep -f "supervis[o]r"); do
  if ps --ppid $sp -o cmd --no-headers 2>/dev/null | grep -q "^sleep"; then
    echo "sup $sp: loop OK (sleep heartbeat)"
  else
    echo "sup $sp: ⚠ NO sleep child — main loop suspect"
  fi
done
echo "-- memory --"
free -g | awk 'NR==2{printf "total=%s used=%s available=%s\n",$2,$3,$7}'
RINIT=$(docker inspect -f '{{.State.Pid}}' apxinf_rust 2>/dev/null)
if [ -n "$RINIT" ]; then
  orph=$(ps -eo pid,ppid,stat --no-headers | awk -v p=$RINIT '$2==p && $3 !~ /Z/' | wc -l)
  zomb=$(ps -eo pid,ppid,stat --no-headers | awk -v p=$RINIT '$2==p && $3 ~ /Z/' | wc -l)
  echo "-- apxinf_rust container: alive_orphans=$orph zombies=$zomb (init=$RINIT)"
fi
cur=$(wc -l < $BASE/supervisor.log 2>/dev/null)
prev=$(cat $STATE 2>/dev/null)
echo "-- supervisor.log lines=$cur delta=$((cur-${prev:-0}))"
echo $cur > $STATE
tail -5 $BASE/supervisor.log 2>/dev/null
echo "==== done ===="
