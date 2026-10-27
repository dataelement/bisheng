#!/usr/bin/env python3
"""Draw a chart with matplotlib and put the SVG straight into an HTML page.

    import json, subprocess, sys
    spec = {"type": "line", "title": "月度营业收入", "unit": "亿元",
            "labels": ["1月", "2月", "3月"],
            "series": [{"name": "2025", "values": [1.2, 1.5, 1.4]},
                       {"name": "2026", "values": [1.6, 1.7, 1.9]}]}
    open("scratch/chart1.json", "w", encoding="utf-8").write(json.dumps(spec, ensure_ascii=False))
    r = subprocess.run([sys.executable, "skills/html-report/scripts/svg_chart.py",
                        "scratch/chart1.json", "--into", "output/report.html", "--slot", "chart1"],
                       capture_output=True, text=True)
    print(r.stdout); print(r.stderr)

The page must already contain the marker ``<!-- chart:chart1 -->`` where the chart
goes; the marker is replaced by a ``<figure>`` holding the inline SVG. Without
``--into`` the SVG is written to ``scratch/<spec name>.svg`` instead.

Why the script edits the page itself: a matplotlib SVG is 10-30 KB. Reading it back
and pasting it with edit_file would make the model re-emit all of it, which costs
far more time than drawing it.

Spec: ``type`` is ``bar`` / ``barh`` / ``line``; ``labels`` are the categories;
each series has ``name`` and ``values`` (same length as ``labels``); ``unit`` and
``title`` are optional.

Text stays text in the SVG (``svg.fonttype = none``), so the page's own font stack
renders the Chinese labels and no font file is embedded.

Always exits 0 and reports on stdout — the code executor discards stdout on a
non-zero exit.
"""

import argparse
import json
import os
import re
import sys
import warnings

PALETTE = ["#1f5f8b", "#c07a1a", "#2e7d4f", "#7a4f9a", "#b3261e", "#4a6572"]


# Families that carry CJK glyphs, in preference order. Labels stay text in the SVG
# and the browser draws them with the page's fonts; matplotlib only needs one of
# these to measure them, or layout is computed from fallback boxes.
_CJK_FAMILIES = (
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
    "Microsoft YaHei",
    "PingFang SC",
    "Hiragino Sans GB",
    "Heiti SC",
    "STHeiti",
    "Arial Unicode MS",
)


def _installed_cjk_fonts() -> list[str]:
    from matplotlib import font_manager

    installed = {f.name for f in font_manager.fontManager.ttflist}
    return [name for name in _CJK_FAMILIES if name in installed]


def build_svg(spec: dict) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["svg.fonttype"] = "none"
    plt.rcParams["font.family"] = ["sans-serif"]
    plt.rcParams["font.sans-serif"] = [*_installed_cjk_fonts(), "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    kind = spec.get("type", "bar")
    labels = [str(x) for x in spec["labels"]]
    series = spec["series"]
    for s in series:
        if len(s["values"]) != len(labels):
            raise ValueError(f"series {s.get('name')!r} has {len(s['values'])} values for {len(labels)} labels")

    fig, ax = plt.subplots(figsize=(8, 4.2 if kind != "barh" else max(2.4, 0.42 * len(labels) + 1)))
    n = len(series)
    if kind == "line":
        for i, s in enumerate(series):
            ax.plot(labels, s["values"], marker="o", linewidth=2, color=PALETTE[i % len(PALETTE)], label=s.get("name"))
    elif kind in ("bar", "barh"):
        width = 0.8 / n
        positions = range(len(labels))
        for i, s in enumerate(series):
            offs = [p - 0.4 + width * (i + 0.5) for p in positions]
            draw = ax.barh if kind == "barh" else ax.bar
            draw(offs, s["values"], width, color=PALETTE[i % len(PALETTE)], label=s.get("name"))
        if kind == "barh":
            ax.set_yticks(list(positions), labels)
            ax.invert_yaxis()
        else:
            ax.set_xticks(list(positions), labels)
    else:
        raise ValueError(f"unknown chart type {kind!r}; use bar, barh or line")

    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="x" if kind == "barh" else "y", color="#d9dee4", linewidth=0.8)
    ax.set_axisbelow(True)
    if spec.get("unit"):
        (ax.set_xlabel if kind == "barh" else ax.set_ylabel)(spec["unit"])
    if n > 1:
        ax.legend(frameon=False)
    fig.tight_layout()

    import io

    buf = io.StringIO()
    fig.savefig(buf, format="svg")
    plt.close(fig)
    svg = buf.getvalue()
    svg = svg[svg.index("<svg") :]
    # Scale with the container instead of a fixed point size.
    svg = re.sub(r'<svg([^>]*?)\swidth="[^"]*"\sheight="[^"]*"', r'<svg\1 width="100%"', svg, count=1)
    svg = re.sub(r"<metadata>.*?</metadata>", "", svg, flags=re.S)
    return svg


def figure_html(svg: str, title: str | None) -> str:
    caption = f"<figcaption>{title}</figcaption>" if title else ""
    return f'<figure class="chart" style="margin:16px 0;max-width:760px">{svg}{caption}</figure>'


def main() -> None:
    # Missing-glyph warnings go to stderr, which a zero exit discards anyway; they
    # only add noise when the script is run by hand.
    warnings.filterwarnings("ignore", message="Glyph .* missing from font")
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="JSON file with the chart spec")
    ap.add_argument("--into", help="HTML file holding the <!-- chart:<slot> --> marker")
    ap.add_argument("--slot", help="marker id inside the HTML file")
    args = ap.parse_args()
    try:
        with open(args.spec, encoding="utf-8") as f:
            spec = json.load(f)
        svg = build_svg(spec)
        block = figure_html(svg, spec.get("title"))
        if args.into:
            if not args.slot:
                print("FAILED: --into needs --slot")
                return
            marker = f"<!-- chart:{args.slot} -->"
            with open(args.into, encoding="utf-8") as f:
                page = f.read()
            if marker not in page:
                print(f"FAILED: {args.into} has no marker {marker}; add it where the chart goes, then rerun")
                return
            with open(args.into, "w", encoding="utf-8") as f:
                f.write(page.replace(marker, block, 1))
            print(f"OK: chart {args.slot} inserted into {args.into} ({len(block) // 1024} KB)")
        else:
            os.makedirs("scratch", exist_ok=True)
            out = os.path.join("scratch", os.path.splitext(os.path.basename(args.spec))[0] + ".svg")
            with open(out, "w", encoding="utf-8") as f:
                f.write(block)
            print(f"OK: chart written to {out} ({len(block) // 1024} KB)")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
    sys.exit(0)
