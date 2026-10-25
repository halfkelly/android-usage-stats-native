"""Write data.js for check.html: the day files of a phone inbox, inlined."""
import json
import sys
from pathlib import Path

src = Path(sys.argv[1]) / "events"
files = {p.name: p.read_text() for p in sorted(src.glob("events-*.csv"))}
out = Path(__file__).with_name("data.js")
out.write_text("window.__files = " + json.dumps(files) + ";\n")
print(f"{len(files)} day files -> {out}")
