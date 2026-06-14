import io
import re
import json
import base64

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import requests

from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

# ---------------------------------------------------------------------------
# Color schemes
# ---------------------------------------------------------------------------

COLOR_SCHEMES = {
    'default':    ['#4361ee', '#06d6a0', '#ffd166', '#ef476f', '#118ab2', '#8338ec', '#fb5607', '#3a86ff'],
    'vibrant':    ['#ff6b6b', '#feca57', '#48dbfb', '#ff9ff3', '#54a0ff', '#5f27cd', '#00d2d3', '#ff9f43'],
    'pastel':     ['#a8dadc', '#ffd6a5', '#fdffb6', '#caffbf', '#9bf6ff', '#bde0fe', '#ffc8dd', '#cdb4db'],
    'cool':       ['#03045e', '#0077b6', '#0096c7', '#00b4d8', '#48cae4', '#90e0ef', '#ade8f4', '#023e8a'],
    'warm':       ['#d62828', '#f77f00', '#fcbf49', '#e63946', '#c1121f', '#780000', '#ffd60a', '#fb8500'],
    'green':      ['#1b4332', '#2d6a4f', '#40916c', '#52b788', '#74c69d', '#95d5b2', '#b7e4c7', '#081c15'],
    'monochrome': ['#212529', '#495057', '#6c757d', '#868e96', '#adb5bd', '#ced4da', '#343a40', '#dee2e6'],
    'sunset':     ['#f72585', '#b5179e', '#7209b7', '#560bad', '#480ca8', '#3a0ca3', '#3f37c9', '#4361ee'],
}

SCHEME_PREVIEWS = {k: v[:3] for k, v in COLOR_SCHEMES.items()}

# ---------------------------------------------------------------------------
# Text / log extraction
# ---------------------------------------------------------------------------

def _extract_numbers_from_text(content):
    lines = [l.strip() for l in content.strip().splitlines() if l.strip()]
    if not lines:
        return None, None

    kv_re = re.compile(
        r'(?<!\w)([A-Za-z][A-Za-z0-9_]*(?:\s+[A-Za-z][A-Za-z0-9_]*)*)\s*[:=]\s*(-?\d+\.?\d*(?:[eE][+-]?\d+)?)(?:\s*[%°])?'
    )
    idx_re = re.compile(
        r'\b(epoch|step|iter(?:ation)?|trial|round|batch|sample|fold|run)\s+(\d+)',
        re.IGNORECASE
    )

    records = []
    for line in lines:
        pairs = kv_re.findall(line)
        idx_m = idx_re.search(line)
        if pairs:
            record = {}
            if idx_m:
                record[idx_m.group(1).title()] = int(idx_m.group(2))
            for raw_key, val in pairs:
                key = raw_key.strip()
                if re.match(r'^(?:epoch|step|iter(?:ation)?|trial|round|batch|sample|fold|run)$',
                            key, re.IGNORECASE):
                    continue
                record[key] = float(val)
            if record:
                records.append(record)

    if len(records) >= 2 and len({k for r in records for k in r}) >= 2:
        return pd.DataFrame(records), 'extracted'

    ln_re = re.compile(r'^([A-Za-z][A-Za-z0-9_\s\-]*?)\s{1,5}(-?\d+\.?\d*)\s*$')
    pairs2 = []
    for line in lines:
        m = ln_re.match(line)
        if m:
            pairs2.append({'Category': m.group(1).strip(), 'Value': float(m.group(2))})
    if len(pairs2) >= 2:
        return pd.DataFrame(pairs2), 'extracted'

    nums = []
    for line in lines:
        found = re.findall(r'-?\d+\.?\d*(?:[eE][+-]?\d+)?', line)
        if found:
            nums.append(float(found[0]))
    if len(nums) >= 2:
        return pd.DataFrame({'Index': range(1, len(nums) + 1), 'Value': nums}), 'extracted'

    return None, None


# ---------------------------------------------------------------------------
# Column classification
# ---------------------------------------------------------------------------

def _is_likely_time(series):
    sample = series.dropna().astype(str).head(20)
    hits = sum(1 for v in sample if pd.notna(pd.to_datetime(v, errors='coerce')))
    return hits / max(len(sample), 1) >= 0.8


def classify_columns(df):
    numeric, categorical, temporal = [], [], []
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            numeric.append(col)
        elif _is_likely_time(df[col]):
            temporal.append(col)
        else:
            categorical.append(col)
    return numeric, categorical, temporal


# ---------------------------------------------------------------------------
# Graph suggestion (32 types, returns top 8)
# ---------------------------------------------------------------------------

