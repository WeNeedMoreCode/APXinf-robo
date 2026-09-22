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

# SCOPE: expert（只 flow 侧 gemma_expert）/ language（只 prefix 侧语言
# 主干）/ both（全模型）。引擎修复范围裁决用：哪半 patch 后崩，引擎就
# 必须修哪半（Cast 包绕被证伪——GE 把 fp32 desc 归一回 f16 kernel，
# arm32 单算 f32/f16 输出逐位同，2026-09-22）
SCOPE = os.environ.get("NORM16_SCOPE", "both")


def _norm_f16(self, x):
    # 原版：var = mean(square(x.float()))——fp32 上浮算方差。
    # 对照：全 f16（对齐 GE 引擎的 AddRmsNorm 执行语义）
    var = torch.mean(torch.square(x), dim=-1, keepdim=True)
    return x * torch.rsqrt(var + self.eps)


import types  # noqa: E402


def _patch_model(model):
    n = 0
    for name, mod in model.named_modules():
        if not isinstance(mod, gm.GemmaRMSNorm):
            continue
        in_expert = "gemma_expert" in name
        hit = (SCOPE == "both") or (SCOPE == "expert" and in_expert) or (SCOPE == "language" and not in_expert)
        if hit:
            mod._norm = types.MethodType(_norm_f16, mod)
            n += 1
    return n


if SCOPE != "load_only":
    _orig_from_pretrained = gm.__dict__.get("_patch_pending", None)
    # PI05Policy 在 main() 里构造——patch 挂在类上等实例化后逐实例替换：
    # 用类级 patch 只对目标 scope 生效不可行（类方法共享），改为构造后
    # 遍历。这里 hook from_pretrained 返回后立即遍历。
    import lerobot.policies.pi05 as pi05mod  # noqa: E402

    _orig_fp = pi05mod.PI05Policy.from_pretrained.__func__

    @classmethod
    def _patched_fp(cls, *a, **kw):
        pol = _orig_fp(cls, *a, **kw)
        n = _patch_model(pol.model)
        print(f"[norm-f16] scope={SCOPE}: patched {n} GemmaRMSNorm instances", flush=True)
        return pol

    pi05mod.PI05Policy.from_pretrained = _patched_fp

from apxinf_robo.cli.eval_libero import main  # noqa: E402

TAG = os.environ.get("NORM16_TAG", f"norm16_{SCOPE}_t0")
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
