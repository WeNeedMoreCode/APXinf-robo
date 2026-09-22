from collections import Counter

from safetensors.numpy import load_file

t = load_file("/data/apxinf/replay/replay_t0.safetensors")
n = sum(1 for k in t if k.startswith("noise_"))
lens = [t[f"token_ids_{i}"].shape[0] for i in range(n)]
nz = [int((t[f"token_ids_{i}"] != 0).sum()) for i in range(n)]
print("frames", n, "stored_len", Counter(lens).most_common(), "nonzero", Counter(nz).most_common())
