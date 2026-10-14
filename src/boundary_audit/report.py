"""Portable offline report with explicit coverage and decoder provenance."""

import json
from html import escape
from pathlib import Path

from .storage import write_json


def write_reports(report, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "report.json", report)
    selection = report["selection"]
    selected = len(selection["checked_cameras"])
    declared = len(selection["declared_cameras"])
    consumer = report.get("consumer_verification", {})
    rows = "".join(
        f"<tr data-severity='{escape(f['severity'])}'><td>{escape(f['code'])}</td><td>{escape(f['severity'])}</td><td>{escape(str(f.get('episode_index', '')))}</td><td>{escape(f['message'])}</td></tr>"
        for f in report["findings"]
    )
    evidence = "".join(
        f"<tr><td>{escape(q['camera'])}</td><td>{q['episode_index']}</td><td>{q['frame_index']}</td><td>{q['request_seconds']:.9f}</td><td>{q['video_pts_seconds']:.9f}</td><td>{q['deviation_seconds']:.7g}</td></tr>"
        for q in report["boundary_queries"]
    )
    videos = []
    for video in report["video_reports"]:
        points = video["deviation_points"]
        xmax = max(video["samples"] - 1, 1)
        ymax = max((abs(p["deviation_ticks"]) for p in points), default=1) or 1
        plot = " ".join(
            f"{20 + p['sample'] / xmax * 600:.1f},{70 - p['deviation_ticks'] / ymax * 45:.1f}" for p in points
        )
        videos.append(
            f"<article><h3>{escape(video['path'])}</h3><p>{video['samples']:,} samples · max deviation {video['max_abs_deviation_seconds']:.7g} s · first affected sample {video['first_deviation_sample']}</p><svg viewBox='0 0 640 140' role='img' aria-label='PTS deviation in ticks'><path d='M20 70H620' stroke='#ccd5e2'/><polyline points='{plot}' fill='none' stroke='#2376b7' stroke-width='2'/><text x='20' y='132' font-size='12'>Sample order → · deviation in ticks · up to 128 representative points</text></svg></article>"
        )
    consumer_summary = {k: v for k, v in consumer.items() if k != "records"}
    source = report.get("sample_source", {})
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>LeRobot boundary audit</title>
<style>body{{max-width:1180px;margin:32px auto;padding:0 22px;font:15px system-ui;color:#172a40;background:#f5f7fb}}h1{{font-size:30px}}.cards{{display:flex;flex-wrap:wrap;gap:14px}}article,.card,details{{background:white;border:1px solid #dce3ed;border-radius:10px;padding:18px;margin:16px 0}}.card{{min-width:180px}}.card b{{display:block;font-size:25px}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{text-align:left;padding:9px;border-bottom:1px solid #e2e8f0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.scroll{{overflow:auto}}svg{{width:100%;max-height:170px}}select{{padding:8px}}summary{{cursor:pointer;font-weight:600}}h3{{overflow-wrap:anywhere}}</style></head><body>
<h1>Episode boundary audit: {escape(report["status"].upper())}</h1><p>{escape(report["scope"])}</p>
<div class="cards"><div class="card"><b>{selected} / {declared}</b>camera streams checked</div><div class="card"><b>{report["coverage"]["metadata_episodes"]}</b>episodes</div><div class="card"><b>{report["coverage"]["data_rows"]:,}</b>data rows scanned</div><div class="card"><b>{report["coverage"]["boundary_queries"]}</b>boundary queries</div></div>
<p><strong>PASS applies only to selected cameras.</strong> Unselected: {escape(", ".join(selection["unselected_cameras"]) or "none")}. Local PyAV: {escape(report["decoder"]["status"])}. Official consumer: {escape(consumer.get("status", "not requested"))}.</p>
<details><summary>Source, scope and versions</summary><pre>{escape(json.dumps({"source": source, "selection": selection, "coverage": report["coverage"], "official_consumer": consumer_summary}, indent=2, ensure_ascii=False))}</pre></details>
<h2>Video timeline evidence</h2>{"".join(videos)}
<h2>Findings ({sum(report.get("finding_counts", {}).values())})</h2><label>Severity <select id="severity"><option value="all">All</option><option>error</option><option>review</option><option>unverified</option></select></label><p>Shown {len(report["findings"])}; omitted {report.get("findings_truncated_count", 0)}.</p><div class="scroll"><table id="findings"><thead><tr><th>Code</th><th>Severity</th><th>Episode</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Limits</h2><ul>{"".join("<li>" + escape(x) + "</li>" for x in report["limitations"])}</ul>
<details><summary>Boundary queries: first, second and last stored row</summary><div class="scroll"><table><tr><th>Camera</th><th>Episode</th><th>Frame</th><th>Stored request (s)</th><th>Expected PTS (s)</th><th>Distance (s)</th></tr>{evidence}</table></div></details>
<script>document.getElementById('severity').addEventListener('change',function(){{document.querySelectorAll('#findings tbody tr').forEach(r=>{{r.hidden=this.value!=='all'&&r.dataset.severity!==this.value;}});}});</script></body></html>"""
    (output / "report.html").write_text(html, encoding="utf-8")


def write_probe_html(report, path):
    """Show the actual query evidence and ambiguity, without remote assets."""
    rows = []
    for record in report.get("records", []):
        cells = [record.get(k, "") for k in ("index", "camera", "delta", "expected_sample", "matched_sample", "status", "reason")]
        rows.append("<tr>" + "".join("<td>" + escape(str(v)) + "</td>" for v in cells) + "</tr>")
    summary = {k: v for k, v in report.items() if k != "records"}
    content = '<!doctype html><html lang="en"><meta charset="utf-8"><title>Real footage loader probe</title><style>body{font:15px system-ui;margin:32px;max-width:1200px}table{border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #ddd}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
    content += "<h1>Real footage loader probe: " + escape(report["status"].upper()) + "</h1>"
    content += "<p>Comparison against sequential ordinal decode. Repeated or indistinguishable frames are unverified. No original sensor identity or physical synchronization guarantee.</p>"
    content += "<details><summary>Scope, budgets, versions and row evidence</summary><pre>" + escape(json.dumps(summary, indent=2, ensure_ascii=False)) + "</pre></details>"
    content += "<table><tr><th>Row</th><th>Camera</th><th>Delta</th><th>Expected sample</th><th>Matched sample</th><th>Status</th><th>Reason</th></tr>" + "".join(rows) + "</table></html>"
    Path(path).write_text(content, encoding="utf-8")