def suggest_graphs(df):
    numeric, categorical, temporal = classify_columns(df)
    n_rows  = len(df)
    n_num   = len(numeric)
    n_cat   = len(categorical)
    n_tmp   = len(temporal)
    suggestions = []

    def add(p, gtype, name, **kw):
        suggestions.append(dict(priority=p, type=gtype, name=name, **kw))

    # ── Time series ──────────────────────────────────────────────────────────
    if n_tmp >= 1 and n_num >= 1:
        xt = temporal[0]
        add(96, 'line',        'Line Chart',     x=xt, y=numeric[0])   # #1 for time data
        add(80, 'area',        'Area Chart',     x=xt, y=numeric[0])
        add(68, 'step',        'Step Chart',     x=xt, y=numeric[0])
        if n_rows >= 5:
            add(64, 'moving_avg', 'Moving Average', x=xt, y=numeric[0])
        if n_num >= 2:
            add(84, 'multi_line', 'Multi-Line',  x=xt, ys=numeric[:5])
            add(66, 'dual_axis',  'Dual Axis',   x=xt, y1=numeric[0], y2=numeric[1])
            add(60, 'filled_area','Filled Area', x=xt, y1=numeric[0], y2=numeric[1])

    # ── Categorical + Numeric ────────────────────────────────────────────────
    if n_cat >= 1 and n_num >= 1:
        xc, yc = categorical[0], numeric[0]
        nc = df[xc].nunique()
        add(98, 'bar',            'Bar Chart',       x=xc, y=yc)   # most common
        if nc <= 9:
            add(88, 'pie',   'Pie Chart',   labels=xc, values=yc)  # 2nd for small cats
            add(70, 'donut', 'Donut Chart', labels=xc, values=yc)
        add(66, 'horizontal_bar', 'Horizontal Bar',  x=xc, y=yc)
        add(62, 'dot_plot',       'Lollipop Chart',  x=xc, y=yc)
        add(57, 'error_bar',      'Error Bar Chart', x=xc, y=yc)
        add(53, 'pareto',         'Pareto Chart',    x=xc, y=yc)
        if df.groupby(xc).size().max() > 1:
            add(65, 'box_cat',    'Box by Category',    x=xc, y=yc)
            add(60, 'violin_cat', 'Violin by Category', x=xc, y=yc)
            add(55, 'strip',      'Strip Plot',         x=xc, y=yc)
        if n_num >= 2:
            add(74, 'grouped_bar', 'Grouped Bar',   x=xc, ys=numeric[:5])
            add(68, 'stacked_bar', 'Stacked Bar',   x=xc, ys=numeric[:5])
            add(56, 'heatmap_cat', 'Pivot Heatmap', x=xc, ys=numeric)
        if n_num >= 3:
            add(58, 'radar', 'Radar Chart', x=xc, cols=numeric[:6])

    # ── Numeric only: sequential / pair relationships ─────────────────────
    if n_num >= 2:
        add(94, 'scatter',    'Scatter Plot', x=numeric[0], y=numeric[1])  # #1 for 2 nums
        add(70, 'regression', 'Regression',   x=numeric[0], y=numeric[1])
        if n_rows >= 10:
            add(60, 'hexbin', 'Hexbin Density', x=numeric[0], y=numeric[1])
        if n_num >= 3:
            add(58, 'bubble', 'Bubble Chart', x=numeric[0], y=numeric[1], size=numeric[2])
        if not (n_cat or n_tmp):
            add(92, 'line',        'Line Chart',    x=numeric[0], y=numeric[1])
            add(78, 'area',        'Area Chart',    x=numeric[0], y=numeric[1])
            add(65, 'step',        'Step Chart',    x=numeric[0], y=numeric[1])
            if n_rows >= 5:
                add(62, 'moving_avg', 'Moving Average', x=numeric[0], y=numeric[1])
            if n_num >= 3:
                add(82, 'multi_line', 'Multi-Line', x=numeric[0], ys=numeric[1:5])
                add(60, 'filled_area','Filled Area', x=numeric[0], y1=numeric[1],
                    y2=numeric[min(2, n_num-1)])
            if n_num >= 2:
                add(63, 'dual_axis', 'Dual Axis', x=numeric[0], y1=numeric[1],
                    y2=numeric[min(2, n_num-1)])

    # ── Distributions ────────────────────────────────────────────────────────
    if n_num >= 1:
        add(86, 'histogram',  'Histogram',     col=numeric[0])  # boosted: very common
        add(62, 'kde',        'Density (KDE)', col=numeric[0])
        add(55, 'cumulative', 'CDF',           col=numeric[0])
        if n_rows >= 4:
            add(48, 'stem',      'Stem Plot',  col=numeric[0])
        if n_rows >= 3:
            add(45, 'waterfall', 'Waterfall',  col=numeric[0])

    if n_num >= 2 and n_rows >= 5:
        add(63, 'box',    'Box Plot',    cols=numeric[:6])
        add(56, 'violin', 'Violin Plot', cols=numeric[:6])

    # ── Multi-numeric overview ────────────────────────────────────────────────
    if n_num >= 3:
        add(60, 'heatmap',     'Correlation Heatmap', cols=numeric)
    if n_num >= 3 and n_rows >= 4:
        add(52, 'pair_scatter', 'Scatter Matrix',      cols=numeric[:4])

    # Deduplicate by type, keeping highest priority
    seen = {}
    for s in sorted(suggestions, key=lambda s: s['priority'], reverse=True):
        if s['type'] not in seen:
            seen[s['type']] = s

    ordered = sorted(seen.values(), key=lambda s: s['priority'], reverse=True)
    return ordered[:8]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _theme(opts):
    dark = opts.get('bg_style') == 'dark'
    return {
        'colors':  COLOR_SCHEMES.get(opts.get('color_scheme', 'default'), COLOR_SCHEMES['default']),
        'fig_bg':  '#14161a' if dark else 'white',
        'ax_bg':   '#1c1f26' if dark else '#f8f9fe',
        'fg':      '#e8eaf0' if dark else '#212529',
        'muted':   '#8b8fa8' if dark else '#6c757d',
        'spine_c': '#2e3244' if dark else '#dee2e6',
        'grid_c':  '#252838' if dark else '#e9ecef',
        'dark':    dark,
    }


def _style_base(ax, t):
    ax.set_facecolor(t['ax_bg'])
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color(t['spine_c'])
    ax.spines['bottom'].set_color(t['spine_c'])
    ax.tick_params(colors=t['muted'])


def _apply_opts(ax, opts, t, default_title='', default_xlabel='', default_ylabel='',
                skip_labels=False, font_size=10, show_grid=False, show_legend=True,
                has_legend=False):
    title  = opts.get('title',  '').strip() or default_title
    xlabel = opts.get('xlabel', '').strip() or default_xlabel
    ylabel = opts.get('ylabel', '').strip() or default_ylabel
    if title:
        ax.set_title(title, fontsize=font_size + 2, fontweight='bold',
                     color=t['fg'], pad=12)
    if not skip_labels:
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=font_size, color=t['muted'], labelpad=8)
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=font_size, color=t['muted'], labelpad=8)
    if show_grid:
        ax.grid(True, color=t['grid_c'], alpha=0.8, linewidth=0.6, zorder=0)
    else:
        ax.grid(False)
    ax.tick_params(colors=t['muted'], labelsize=font_size - 1)
    if show_legend and has_legend:
        leg = ax.get_legend()
        if leg:
            leg.set_frame_on(True)
            leg.get_frame().set_facecolor(t['ax_bg'])
            leg.get_frame().set_edgecolor(t['spine_c'])
            for text in leg.get_texts():
                text.set_color(t['fg'])
                text.set_fontsize(font_size - 1)
    elif not show_legend:
        leg = ax.get_legend()
        if leg:
            leg.remove()


def _save(fig, fmt, fig_bg, dpi=150):
    buf = io.BytesIO()
    kw = dict(bbox_inches='tight', facecolor=fig_bg)
    if fmt == 'jpeg':
        kw['pil_kwargs'] = {'quality': 95}
    plt.savefig(buf, format=fmt, dpi=dpi if fmt != 'svg' else 96, **kw)
    buf.seek(0)
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Main render dispatcher
# ---------------------------------------------------------------------------

