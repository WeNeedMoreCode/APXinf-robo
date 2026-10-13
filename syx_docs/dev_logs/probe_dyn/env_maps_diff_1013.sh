#!/bin/bash
# env_maps_diff_1013.sh — chip2 生产 serve vs chip2 测试 serve 的 env/maps diff
pp=$(cat /data/apxinf/serve_gear/chip2/pid)
pt=$(cat /data/apxinf/serve_gear_test/chip2/pid)
echo "== pids: prod=$pp test=$pt =="
echo "== env diff (prod vs test) =="
diff <(strings /proc/$pp/environ | sort) <(strings /proc/$pt/environ | sort)
echo "== maps diff (uniq paths) =="
diff <(strings /proc/$pp/maps | grep -oE '/[^ ]+\.so[^ ]*' | sort -u) \
     <(strings /proc/$pt/maps | grep -oE '/[^ ]+\.so[^ ]*' | sort -u)
echo "== done =="
