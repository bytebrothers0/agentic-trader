"""Inspect the last tester log: how many genetic passes ran, and the run timeline."""
import os
import re

base = os.path.join(os.environ["APPDATA"], "MetaQuotes", "Terminal",
                    "D0E8209F77C8CF37AD8BF550E51FF075", "Tester", "logs")
log = os.path.join(base, "20261112.log")
raw = open(log, "rb").read()
for enc in ("utf-16", "utf-8", "cp1252"):
    try:
        text = raw.decode(enc)
        break
    except (UnicodeDecodeError, UnicodeError):
        continue

lines = text.splitlines()
print(f"total lines: {len(lines)}")

# collect tester-level (non-bar) events: wall-time lines from the Tester component
events = []
for ln in lines:
    m = re.match(r"([A-Z]{2})\t0\t(\d\d:\d\d:\d\d\.\d+)\t(Tester|Core 1)\t(.{0,110})", ln)
    if m:
        events.append(m.groups())

# find the last optimization start
starts = [i for i, e in enumerate(events) if "optimization" in e[3].lower()
          or "automatic testing" in e[3].lower()]
print("last 6 start/stop events:")
for i in starts[-6:]:
    print(f"  [{events[i][1]}] {events[i][3]}")

# passes: lines with 'pass ' from the last optimization start onward
last_start = 0
for i, e in enumerate(events):
    if "optimization started" in e[3].lower() or "automatic testing started" in e[3].lower():
        last_start = i
passes = [e for e in events[last_start:] if re.search(r"pass\s*\d+", e[3], re.I)]
print(f"\npasses since last start: {len(passes)}")
for e in passes[:5]:
    print(f"  [{e[1]}] {e[3]}")
if len(passes) > 5:
    print("  ...")
    for e in passes[-3:]:
        print(f"  [{e[1]}] {e[3]}")

# also show raw non-MSNR core lines around the run end
tail = [e for e in events[last_start:] if "MSNR" not in e[3]][:60]
print("\nrun timeline (non-MSNR):")
for e in tail:
    print(f"  [{e[1]}] {e[3]}")
