#!/usr/bin/env python
# probe_tok_cost_1015.py — I9 取证：tokenizer 单项成本 + state 段可分解性
# 跑法（宿主）: docker exec apxinf_npu bash -lc 'python /data/apxinf/probe_tok_cost_1015.py'
# 只用 CPU，不碰 NPU。回答三个问题：
#   Q1 每步 tokenizer 全量调用到底多少 ms（186ms 归因是否成立）
#   Q2 prefix-only / state 段 / 尾巴 各占多少
#   Q3 per-int 查表 concat 是否与全串 tokenize 逐位一致（BPE 跨界风险）
import time
import collections
import numpy as np
from transformers import AutoTokenizer

TOK_DIR = "/data/apxinf/weights/paligemma-3b-pt-224"
t0 = time.perf_counter()
tok = AutoTokenizer.from_pretrained(TOK_DIR)
print(f"load_ms={(time.perf_counter()-t0)*1000:.1f} class={type(tok).__name__} is_fast={tok.is_fast}")

TASK = "put the black bowl on the stove element"


def make_prompt(state):
    s = " ".join(map(str, state))
    return f"Task: {TASK}, State: {s};\nAction: "


def call(text):
    return tok(
        text,
        max_length=200,
        truncation=True,
        padding="max_length",
        padding_side="right",
        return_tensors="pt",
    )


rng = np.random.default_rng(0)
states = [rng.integers(-255, 256, size=32).tolist() for _ in range(50)]
states[0] = [0] * 32
states[1] = [255] * 32
states[2] = [-255] * 32

# Q1: 全量调用稳态成本
for st in states[:5]:
    call(make_prompt(st))  # warm
t0 = time.perf_counter()
for st in states:
    call(make_prompt(st))
print(f"Q1 full_prompt_call_ms={(time.perf_counter()-t0)/len(states)*1000:.2f}")

# Q2: 分段成本
prefix = f"Task: {TASK}, State: "
state_only = " ".join(map(str, states[5]))
tail = ";\nAction: "
for _ in range(3):
    call(prefix)
    call(state_only)
    call(tail)
for name, s in (("prefix", prefix), ("state_only", state_only), ("tail", tail)):
    t0 = time.perf_counter()
    for _ in range(20):
        call(s)
    print(f"Q2 {name}_ms={(time.perf_counter()-t0)/20*1000:.2f}")

# digitize 本体（Normalizer 后的离散化,应可忽略）
norm_state = rng.uniform(-1, 1, size=(1, 32)).astype(np.float32)
t0 = time.perf_counter()
for _ in range(1000):
    np.digitize(norm_state, bins=np.linspace(-1, 1, 257)[:-1]) - 1
print(f"Q2 digitize_ms={(time.perf_counter()-t0)/1000*1000:.4f}")


# Q3: 可分解性。三段：prefix(到"State: ") + 32 个带前导空格的 int + tail。
# 查表条目取 ids(" 12") 形态；首 int 紧跟 prefix 尾部空格，单独验证。
def ids_nospecial(text):
    out = tok(text, add_special_tokens=False, return_tensors=None)["input_ids"]
    return out[0] if isinstance(out[0], list) else out


t0 = time.perf_counter()
tab_sp = {v: ids_nospecial(" " + str(v)) for v in range(-255, 256)}  # 带前导空格
tab_bare = {v: ids_nospecial(str(v)) for v in range(-255, 256)}  # 无前导空格(串首)
print(f"Q3 table_build_ms={(time.perf_counter()-t0)*1000:.1f}")

# 先看结构样本
print(f"Q3 sample: sp[12]={tab_sp[12]} bare[12]={tab_bare[12]} sp[-3]={tab_sp[-3]} bare[-3]={tab_bare[-3]} sp[0]={tab_sp[0]} sp[255]={tab_sp[255]}")
lens = collections.Counter(len(v) for v in tab_sp.values())
print(f"Q3 sp_int_tok_len_dist={dict(lens)}")

# 候选 A: pre_ids + tab_bare[st[0]] + Σ tab_sp[rest] + tail_ids
pre = ids_nospecial(prefix)
tail_ids = ids_nospecial(tail)
ok_a = True
first_div = None
for st in states:
    full = ids_nospecial(make_prompt(st))
    cand = pre + tab_bare[st[0]] + [t for v in st[1:] for t in tab_sp[v]] + tail_ids
    if full != cand:
        ok_a = False
        for i, (x, y) in enumerate(zip(full, cand)):
            if x != y:
                first_div = (i, full[max(0, i - 4):i + 6], cand[max(0, i - 4):i + 6])
                break
        break
print(f"Q3 concatA_exact={ok_a} first_div={first_div}")

# 候选 B（若 A 失败）: 首元素也用 sp 表（prefix 以"State:"结尾不带空格变体）——
# 仅当 A 失败时才有意义,此处直接打印 prefix 尾部 token 供诊断
print(f"Q3 pre_tail_toks={pre[-4:]} tail_ids={tail_ids}")

# concat 本体成本（I9 每步的替代工作量）
st = states[5]
t0 = time.perf_counter()
for _ in range(10000):
    cand = pre + tab_bare[st[0]] + [t for v in st[1:] for t in tab_sp[v]] + tail_ids
print(f"Q3 concat_ms={(time.perf_counter()-t0)/10000*1000:.4f} len={len(cand)}")

# 长度分布（L 漂移 144/145 佐证：state 各位数字位数决定 L）
ls = []
for st in states:
    ls.append(len(ids_nospecial(make_prompt(st))))
print(f"Q3 prompt_len_dist={dict(collections.Counter(ls))}")
