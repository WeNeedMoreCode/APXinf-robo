#!/usr/bin/env python3
"""L 谱系探测：全 suite × 全任务的 prompt token 长度分布（静态 OM 分桶依据）。

复刻 eval 客户端的精确 tokenize 链（processors/tokenize.py PromptTokenizer）：
build_prompt(清洗后任务文本) → SentencePiece encode(add_bos=True) + 尾部独立
换行 token。L = len(ids) 决定桶 tl{L}——静态 OM 每长度一桶，烤桶/预置预算
以此为准（2026-09-28 实证 object 套件跑 140-148）。

用法（apxinf_npu 容器，PYTHONPATH 须含 engine_py/apxinf——注意追加继承
容器默认值，覆盖会丢 torch_npu/tbe 路径导致 init 挂）：
  PYTHONPATH=/data/apxinf/engine_py/apxinf:$PYTHONPATH python3 probe_L_spectrum.py
"""
import sys
from collections import Counter

from libero.libero import benchmark

sys.path.insert(0, "/data/apxinf/engine_py/apxinf")
from apxinf.processors.tokenize import PromptTokenizer  # noqa: E402

TOKENIZER_MODEL = "/data/apxinf/weights/paligemma-3b-pt-224/tokenizer.model"


def main():
    tok = PromptTokenizer(TOKENIZER_MODEL)
    bench = benchmark.get_benchmark_dict()
    total = Counter()
    for name in sorted(bench.keys()):
        suite = bench[name]()
        lens = []
        for tid in range(suite.n_tasks):
            prompt = str(suite.get_task(tid).language)
            lens.append(len(tok(prompt)))
        dist = Counter(lens)
        total.update(dist)
        lo, hi = min(lens), max(lens)
        uniq = sorted(dist.items())
        print(f"{name:<16} n={suite.n_tasks} L∈[{lo},{hi}] 分布 {uniq}")
    lo, hi = min(total), max(total)
    buckets = sorted(total)
    print(f"\n全谱系：L∈[{lo},{hi}]，需桶 {buckets}（共 {len(buckets)} 个）")


if __name__ == "__main__":
    main()
