import pathlib
p = pathlib.Path('patterns.py')
t = p.read_text()
bad = "                  *[{}] for cts, ce, tts, te in hits]  # placeholder replaced below"
assert bad in t, "block not found"
lines = t.splitlines(keepends=True)
out = []
skip_next = False
for i, ln in enumerate(lines):
    if "ev = [{\"edge_id\": ce" in ln:
        # skip this line, the next two lines (continuation + bad line), keep following "ev = []"
        out.append("            ev = []\n")
        # skip until we pass the bad line
        # current ln is start; skip ln, next ln (reference...), next (bad)
        # mark to skip next 2
        skip_next = 2
        continue
    if skip_next > 0:
        skip_next -= 1
        continue
    out.append(ln)
p.write_text("".join(out))
print("patched")
