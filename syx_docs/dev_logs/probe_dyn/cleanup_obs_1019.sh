#!/bin/bash
# cleanup_obs_1019.sh — range 观察期收尾清理（goal #3，2026-10-19 立案）
# 门：隔日 spot 第二绿后执行（10-19 已两轮 6/6，隔日轮全绿即 DOIT）
# 清单 = goal 点名四项 + 当日 ab_catgu 实验资产；grid8/t712fix/旧 f16 目录不动
# 用法: bash cleanup_obs_1019.sh DOIT   （无参 = 只打印清单不删）
set -eu
OM=/data/apxinf/om_cache
G=/data/apxinf/golden
TARGETS=""
for L in 133 134 135 136 137 138 139 140 141 142 143 144 145 146 147 148 149 150 151 152 153 154 155 156 157 200; do
  TARGETS="$TARGETS $OM/tl${L}_i8"
done
TARGETS="$TARGETS $OM/tl154_v1bias $OM/tl154_v2rope $OM/tl154_v4sm $OM/tl_dyn_g154 $OM/ab_catgu"
TARGETS="$TARGETS $G/dump_ab_base $G/dump_ab_catgu $G/dump_ab_catgu2 $G/dump_dyn_g154 $G/dump_dyn_t4 $G/dump_dyn_torch $G/dump_range160 $G/dump_static_t4 $G/dump_v1bias $G/dump_v2rope $G/dump_v4sm"
echo "== 清理清单（~98GB）=="
du -shc $TARGETS 2>/dev/null | tail -3
echo "== 保留校验 =="
ls $OM/grid8/tl200_i8 >/dev/null && echo grid8_OK
ls $OM/t712fix/vision_real.om >/dev/null && echo t712fix_OK
if [ "${1:-}" != "DOIT" ]; then
  echo
  echo "DRY-RUN（无删除）。确认后: bash $0 DOIT"
  exit 0
fi
rm -rf $TARGETS
echo "== 完成 =="
df -h /data | tail -1
