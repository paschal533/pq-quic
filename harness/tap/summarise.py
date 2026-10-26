"""Print a compact summary of decode_initial.py output (reads JSON on stdin)."""
import json
import sys

r = json.load(sys.stdin)
for d in ("c2s", "s2c"):
    x = r[d]
    print(d, {k: x[k] for k in ("datagrams", "bytes", "initial_datagrams", "initial_bytes")})
    for h in x["hellos"]:
        print("   ", json.dumps(h))
