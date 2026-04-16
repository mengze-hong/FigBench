"""Generate comprehensive statistics report for FigBench dataset."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from database import get_conn
from collections import Counter

conn = get_conn()

# Basic counts
total_papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
total_figures = conn.execute("SELECT COUNT(*) FROM figures").fetchone()[0]

# By venue
venue_papers = conn.execute("SELECT venue, COUNT(*) as c FROM papers GROUP BY venue ORDER BY c DESC").fetchall()
venue_figures = conn.execute("""
    SELECT p.venue, COUNT(f.id) as c FROM figures f JOIN papers p ON f.paper_id=p.id 
    GROUP BY p.venue ORDER BY c DESC
""").fetchall()

# By layout
layout = conn.execute("SELECT layout_type, COUNT(*) as c FROM figures GROUP BY layout_type ORDER BY c DESC").fetchall()

# By figure_type
ftypes = conn.execute("SELECT figure_type, COUNT(*) as c FROM figures GROUP BY figure_type ORDER BY c DESC").fetchall()

# By venue x layout
venue_layout = conn.execute("""
    SELECT p.venue, f.layout_type, COUNT(*) as c 
    FROM figures f JOIN papers p ON f.paper_id=p.id 
    GROUP BY p.venue, f.layout_type ORDER BY p.venue, c DESC
""").fetchall()

# By venue x figure_type
venue_ftype = conn.execute("""
    SELECT p.venue, f.figure_type, COUNT(*) as c
    FROM figures f JOIN papers p ON f.paper_id=p.id
    GROUP BY p.venue, f.figure_type ORDER BY p.venue, c DESC
""").fetchall()

# Top tags
all_tags = conn.execute("SELECT tags FROM figures WHERE tags != '[]'").fetchall()
tag_counter = Counter()
for r in all_tags:
    for t in json.loads(r["tags"]):
        tag_counter[t] += 1

# Figures per paper distribution
fpp = conn.execute("""
    SELECT paper_id, COUNT(*) as c FROM figures GROUP BY paper_id
""").fetchall()
fpp_counts = [r["c"] for r in fpp]

# Avg figures per paper by venue
avg_fpp = conn.execute("""
    SELECT p.venue, ROUND(AVG(cnt), 2) as avg_figs FROM (
        SELECT paper_id, COUNT(*) as cnt FROM figures GROUP BY paper_id
    ) sub JOIN papers p ON sub.paper_id=p.id GROUP BY p.venue
""").fetchall()

conn.close()

# Build markdown
lines = []
lines.append("# FigBench Dataset Statistics\n")
lines.append(f"*Auto-generated report*\n")
lines.append(f"## Overview\n")
lines.append(f"| Metric | Count |")
lines.append(f"|--------|-------|")
lines.append(f"| **Total Papers** | {total_papers} |")
lines.append(f"| **Total Figures** | {total_figures} |")
lines.append(f"| **Figures / Paper** | {total_figures/total_papers:.2f} |")
lines.append(f"| **Min figs/paper** | {min(fpp_counts)} |")
lines.append(f"| **Max figs/paper** | {max(fpp_counts)} |")
lines.append(f"| **Median figs/paper** | {sorted(fpp_counts)[len(fpp_counts)//2]} |")
lines.append("")

lines.append("## By Venue\n")
lines.append("| Venue | Papers | Figures | Avg Figs/Paper |")
lines.append("|-------|--------|---------|----------------|")
vp_dict = {r["venue"]: r["c"] for r in venue_papers}
vf_dict = {r["venue"]: r["c"] for r in venue_figures}
va_dict = {r["venue"]: r["avg_figs"] for r in avg_fpp}
for v in vp_dict:
    p = vp_dict.get(v, 0)
    f = vf_dict.get(v, 0)
    a = va_dict.get(v, 0)
    lines.append(f"| {v} | {p} | {f} | {a} |")
lines.append("")

lines.append("## By Layout Type\n")
lines.append("| Layout | Count | % |")
lines.append("|--------|-------|---|")
for r in layout:
    lt = r["layout_type"] or "(unlabeled)"
    pct = r["c"] / total_figures * 100
    lines.append(f"| {lt} | {r['c']} | {pct:.1f}% |")
lines.append("")

lines.append("## By Figure Type\n")
lines.append("| Figure Type | Count | % |")
lines.append("|-------------|-------|---|")
for r in ftypes:
    pct = r["c"] / total_figures * 100
    lines.append(f"| {r['figure_type']} | {r['c']} | {pct:.1f}% |")
lines.append("")

lines.append("## Venue × Layout\n")
lines.append("| Venue | Layout | Count |")
lines.append("|-------|--------|-------|")
for r in venue_layout:
    lt = r["layout_type"] or "(unlabeled)"
    lines.append(f"| {r['venue']} | {lt} | {r['c']} |")
lines.append("")

lines.append("## Venue × Figure Type\n")
lines.append("| Venue | Figure Type | Count |")
lines.append("|-------|-------------|-------|")
for r in venue_ftype:
    lines.append(f"| {r['venue']} | {r['figure_type']} | {r['c']} |")
lines.append("")

lines.append("## Top 30 Tags\n")
lines.append("| Rank | Tag | Count | % |")
lines.append("|------|-----|-------|---|")
for i, (tag, cnt) in enumerate(tag_counter.most_common(30)):
    pct = cnt / total_figures * 100
    lines.append(f"| {i+1} | {tag} | {cnt} | {pct:.1f}% |")
lines.append("")

lines.append("## Figures Per Paper Distribution\n")
dist = Counter(fpp_counts)
lines.append("| Figs/Paper | Papers | % |")
lines.append("|------------|--------|---|")
for k in sorted(dist.keys()):
    pct = dist[k] / total_papers * 100
    lines.append(f"| {k} | {dist[k]} | {pct:.1f}% |")
lines.append("")

report = "\n".join(lines)
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "STATISTICS.md")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(report)

print(report)
print(f"\nSaved to {os.path.abspath(out_path)}")
