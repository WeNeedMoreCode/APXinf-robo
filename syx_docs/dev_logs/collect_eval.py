import json
import sys

tag = sys.argv[1]
s = json.load(open(f"/data/apxinf/serve/eval_{tag}_summary.json"))
suite = s["per_suite"]["libero_object"]["per_task"]
for tid, t in sorted(suite.items(), key=lambda kv: int(kv[0])):
    print(f"task {tid}: completed {t['completed']} success {t['successes']}")
rows = [json.loads(l) for l in open(f"/data/apxinf/serve/eval_{tag}.jsonl")]
ms = []
for r in rows:
    calls = r.get("replans", 0) + 1
    per = round(r["model_seconds"] * 1000 / calls, 1)
    ms.append(per)
    print(f"  task {r['task_id']}: steps {r['action_steps']} success {r['success']} model_ms/call {per}")
if ms:
    ms.sort()
    print(f"per-call P50 {ms[len(ms)//2]} min {ms[0]} max {ms[-1]}")
