#!/bin/bash
# eval_t7_forensic.sh — spatial task7 客户端"无痕死"取证（2026-10-09，goal ②）。
# 2026-09-29 两次复现：清场后 20min 超时、桶仅受理 1 次推理后客户端死。
# 手段：PYTHONFAULTHANDLER（SIGSEGV/SIGABRT 时打印 Python 栈）+ py-spy
# 周期 dump（死后留最后栈）+ rc 采集 + serve 侧 stdout 尾采。
# serve = serve_i8 v3 位（tl153 冷 spawn 首跑，OM 已由 bake_prodext 烤好）。
cd /data/apxinf
BASE=/data/apxinf/serve_i8
LOG=$BASE/t7_forensic.log
PSLOG=$BASE/t7_pyspy.log
rm -f $PSLOG
echo "=== t7 forensic start $(date -u) ===" > $LOG
MUJOCO_GL=egl ASCEND_RT_VISIBLE_DEVICES=2 PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1 \
PYTHONPATH=/data/apxinf/robo_src:/data/apxinf/engine_py/apxinf:$PYTHONPATH \
APXINF_GE_SERVE_ROOT=$BASE \
timeout 1500 python3 -m apxinf_robo.cli eval-libero \
  --backend in-process --engine npu-ge --precision fp16 \
  --suite libero_spatial --tasks 7 --trials-per-task 1 --seed 7 \
  --replan-steps 5 \
  --model-dir /data/apxinf/weights/pi05_libero_finetuned \
  --tokenizer /data/apxinf/weights/paligemma-3b-pt-224 \
  --results-jsonl $BASE/eval_t7f.jsonl \
  --summary-json $BASE/eval_t7f_summary.json \
  >> $LOG 2>&1 &
MAINPID=$!
echo "client pid=$MAINPID" >> $LOG
if command -v py-spy >/dev/null 2>&1; then
  while kill -0 $MAINPID 2>/dev/null; do
    py-spy dump --pid $MAINPID >> $PSLOG 2>&1
    echo "--- $(date -u +%T) ---" >> $PSLOG
    sleep 15
  done
else
  echo "py-spy not found" >> $LOG
fi
wait $MAINPID
RC=$?
echo "CLIENT_RC=$RC" >> $LOG
echo "=== serve tl153 stdout tail ===" >> $LOG
tail -20 /data/apxinf/serve_i8/tl153/stdout.log >> $LOG 2>&1
echo "=== dmesg tail ===" >> $LOG
dmesg 2>/dev/null | tail -15 >> $LOG
echo "T7_FORENSIC_DONE rc=$RC $(date -u)" >> $LOG