def render_graph(df, cfg, opts=None, fmt='png'):
    opts  = opts or {}
    t     = _theme(opts)
    fs    = int(opts.get('font_size', 10))
    grid  = bool(opts.get('show_grid', False))
    leg   = bool(opts.get('show_legend', True))
    gtype = cfg['type']
    C     = t['colors']

    # ── Special multi-subplot charts ─────────────────────────────────────────
    if gtype == 'pair_scatter':
        cols = cfg['cols'][:4]
        n    = len(cols)
        fig, axes = plt.subplots(n, n, figsize=(max(7, n * 2.4), max(7, n * 2.4)),
                                 facecolor=t['fig_bg'], squeeze=False)
        for i in range(n):
            for j in range(n):
                ax2 = axes[i][j]
                _style_base(ax2, t)
                ax2.tick_params(colors=t['muted'], labelsize=5)
                if i == j:
                    ax2.hist(df[cols[i]].dropna(), bins=12,
                             color=C[i % len(C)], alpha=0.85, edgecolor=t['fig_bg'])
                else:
                    ax2.scatter(df[cols[j]], df[cols[i]],
                                color=C[j % len(C)], alpha=0.5, s=10)
                if i == n - 1:
                    ax2.set_xlabel(cols[j], fontsize=6, color=t['muted'])
                if j == 0:
                    ax2.set_ylabel(cols[i], fontsize=6, color=t['muted'],
                                   rotation=45, ha='right', labelpad=14)
        title = opts.get('title', '').strip() or 'Scatter Matrix'
        plt.suptitle(title, fontsize=fs + 2, fontweight='bold',
                     color=t['fg'], y=1.01)
        plt.tight_layout(pad=0.4)
        return _save(fig, fmt, t['fig_bg'], dpi=130)

    if gtype == 'radar':
        cols = cfg['cols']
        n    = len(cols)
        if n < 3:
            raise ValueError('Radar needs ≥ 3 numeric columns')
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
        angles += angles[:1]
        fig, ax = plt.subplots(figsize=(7, 7), facecolor=t['fig_bg'],
                               subplot_kw=dict(polar=True))
        ax.set_facecolor(t['ax_bg'])
        ax.spines['polar'].set_color(t['spine_c'])
        ax.grid(color=t['grid_c'], linewidth=0.5, alpha=0.7)
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(cols, color=t['fg'], fontsize=fs - 1)
        ax.yaxis.set_tick_params(labelcolor=t['muted'])

        col_max = df[cols].max()
        col_min = df[cols].min()
        col_rng = (col_max - col_min).replace(0, 1)
        x_col   = cfg.get('x')
        if x_col:
            groups = df.groupby(x_col)[cols].mean()
            for i, (idx, row) in enumerate(groups.head(8).iterrows()):
                norm = ((row - col_min) / col_rng).values.tolist() + [0]
                norm[-1] = norm[0]
                c = C[i % len(C)]
                ax.plot(angles, norm, color=c, linewidth=2, label=str(idx))
                ax.fill(angles, norm, color=c, alpha=0.12)
        else:
            for i, (_, row) in enumerate(df[cols].head(5).iterrows()):
                norm = ((row - col_min) / col_rng).values.tolist()
                norm += norm[:1]
                c = C[i % len(C)]
                ax.plot(angles, norm, color=c, linewidth=2)
                ax.fill(angles, norm, color=c, alpha=0.12)
        ax.set_ylim(0, 1)
        title = opts.get('title', '').strip() or 'Radar Chart'
        ax.set_title(title, fontsize=fs + 2, fontweight='bold', color=t['fg'], pad=20)
        if x_col and leg:
            ax.legend(loc='upper right', bbox_to_anchor=(1.35, 1.1),
                      fontsize=fs - 1, labelcolor=t['fg'],
                      facecolor=t['ax_bg'], edgecolor=t['spine_c'])
        plt.tight_layout()
        return _save(fig, fmt, t['fig_bg'])

    # ── All single-axis charts ────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 5.5), facecolor=t['fig_bg'])
    _style_base(ax, t)

    rotate_x   = False
    dtitle = dxlabel = dylabel = ''
    has_legend_data = False

    try:
        # ── BAR ────────────────────────────────────────────────────────────────
        if gtype == 'bar':
            g = df.groupby(cfg['x'])[cfg['y']].mean()
            ax.bar(g.index.astype(str), g.values,
                   color=[C[i % len(C)] for i in range(len(g))],
                   edgecolor=t['fig_bg'], linewidth=0.6)
            dtitle = f'{cfg["y"]} by {cfg["x"]}'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = True

        # ── HORIZONTAL BAR ──────────────────────────────────────────────────────
        elif gtype == 'horizontal_bar':
            g = df.groupby(cfg['x'])[cfg['y']].mean().sort_values()
            ax.barh(g.index.astype(str), g.values,
                    color=[C[i % len(C)] for i in range(len(g))],
                    edgecolor=t['fig_bg'], linewidth=0.5)
            dtitle = f'{cfg["y"]} by {cfg["x"]}'; dxlabel = cfg['y']; dylabel = cfg['x']

        # ── DOT / LOLLIPOP ──────────────────────────────────────────────────────
        elif gtype == 'dot_plot':
            g = df.groupby(cfg['x'])[cfg['y']].mean()
            labels = g.index.astype(str).tolist()
            vals   = g.values
            for i, val in enumerate(vals):
                ax.hlines(i, 0, val, colors=C[i % len(C)], linewidth=2, alpha=0.7)
                ax.scatter(val, i, color=C[i % len(C)], s=90, zorder=5)
            ax.set_yticks(range(len(labels)))
            ax.set_yticklabels(labels, fontsize=fs - 1, color=t['muted'])
            dtitle = f'{cfg["y"]} — {cfg["x"]}'; dxlabel = cfg['y']

        # ── ERROR BAR ───────────────────────────────────────────────────────────
        elif gtype == 'error_bar':
            g = df.groupby(cfg['x'])[cfg['y']].agg(['mean', 'std']).reset_index()
            labels = g[cfg['x']].astype(str).tolist()
            means  = g['mean'].values
            stds   = g['std'].fillna(0).values
            xp = range(len(labels))
            ax.bar(xp, means,
                   color=[C[i % len(C)] for i in range(len(g))],
                   edgecolor=t['fig_bg'], alpha=0.85)
            ax.errorbar(xp, means, yerr=stds, fmt='none',
                        color=t['fg'], capsize=6, capthick=2, elinewidth=2)
            ax.set_xticks(xp)
            ax.set_xticklabels(labels)
            dtitle = f'{cfg["y"]} Mean ± Std by {cfg["x"]}'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = True

        # ── PARETO ──────────────────────────────────────────────────────────────
        elif gtype == 'pareto':
            g    = df.groupby(cfg['x'])[cfg['y']].sum().sort_values(ascending=False)
            cumx = (g.cumsum() / g.sum() * 100).values
            xp   = range(len(g))
            ax.bar(xp, g.values,
                   color=[C[i % len(C)] for i in range(len(g))],
                   edgecolor=t['fig_bg'])
            ax.set_xticks(xp); ax.set_xticklabels(g.index.astype(str))
            ax2 = ax.twinx()
            ax2.plot(xp, cumx, color=C[3 % len(C)], linewidth=2.5,
                     marker='o', markersize=5)
            ax2.axhline(80, color=C[3 % len(C)], linestyle='--', linewidth=1, alpha=0.5)
            ax2.set_ylim(0, 112)
            ax2.set_ylabel('Cumulative %', color=C[3 % len(C)], fontsize=fs)
            ax2.tick_params(colors=C[3 % len(C)], labelsize=fs - 1)
            ax2.spines['right'].set_color(C[3 % len(C)])
            ax2.spines['top'].set_visible(False)
            ax2.spines['left'].set_visible(False)
            ax2.spines['bottom'].set_visible(False)
            dtitle = f'Pareto — {cfg["y"]}'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = True

        # ── WATERFALL ───────────────────────────────────────────────────────────
        elif gtype == 'waterfall':
            vals = df[cfg['col']].dropna().values[:30]
            running = 0
            bot, hgt, bcolors = [], [], []
            pos_c, neg_c = C[0], (C[3] if len(C) > 3 else C[-1])
            for v in vals:
                bot.append(min(running, running + v))
                hgt.append(abs(v))
                bcolors.append(pos_c if v >= 0 else neg_c)
                running += v
            xlabels = [str(i) for i in range(len(vals))]
            ax.bar(xlabels, hgt, bottom=bot, color=bcolors,
                   edgecolor=t['fig_bg'], linewidth=0.5)
            ax.axhline(0, color=t['muted'], linewidth=0.8, alpha=0.5)
            dtitle = f'Waterfall — {cfg["col"]}'; dxlabel = 'Step'; dylabel = cfg['col']
            rotate_x = True

        # ── PIE ─────────────────────────────────────────────────────────────────
        elif gtype == 'pie':
            g = df.groupby(cfg['labels'])[cfg['values']].sum()
            pc = [C[i % len(C)] for i in range(len(g))]
            _, _, autotexts = ax.pie(
                g.values, labels=g.index.astype(str), autopct='%1.1f%%',
                colors=pc, startangle=90, pctdistance=0.82,
                wedgeprops=dict(edgecolor=t['fig_bg'], linewidth=1.5),
                textprops=dict(color=t['fg'], fontsize=fs - 1))
            for at in autotexts:
                at.set_color(t['fig_bg']); at.set_fontweight('bold')
            dtitle = f'{cfg["values"]} Breakdown'

        # ── DONUT ───────────────────────────────────────────────────────────────
        elif gtype == 'donut':
            g  = df.groupby(cfg['labels'])[cfg['values']].sum()
            pc = [C[i % len(C)] for i in range(len(g))]
            ax.pie(g.values, labels=g.index.astype(str), autopct='%1.1f%%',
                   colors=pc, startangle=90, pctdistance=0.75,
                   wedgeprops=dict(edgecolor=t['fig_bg'], linewidth=1.5, width=0.5),
                   textprops=dict(color=t['fg'], fontsize=fs - 1))
            ax.add_patch(plt.Circle((0, 0), 0.5, color=t['fig_bg']))
            total = g.sum()
            ax.text(0, 0, f'{total:,.0f}', ha='center', va='center',
                    color=t['fg'], fontsize=fs + 2, fontweight='bold')
            dtitle = f'{cfg["values"]} Donut'

        # ── SCATTER ─────────────────────────────────────────────────────────────
        elif gtype == 'scatter':
            mask = df[cfg['x']].notna() & df[cfg['y']].notna()
            ax.scatter(df.loc[mask, cfg['x']], df.loc[mask, cfg['y']],
                       color=C[0], alpha=0.72, s=55,
                       edgecolors=t['fig_bg'], linewidths=0.4)
            dtitle = f'{cfg["y"]} vs {cfg["x"]}'; dxlabel = cfg['x']; dylabel = cfg['y']

        # ── REGRESSION ──────────────────────────────────────────────────────────
        elif gtype == 'regression':
            mask   = df[cfg['x']].notna() & df[cfg['y']].notna()
            xd, yd = df.loc[mask, cfg['x']].values, df.loc[mask, cfg['y']].values
            ax.scatter(xd, yd, color=C[0], alpha=0.6, s=50,
                       edgecolors=t['fig_bg'], linewidths=0.4, label='Data')
            if len(xd) >= 2:
                coeffs  = np.polyfit(xd, yd, 1)
                xl      = np.linspace(xd.min(), xd.max(), 200)
                yl      = np.polyval(coeffs, xl)
                ax.plot(xl, yl, color=C[3 % len(C)], linewidth=2.5,
                        label=f'y = {coeffs[0]:.3f}x + {coeffs[1]:.3f}')
                y_pred  = np.polyval(coeffs, xd)
                ss_res  = np.sum((yd - y_pred) ** 2)
                ss_tot  = np.sum((yd - yd.mean()) ** 2)
                r2      = 1 - ss_res / max(ss_tot, 1e-10)
                ax.text(0.05, 0.95, f'R² = {r2:.3f}', transform=ax.transAxes,
                        color=t['fg'], fontsize=fs, va='top',
                        bbox=dict(boxstyle='round,pad=0.3', facecolor=t['ax_bg'],
                                  edgecolor=t['spine_c'], alpha=0.85))
                ax.legend(fontsize=fs - 1); has_legend_data = True
            dtitle = f'{cfg["y"]} vs {cfg["x"]} (Regression)'
            dxlabel = cfg['x']; dylabel = cfg['y']

        # ── BUBBLE ──────────────────────────────────────────────────────────────
        elif gtype == 'bubble':
            mask = df[cfg['x']].notna() & df[cfg['y']].notna() & df[cfg['size']].notna()
            xd, yd, sd = (df.loc[mask, cfg['x']].values,
                          df.loc[mask, cfg['y']].values,
                          df.loc[mask, cfg['size']].values)
            smin, smax = sd.min(), sd.max()
            sizes = 30 + (sd - smin) / max(smax - smin, 1) * 500
            bcolors = [C[i % len(C)] for i in range(len(xd))]
            ax.scatter(xd, yd, s=sizes, alpha=0.65,
                       c=bcolors, edgecolors=t['fig_bg'], linewidths=0.5)
            dtitle = f'{cfg["y"]} vs {cfg["x"]} · size={cfg["size"]}'
            dxlabel = cfg['x']; dylabel = cfg['y']

        # ── HEXBIN ──────────────────────────────────────────────────────────────
        elif gtype == 'hexbin':
            mask = df[cfg['x']].notna() & df[cfg['y']].notna()
            xd, yd = df.loc[mask, cfg['x']].values, df.loc[mask, cfg['y']].values
            cmap = 'YlOrRd' if not t['dark'] else 'plasma'
            hb   = ax.hexbin(xd, yd, gridsize=20, cmap=cmap, linewidths=0.2)
            cb   = fig.colorbar(hb, ax=ax, shrink=0.8)
            cb.ax.tick_params(colors=t['muted'], labelsize=fs - 2)
            cb.set_label('Count', color=t['muted'], fontsize=fs - 1)
            dtitle = f'{cfg["y"]} vs {cfg["x"]} (Density)'; dxlabel = cfg['x']; dylabel = cfg['y']

        # ── FILLED AREA ─────────────────────────────────────────────────────────
        elif gtype == 'filled_area':
            if 'x' in cfg:
                sdf   = df.sort_values(cfg['x'])
                xstr  = sdf[cfg['x']].astype(str).values
                xpos  = list(range(len(xstr)))
                y1, y2 = sdf[cfg['y1']].values, sdf[cfg['y2']].values
                ax.fill_between(xpos, y1, y2, alpha=0.25, color=C[0])
                ax.plot(xpos, y1, color=C[0], linewidth=2.5, label=cfg['y1'])
                ax.plot(xpos, y2, color=C[1 % len(C)], linewidth=2.5, label=cfg['y2'])
                ax.set_xticks(xpos); ax.set_xticklabels(xstr)
                dtitle = f'{cfg["y1"]} vs {cfg["y2"]}'; dxlabel = cfg['x']
                has_legend_data = True; ax.legend(fontsize=fs - 1); rotate_x = True
            else:
                y1d = df[cfg['y1']].dropna().values
                y2d = df[cfg['y2']].dropna().values
                n   = min(len(y1d), len(y2d))
                xp  = list(range(n))
                ax.fill_between(xp, y1d[:n], y2d[:n], alpha=0.25, color=C[0])
                ax.plot(xp, y1d[:n], color=C[0], linewidth=2.5, label=cfg['y1'])
                ax.plot(xp, y2d[:n], color=C[1 % len(C)], linewidth=2.5, label=cfg['y2'])
                has_legend_data = True; ax.legend(fontsize=fs - 1)
                dtitle = 'Filled Area Chart'

        # ── LINE ────────────────────────────────────────────────────────────────
        elif gtype == 'line':
            sdf  = df.sort_values(cfg['x'])
            xstr = sdf[cfg['x']].astype(str).values
            c    = C[0]
            ax.plot(xstr, sdf[cfg['y']].values, color=c, linewidth=2.5, marker='o',
                    markersize=4, markerfacecolor=t['fig_bg'], markeredgecolor=c,
                    markeredgewidth=2)
            dtitle = f'{cfg["y"]} over {cfg["x"]}'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = True

        # ── MULTI-LINE ──────────────────────────────────────────────────────────
        elif gtype == 'multi_line':
            sdf  = df.sort_values(cfg['x'])
            xstr = sdf[cfg['x']].astype(str).values
            for i, y in enumerate(cfg['ys']):
                c = C[i % len(C)]
                ax.plot(xstr, sdf[y].values, color=c, linewidth=2, marker='o',
                        markersize=3.5, label=y, markerfacecolor=t['fig_bg'],
                        markeredgecolor=c, markeredgewidth=1.5)
            ax.legend(fontsize=fs - 1); has_legend_data = True
            dtitle = f'Trends over {cfg["x"]}'; dxlabel = cfg['x']
            rotate_x = True

        # ── AREA ────────────────────────────────────────────────────────────────
        elif gtype == 'area':
            sdf  = df.sort_values(cfg['x'])
            xstr = sdf[cfg['x']].astype(str).values
            yv   = sdf[cfg['y']].values
            c    = C[0]
            ax.fill_between(range(len(xstr)), yv, alpha=0.25, color=c)
            ax.plot(range(len(xstr)), yv, color=c, linewidth=2.5)
            ax.set_xticks(range(len(xstr))); ax.set_xticklabels(xstr)
            dtitle = f'{cfg["y"]} — Area'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = True

        # ── STEP ────────────────────────────────────────────────────────────────
        elif gtype == 'step':
            sdf  = df.sort_values(cfg['x'])
            xstr = sdf[cfg['x']].astype(str).values
            yv   = sdf[cfg['y']].values
            xpos = list(range(len(xstr)))
            c    = C[0]
            ax.step(xpos, yv, color=c, linewidth=2.5, where='mid')
            ax.fill_between(xpos, yv, step='mid', alpha=0.18, color=c)
            ax.set_xticks(xpos); ax.set_xticklabels(xstr)
            dtitle = f'{cfg["y"]} — Step Chart'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = True

        # ── DUAL AXIS ───────────────────────────────────────────────────────────
        elif gtype == 'dual_axis':
            sdf  = df.sort_values(cfg['x'])
            xstr = sdf[cfg['x']].astype(str).values
            xpos = list(range(len(xstr)))
            c1, c2 = C[0], C[1 % len(C)]
            ax.plot(xpos, sdf[cfg['y1']].values, color=c1, linewidth=2.5,
                    marker='o', markersize=4, label=cfg['y1'])
            ax.set_ylabel(cfg['y1'], color=c1, fontsize=fs)
            ax.tick_params(axis='y', colors=c1)
            ax.spines['left'].set_color(c1)
            ax2 = ax.twinx()
            ax2.plot(xpos, sdf[cfg['y2']].values, color=c2, linewidth=2.5,
                     marker='s', markersize=4, label=cfg['y2'])
            ax2.set_ylabel(cfg['y2'], color=c2, fontsize=fs)
            ax2.tick_params(axis='y', colors=c2)
            ax2.spines['right'].set_color(c2)
            ax2.spines[['top', 'left', 'bottom']].set_visible(False)
            ax.set_xticks(xpos); ax.set_xticklabels(xstr)
            if leg:
                lines1, lbl1 = ax.get_legend_handles_labels()
                lines2, lbl2 = ax2.get_legend_handles_labels()
                ax.legend(lines1 + lines2, lbl1 + lbl2, fontsize=fs - 1)
                has_legend_data = True
            dtitle = f'{cfg["y1"]} & {cfg["y2"]}'; dxlabel = cfg['x']
            rotate_x = True

        # ── MOVING AVERAGE ──────────────────────────────────────────────────────
        elif gtype == 'moving_avg':
            sdf  = df.sort_values(cfg['x'])
            yv   = sdf[cfg['y']].values
            w    = max(3, len(yv) // 5)
            xstr = sdf[cfg['x']].astype(str).values
            xpos = list(range(len(xstr)))
            ax.scatter(xpos, yv, color=C[0], alpha=0.35, s=25, edgecolors='none')
            ax.plot(xpos, yv, color=C[0], linewidth=1, alpha=0.35)
            if len(yv) >= w:
                ma = pd.Series(yv).rolling(window=w, center=True).mean().values
                ax.plot(xpos, ma, color=C[3 % len(C)], linewidth=2.5,
                        label=f'{w}-pt avg')
                ax.legend(fontsize=fs - 1); has_legend_data = True
            ax.set_xticks(xpos); ax.set_xticklabels(xstr)
            dtitle = f'{cfg["y"]} — Moving Avg'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = True

        # ── HISTOGRAM ───────────────────────────────────────────────────────────
        elif gtype == 'histogram':
            vals = df[cfg['col']].dropna()
            ax.hist(vals, bins='auto', color=C[0],
                    edgecolor=t['fig_bg'], linewidth=0.5, alpha=0.9)
            dtitle = f'Distribution — {cfg["col"]}'; dxlabel = cfg['col']; dylabel = 'Frequency'

        # ── KDE (manual Gaussian) ────────────────────────────────────────────────
        elif gtype == 'kde':
            vals = df[cfg['col']].dropna().values.astype(float)
            if len(vals) < 2:
                raise ValueError('Need ≥ 2 values for KDE')
            bw   = 1.06 * vals.std() * len(vals) ** (-0.2)
            bw   = max(bw, 1e-9)
            xrng = np.linspace(vals.min() - 3 * bw, vals.max() + 3 * bw, 300)
            diff = (xrng[:, None] - vals[None, :]) / bw
            ykde = np.exp(-0.5 * diff ** 2).sum(axis=1) / (len(vals) * bw * np.sqrt(2 * np.pi))
            ax.fill_between(xrng, ykde, alpha=0.25, color=C[0])
            ax.plot(xrng, ykde, color=C[0], linewidth=2.5)
            ax.axvline(vals.mean(),   color=C[1 % len(C)], linestyle='--', linewidth=1.8,
                       label=f'Mean {vals.mean():.2f}')
            ax.axvline(np.median(vals), color=C[2 % len(C)], linestyle=':', linewidth=1.8,
                       label=f'Median {np.median(vals):.2f}')
            ax.legend(fontsize=fs - 1); has_legend_data = True
            dtitle = f'Density — {cfg["col"]}'; dxlabel = cfg['col']; dylabel = 'Density'

        # ── CUMULATIVE CDF ───────────────────────────────────────────────────────
        elif gtype == 'cumulative':
            vals = np.sort(df[cfg['col']].dropna().values)
            yv   = np.arange(1, len(vals) + 1) / len(vals)
            ax.plot(vals, yv, color=C[0], linewidth=2.5, drawstyle='steps-post')
            ax.fill_between(vals, yv, alpha=0.15, color=C[0], step='post')
            ax.set_ylim(0, 1.05)
            ax.yaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, _: f'{x * 100:.0f}%'))
            dtitle = f'CDF — {cfg["col"]}'; dxlabel = cfg['col']; dylabel = 'Cumulative %'

        # ── BOX (multiple numeric columns) ──────────────────────────────────────
        elif gtype == 'box':
            data   = [df[c].dropna() for c in cfg['cols']]
            labels = cfg['cols']
            bp = ax.boxplot(data, patch_artist=True, labels=labels,
                            medianprops=dict(color=t['fig_bg'], linewidth=2.5),
                            whiskerprops=dict(color=t['muted'], linewidth=1.2),
                            capprops=dict(color=t['muted'], linewidth=1.2),
                            flierprops=dict(markerfacecolor=t['muted'], markersize=4,
                                            markeredgecolor='none'))
            for i, patch in enumerate(bp['boxes']):
                patch.set_facecolor(C[i % len(C)])
            rotate_x = len(cfg['cols']) > 4
            dtitle = 'Box Plot'

        # ── BOX BY CATEGORY ─────────────────────────────────────────────────────
        elif gtype == 'box_cat':
            cats = df[cfg['x']].unique()
            data = [df[df[cfg['x']] == c][cfg['y']].dropna() for c in cats]
            bp   = ax.boxplot(data, patch_artist=True,
                              labels=[str(c) for c in cats],
                              medianprops=dict(color=t['fig_bg'], linewidth=2.5),
                              whiskerprops=dict(color=t['muted'], linewidth=1.2),
                              capprops=dict(color=t['muted'], linewidth=1.2),
                              flierprops=dict(markerfacecolor=t['muted'], markersize=4,
                                              markeredgecolor='none'))
            for i, patch in enumerate(bp['boxes']):
                patch.set_facecolor(C[i % len(C)])
            dtitle = f'{cfg["y"]} Distribution by {cfg["x"]}'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = len(cats) > 4

        # ── VIOLIN (multiple numeric columns) ────────────────────────────────────
        elif gtype == 'violin':
            cols_ = [c for c in cfg['cols'] if df[c].dropna().shape[0] >= 2]
            data  = [df[c].dropna().values for c in cols_]
            if not data:
                raise ValueError('No data for violin')
            parts = ax.violinplot(data, showmedians=True, showextrema=True)
            for i, pc in enumerate(parts['bodies']):
                pc.set_facecolor(C[i % len(C)]); pc.set_alpha(0.75)
            parts['cmedians'].set_color(t['fig_bg']); parts['cmedians'].set_linewidth(2)
            parts['cbars'].set_color(t['muted']); parts['cmins'].set_color(t['muted'])
            parts['cmaxes'].set_color(t['muted'])
            ax.set_xticks(range(1, len(data) + 1))
            ax.set_xticklabels(cols_)
            rotate_x = len(cols_) > 4
            dtitle = 'Violin Plot'

        # ── VIOLIN BY CATEGORY ──────────────────────────────────────────────────
        elif gtype == 'violin_cat':
            cats = df[cfg['x']].unique()
            data = [df[df[cfg['x']] == c][cfg['y']].dropna().values for c in cats]
            data = [(d if len(d) >= 2 else np.array([d[0], d[0]])) for d in data]
            parts = ax.violinplot(data, positions=range(len(cats)),
                                  showmedians=True, showextrema=True)
            for i, pc in enumerate(parts['bodies']):
                pc.set_facecolor(C[i % len(C)]); pc.set_alpha(0.75)
            parts['cmedians'].set_color(t['fig_bg']); parts['cmedians'].set_linewidth(2)
            parts['cbars'].set_color(t['muted']); parts['cmins'].set_color(t['muted'])
            parts['cmaxes'].set_color(t['muted'])
            ax.set_xticks(range(len(cats)))
            ax.set_xticklabels([str(c) for c in cats])
            dtitle = f'{cfg["y"]} Distribution by {cfg["x"]}'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = len(cats) > 4

        # ── STRIP / JITTER ───────────────────────────────────────────────────────
        elif gtype == 'strip':
            cats = df[cfg['x']].unique()
            rng  = np.random.default_rng(42)
            for i, cat in enumerate(cats):
                yd = df[df[cfg['x']] == cat][cfg['y']].dropna().values
                xj = rng.normal(i, 0.1, size=len(yd))
                ax.scatter(xj, yd, alpha=0.65, s=30, color=C[i % len(C)],
                           edgecolors=t['fig_bg'], linewidths=0.3)
            ax.set_xticks(range(len(cats)))
            ax.set_xticklabels([str(c) for c in cats])
            dtitle = f'{cfg["y"]} by {cfg["x"]} (Strip)'; dxlabel = cfg['x']; dylabel = cfg['y']
            rotate_x = len(cats) > 4

        # ── STEM ────────────────────────────────────────────────────────────────
        elif gtype == 'stem':
            vals = df[cfg['col']].dropna().values[:50]
            ml, sl, bl = ax.stem(range(len(vals)), vals)
            plt.setp(ml, color=C[0], markersize=5, markerfacecolor=C[0])
            plt.setp(sl, color=C[0], linewidth=1.5, alpha=0.7)
            plt.setp(bl, color=t['muted'], linewidth=0.5)
            dtitle = f'Stem — {cfg["col"]}'; dylabel = cfg['col']

        # ── CORRELATION HEATMAP ──────────────────────────────────────────────────
        elif gtype == 'heatmap':
            cols_ = cfg['cols']
            corr  = df[cols_].corr()
            cmap  = 'RdBu_r'
            im    = ax.imshow(corr.values, cmap=cmap, vmin=-1, vmax=1, aspect='auto')
            cb    = fig.colorbar(im, ax=ax, shrink=0.8)
            cb.ax.tick_params(colors=t['muted'], labelsize=fs - 2)
            n_ = len(cols_)
            ax.set_xticks(range(n_)); ax.set_yticks(range(n_))
            ax.set_xticklabels(cols_, fontsize=fs - 1)
            ax.set_yticklabels(cols_, fontsize=fs - 1)
            for i in range(n_):
                for j in range(n_):
                    v = corr.iloc[i, j]
                    tc = t['fig_bg'] if abs(v) > 0.6 else t['fg']
                    ax.text(j, i, f'{v:.2f}', ha='center', va='center',
                            fontsize=max(6, fs - 2), color=tc, fontweight='bold')
            dtitle = 'Correlation Heatmap'
            rotate_x = True

        # ── PIVOT / CATEGORY HEATMAP ─────────────────────────────────────────────
        elif gtype == 'heatmap_cat':
            ys_   = cfg['ys'][:8]
            pivot = df.groupby(cfg['x'])[ys_].mean()
            norm  = (pivot - pivot.min()) / (pivot.max() - pivot.min()).replace(0, 1)
            cmap  = 'YlOrRd' if not t['dark'] else 'magma'
            im    = ax.imshow(norm.values.T, cmap=cmap, aspect='auto', vmin=0, vmax=1)
            cb    = fig.colorbar(im, ax=ax, shrink=0.8)
            cb.ax.tick_params(colors=t['muted'], labelsize=fs - 2)
            ax.set_xticks(range(len(pivot.index)))
            ax.set_yticks(range(len(ys_)))
            ax.set_xticklabels(pivot.index.astype(str), fontsize=fs - 1)
            ax.set_yticklabels(ys_, fontsize=fs - 1)
            for i, yc in enumerate(ys_):
                for j, xc in enumerate(pivot.index):
                    v  = pivot.loc[xc, yc]
                    nv = norm.loc[xc, yc]
                    tc = t['fig_bg'] if nv > 0.6 else t['fg']
                    ax.text(j, i, f'{v:.1f}', ha='center', va='center',
                            fontsize=max(6, fs - 2), color=tc, fontweight='bold')
            dtitle = f'Heatmap by {cfg["x"]}'; dxlabel = cfg['x']
            rotate_x = True

        # ── GROUPED BAR ─────────────────────────────────────────────────────────
        elif gtype == 'grouped_bar':
            grouped = df.groupby(cfg['x'])[cfg['ys']].mean()
            x  = np.arange(len(grouped))
            w  = 0.8 / len(cfg['ys'])
            for i, col in enumerate(cfg['ys']):
                ax.bar(x + i * w, grouped[col], w, label=col,
                       color=C[i % len(C)], edgecolor=t['fig_bg'])
            mid = w * (len(cfg['ys']) - 1) / 2
            ax.set_xticks(x + mid)
            ax.set_xticklabels(grouped.index.astype(str))
            ax.legend(fontsize=fs - 1); has_legend_data = True
            dtitle = 'Grouped Bar Chart'
            rotate_x = True

        # ── STACKED BAR ─────────────────────────────────────────────────────────
        elif gtype == 'stacked_bar':
            grouped = df.groupby(cfg['x'])[cfg['ys']].sum()
            bottom  = np.zeros(len(grouped))
            for i, col in enumerate(cfg['ys']):
                ax.bar(grouped.index.astype(str), grouped[col], bottom=bottom,
                       label=col, color=C[i % len(C)], edgecolor=t['fig_bg'])
                bottom += grouped[col].values
            ax.legend(fontsize=fs - 1); has_legend_data = True
            dtitle = 'Stacked Bar Chart'
            rotate_x = True

        else:
            raise ValueError(f'Unknown graph type: {gtype}')

        # ── Rotate x labels ──────────────────────────────────────────────────────
        if rotate_x and gtype not in ('pie', 'donut', 'dot_plot', 'horizontal_bar'):
            plt.setp(ax.get_xticklabels(), rotation=40, ha='right',
                     rotation_mode='anchor', fontsize=fs - 1)

        # ── Apply opts overrides ─────────────────────────────────────────────────
        _apply_opts(ax, opts, t,
                    default_title=dtitle, default_xlabel=dxlabel, default_ylabel=dylabel,
                    skip_labels=(gtype in ('pie', 'donut')),
                    font_size=fs, show_grid=grid, show_legend=leg,
                    has_legend=has_legend_data)

        plt.tight_layout(pad=1.5)
        return _save(fig, fmt, t['fig_bg'])

    except Exception as exc:
        plt.close(fig)
        raise exc


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _smart_parse_text(content):
    for sep in ['\t', ',', ';', '|']:
        try:
            df = pd.read_csv(io.StringIO(content), sep=sep)
            if len(df.columns) > 1:
                return df, 'tabular'
        except Exception:
            pass
    try:
        df = pd.read_csv(io.StringIO(content))
        if len(df.columns) == 1:
            exdf, mode = _extract_numbers_from_text(content)
            if exdf is not None:
                return exdf, mode
        return df, 'tabular'
    except Exception:
        pass
    return _extract_numbers_from_text(content)


