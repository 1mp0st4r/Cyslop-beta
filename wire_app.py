import pathlib
p = pathlib.Path("nexusfront/src/App.tsx")
t = p.read_text(encoding="utf-8")
if "Findings" not in t:
    t = t.replace("import AuditLog from '@/pages/AuditLog';",
                  "import AuditLog from '@/pages/AuditLog';\nimport Findings from '@/pages/Findings';")
    t = t.replace("{item('/review', 'Evidence Review', ClipboardList)}",
                  "{item('/review', 'Evidence Review', ClipboardList)}\n          {item('/findings', 'Findings', Radar)}")
    t = t.replace("import { Grid2X2, Network, ClipboardList, ScrollText, LogOut, Menu } from 'lucide-react';",
                  "import { Grid2X2, Network, ClipboardList, ScrollText, LogOut, Menu, Radar } from 'lucide-react';")
    t = t.replace('<Route path="/audit"><Shell /></Route>',
                  '<Route path="/audit"><Shell /></Route>\n          <Route path="/findings"><Shell /></Route>')
    t = t.replace('<Route path="/audit" component={AuditLog} />',
                  '<Route path="/audit" component={AuditLog} />\n          <Route path="/findings" component={Findings} />')
    p.write_text(t, encoding="utf-8")
    print("App.tsx patched")
else:
    print("App.tsx already wired")
