#!/bin/bash
# prof_hotspot_1015.sh — 最小 msprof 热点采集（ascend-msprof skill 最小化纪律：
# 12 迭代 ≈ 2.4 万 task 行 < 5 万红线；产物 ~200MB 级非 GB 级）
# 用法（apxinf_rust 容器内）: bash /data/apxinf/prof_hotspot_1015.sh
OUT=/data/apxinf/prof_hotspot_1015
rm -rf "$OUT"
msprof --output="$OUT" --application="/data/apxinf/prof_bench_inner.sh" \
  > /data/apxinf/prof_hotspot_1015_msprof.log 2>&1
echo "MSPROF_RC=$? $(date -u +%T)" >> /data/apxinf/prof_hotspot_1015_msprof.log
