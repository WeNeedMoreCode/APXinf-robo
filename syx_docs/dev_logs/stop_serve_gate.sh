#!/bin/bash
# 收尾停 serve 系统：supervisor + 全部桶引擎优雅退（shutdown 文件），3s 后补刀
for p in $(pgrep -f "supervisor.s[h]"); do kill "$p" 2>/dev/null; done
sleep 1
for L in 138 139 140 141 142 143 144 145 146 147 148; do
  touch /data/apxinf/serve/tl$L/shutdown 2>/dev/null
done
sleep 3
for f in /data/apxinf/serve/tl1*/pid; do
  p=$(cat "$f" 2>/dev/null)
  [ -n "$p" ] && kill "$p" 2>/dev/null
done
sleep 2
echo "live engines: $(pgrep -f 'ge_model_prob[e]' | while read q; do grep -q zombie /proc/$q/status 2>/dev/null || echo $q; done | wc -l)"
echo SERVE_STOPPED
date
