import pathlib
p = pathlib.Path("patterns.py")
t = p.read_text(encoding="utf-8")
t = t.replace("\u2192", "->").replace("\u2194", "<->")
p.write_text(t, encoding="utf-8")
print("arrows ascii-fied")

v = pathlib.Path("verify_patterns.py")
t = v.read_text(encoding="utf-8")
t = t.replace(
    'print("-", f["rule_id"], f["severity"], f["entity_ids"], "|", f["explanation"][:110])',
    'print(("-", f["rule_id"], f["severity"], f["entity_ids"], "|", f["explanation"][:110]))',
)
# make stdout utf-8 safe regardless
t = t.replace(
    "import database",
    "import sys, io\ntry:\n    sys.stdout.reconfigure(encoding='utf-8')\nexcept Exception:\n    pass\nimport database",
)
v.write_text(t, encoding="utf-8")
print("verify patched")
