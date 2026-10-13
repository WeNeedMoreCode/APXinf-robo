#!/bin/bash
# test2_cleanup_1013.sh — 收尸 test2 supervisor + 其 serve + 残留测试 serve
for p in $(pgrep -f 'supervisor_test2_101[3]' || true); do kill "$p" 2>/dev/null && echo "killed sup2 $p"; done
for p in $(pgrep -f 'ge_model_prob[e]' || true); do
  if tr '\0' '\n' < /proc/$p/environ 2>/dev/null | grep -q 'serve_gear_test'; then
    kill "$p" 2>/dev/null && echo "killed test serve $p"
  fi
done
sleep 2
for p in $(pgrep -f 'ge_model_prob[e]' || true); do
  if tr '\0' '\n' < /proc/$p/environ 2>/dev/null | grep -q 'serve_gear_test'; then
    kill -9 "$p" 2>/dev/null && echo "force $p"
  fi
done
rm -rf /data/apxinf/serve_gear_test /data/apxinf/serve_gear_test2
echo T2_CLEAN_DONE
