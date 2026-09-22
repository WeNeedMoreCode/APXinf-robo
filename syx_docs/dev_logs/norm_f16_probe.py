"""对照实验：torch 基线的 GemmaRMSNorm 方差计算去 fp32 上浮（全 f16），
跑 task0 闭环——崩 = norm 精度是行为开关（引擎修 fp32 上浮即对症）；
不崩 = 引擎另有集成 bug（194% 残差另有主源）。

跑法（apxinf_npu）：环境同 run_ge_eval.sh，python3 norm_f16_probe.py
"""
import os
import sys

os.environ.setdefault("MUJOCO_GL", "egl")
sys.path.insert(0, "/data/apxinf/robo_src")
sys.path.insert(0, "/data/apxinf/engine_py/apxinf")

import torch  # noqa: E402
import transformers.models.gemma.modeling_gemma as gm  # noqa: E402


def _norm_f16(self, x):
    # 原版：var = mean(square(x.float()))——fp32 上浮算方差。
    # 对照：全 f16（对齐 GE 引擎的 AddRmsNorm 执行语义）
    var = torch.mean(torch.square(x), dim=-1, keepdim=True)
    return x * torch.rsqrt(var + self.eps)


gm.GemmaRMSNorm._norm = _norm_f16
print("[norm-f16] GemmaRMSNorm._norm patched: fp32 upcast removed", flush=True)

from apxinf_robo.cli.eval_libero import main  # noqa: E402

TAG = os.environ.get("NORM16_TAG", "norm16_t0")
sys.argv = [
    "eval-libero",
    "--backend", "in-process",
    "--engine", "npu-torch",
    "--precision", "fp16",
    "--suite", "libero_object",
    "--tasks", os.environ.get("NORM16_TASKS", "0"),
    "--trials-per-task", "1",
    "--seed", "7",
    "--replan-steps", "5",
    "--model-dir", "/data/apxinf/weights/pi05_libero_finetuned",
    "--tokenizer", "/data/apxinf/weights/paligemma-3b-pt-224",
    "--results-jsonl", f"/data/apxinf/serve/eval_{TAG}.jsonl",
    "--summary-json", f"/data/apxinf/serve/eval_{TAG}_summary.json",
]
main(sys.argv[1:])
