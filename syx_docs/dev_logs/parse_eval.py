import json

rows = [json.loads(l) for l in open("/data/apxinf/serve/eval_full1.jsonl")]
succ = 0
for r in sorted(rows, key=lambda x: x["task_id"]):
    ok = r.get("success")
    st = r.get("status")
    succ += bool(ok)
    inf = r.get("inference_seconds", 0)
    ms = r.get("model_seconds", 0)
    rp = r.get("replans", 0)
    steps = r.get("action_steps", 0)
    per = ms / rp * 1000 if rp else 0
    print(
        f"task{r['task_id']}: success={ok} status={st} steps={steps} replans={rp} "
        f"engine={per:.0f}ms/replan total_inf={inf:.0f}s"
    )
print(f"\n=== {succ}/10 ===")