def _coerce_types(df):
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.columns:
        try:
            df[col] = pd.to_numeric(df[col])
        except Exception:
            pass
    return df.dropna(how='all')


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/parse', methods=['POST'])
def parse_data():
    try:
        df = None
        extracted = False

        if 'file' in request.files:
            f    = request.files['file']
            name = f.filename.lower()
            if name.endswith('.csv'):
                df = pd.read_csv(f)
            elif name.endswith(('.txt', '.tsv', '.log')):
                content = f.read().decode('utf-8-sig')
                df, mode = _smart_parse_text(content)
                extracted = (mode == 'extracted')
            elif name.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(f)
            else:
                return jsonify({'error': 'Unsupported file type.'}), 400

        elif request.form.get('sheets_url'):
            url = request.form['sheets_url'].strip()
            m   = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
            if not m:
                return jsonify({'error': 'Invalid Google Sheets URL.'}), 400
            sheet_id = m.group(1)
            gid_m    = re.search(r'gid=(\d+)', url)
            gid      = f'&gid={gid_m.group(1)}' if gid_m else ''
            csv_url  = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{gid}'
            resp     = requests.get(csv_url, timeout=15)
            if resp.status_code != 200:
                return jsonify({'error': 'Could not fetch sheet.'}), 400
            df = pd.read_csv(io.StringIO(resp.text))

        elif request.form.get('table_data'):
            payload = json.loads(request.form['table_data'])
            df = pd.DataFrame(payload['rows'], columns=payload['headers'])

        elif request.form.get('raw_text'):
            df, mode = _extract_numbers_from_text(request.form['raw_text'])
            extracted = True
            if df is None:
                return jsonify({'error': 'Could not extract numeric data. Use "Key: value" format.'}), 400

        else:
            return jsonify({'error': 'No data provided.'}), 400

        if df is None:
            return jsonify({'error': 'Could not parse the data.'}), 400

        df = _coerce_types(df)
        if df.empty:
            return jsonify({'error': 'Data is empty after parsing.'}), 400

        return jsonify({
            'headers':   df.columns.tolist(),
            'rows':      df.where(pd.notnull(df), None).values.tolist(),
            'shape':     list(df.shape),
            'extracted': extracted,
        })

    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/generate', methods=['POST'])
