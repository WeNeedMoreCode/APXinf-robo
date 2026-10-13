#!/bin/bash
# test_serve_cleanup_1013.sh — 收尸所有 serve_gear_test 相关 serve（env 匹配）
for p in $(pgrep -f 'ge_model_prob[e]' || true); do
  if tr '\0' '\n' < /proc/$p/environ 2>/dev/null | grep -q 'serve_gear_test'; then
    echo "killing test serve pid=$p ($(ps -o lstart= -p $p))"
    kill "$p" 2>/dev/null
  fi
done
sleep 2
for p in $(pgrep -f 'ge_model_prob[e]' || true); do
  if tr '\0' '\n' < /proc/$p/environ 2>/dev/null | grep -q 'serve_gear_test'; then
    kill -9 "$p" 2>/dev/null
    echo "force-killed pid=$p"
  fi
done
rm -rf /data/apxinf/serve_gear_test/chip2
echo CLEAN_DONE
