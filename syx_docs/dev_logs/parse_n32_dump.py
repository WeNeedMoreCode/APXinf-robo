import glob
import re

files = sorted(glob.glob("/tmp/n32d2/pid_*/ge_proto_00000003_graph_0_AfterInfershape.txt"))
txt = open(files[0]).read()
blocks = txt.split("op {")
for b in blocks:
    t = re.search(r'type: "(\w+)"', b)
    if not t:
        continue
    tn = t.group(1)
    if tn not in ("MatMulV2", "Mul", "Cast", "ReduceSumD", "RealDiv", "Sqrt", "TileD"):
        continue
    nm = re.search(r'name: "([^"]+)"', b)
    dims = [l.strip() for l in b.splitlines() if l.strip().startswith(("dim:", "dtype:"))]
    print(f"{nm.group(1) if nm else '?':26s} {tn:12s} {dims[:6]}")