def generate():
    try:
        payload = request.json
        df = pd.DataFrame(payload['rows'], columns=payload['headers'])
        df = _coerce_types(df)
        if df.empty:
            return jsonify({'error': 'No data to visualize.'}), 400

        suggestions = suggest_graphs(df)
        if not suggestions:
            return jsonify({'error': 'No suitable chart types found.'}), 400

        graphs = []
        for cfg in suggestions:
            try:
                img_bytes = render_graph(df, cfg)
                graphs.append({
                    'name':   cfg['name'],
                    'type':   cfg['type'],
                    'config': cfg,
                    'image':  base64.b64encode(img_bytes).decode(),
                })
            except Exception as exc:
                print(f'[warn] skipped {cfg["type"]}: {exc}')

        if not graphs:
            return jsonify({'error': 'All chart types failed to render.'}), 500

        return jsonify({'graphs': graphs, 'schemes': SCHEME_PREVIEWS})

    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/customize', methods=['POST'])
def customize():
    try:
        payload = request.json
        df = pd.DataFrame(payload['rows'], columns=payload['headers'])
        df = _coerce_types(df)
        img_bytes = render_graph(df, payload['config'], opts=payload.get('options', {}), fmt='png')
        return jsonify({'image': base64.b64encode(img_bytes).decode()})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@app.route('/api/download', methods=['POST'])
def download():
    try:
        payload = request.json
        fmt     = payload.get('format', 'png').lower()
        if fmt not in ('png', 'svg', 'pdf', 'jpeg'):
            return jsonify({'error': 'Unsupported format.'}), 400
        df = pd.DataFrame(payload['rows'], columns=payload['headers'])
        df = _coerce_types(df)
        img_bytes = render_graph(df, payload['config'],
                                 opts=payload.get('options', {}), fmt=fmt)
        mime = {'png': 'image/png', 'svg': 'image/svg+xml',
                'pdf': 'application/pdf', 'jpeg': 'image/jpeg'}[fmt]
        name = payload.get('name', 'chart').replace(' ', '_')
        return send_file(io.BytesIO(img_bytes), mimetype=mime,
                         as_attachment=True, download_name=f'{name}.{fmt}')
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
