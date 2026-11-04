import React, { useState, useRef } from "react";
import { fmt } from "./ui.jsx";

const W = 640;

function niceMax(v) {
  if (!v || v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

function Tip({ tip }) {
  if (!tip) return null;
  return (
    <div style={{ position: "absolute", left: `${tip.x}%`, top: tip.y, transform: "translate(-50%, -110%)", background: "var(--surface)", border: "1px solid var(--line)", boxShadow: "var(--shadow)", borderRadius: 6, padding: "6px 9px", fontSize: ".78rem", pointerEvents: "none", whiteSpace: "nowrap", zIndex: 2 }}>
      <div className="faint">{tip.title}</div>
      {tip.rows.map((r) => <div key={r.label} className="row" style={{ gap: 6 }}><i style={{ width: 8, height: 8, borderRadius: 2, background: r.color, display: "inline-block" }} />{r.label}<b className="num" style={{ marginLeft: "auto" }}>{fmt(r.value)}</b></div>)}
    </div>
  );
}

/** Horizontal bars: magnitude by category. items: [{label, value, color?}] */
export function HBars({ items, height = 22, format = (v) => fmt(v), color = "var(--chart-1)" }) {
  const max = niceMax(Math.max(...items.map((i) => i.value), 0));
  const labelW = 190;
  const H = items.length * (height + 8) + 4;
  const [hov, setHov] = useState(null);
  return (
    <div style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" style={{ minWidth: 380 }}>
        {items.map((it, i) => {
          const y = i * (height + 8) + 2;
          const w = Math.max(2, ((W - labelW - 60) * it.value) / max);
          return (
            <g key={it.label} onMouseEnter={() => setHov(i)} onMouseLeave={() => setHov(null)}>
              <rect x={0} y={y - 3} width={W} height={height + 6} fill="transparent" />
              <text x={labelW - 8} y={y + height / 2 + 4} textAnchor="end" className="lbl">{it.label.length > 30 ? it.label.slice(0, 29) + "…" : it.label}</text>
              <rect x={labelW} y={y} width={w} height={height} rx={4} fill={it.color || color} opacity={hov === null || hov === i ? 1 : 0.55} />
              <text x={labelW + w + 6} y={y + height / 2 + 4} className="lbl num">{format(it.value)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/** Line/area over time with crosshair tooltip. series: [{name, color, values:[n]}], x: [labels] */
export function Lines({ x, series, height = 200, area = true }) {
  const ref = useRef(null);
  const [hi, setHi] = useState(null);
  const L = 44, R = 12, T = 12, B = 26, H = height;
  const max = niceMax(Math.max(1, ...series.flatMap((s) => s.values)));
  const n = Math.max(x.length, 1);
  const px = (i) => L + (n === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (n - 1));
  const py = (v) => T + (H - T - B) * (1 - v / max);
  const ticks = [0, max / 2, max];
  const step = Math.ceil(n / 7);
  const onMove = (e) => {
    const r = ref.current.getBoundingClientRect();
    const rel = ((e.clientX - r.left) / r.width) * W;
    const i = Math.round(((rel - L) / (W - L - R)) * (n - 1));
    setHi(Math.max(0, Math.min(n - 1, i)));
  };
  return (
    <div style={{ position: "relative" }}>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} width="100%" role="img" onMouseMove={onMove} onMouseLeave={() => setHi(null)}>
        {ticks.map((t) => (
          <g key={t}><line x1={L} x2={W - R} y1={py(t)} y2={py(t)} stroke="var(--chart-grid)" /><text x={L - 6} y={py(t) + 4} textAnchor="end" className="num">{fmt(t)}</text></g>
        ))}
        {x.map((lbl, i) => (i % step === 0 || i === n - 1) && <text key={i} x={px(i)} y={H - 8} textAnchor="middle">{String(lbl).slice(5)}</text>)}
        {series.map((s) => {
          const d = s.values.map((v, i) => `${i ? "L" : "M"}${px(i)},${py(v)}`).join(" ");
          return (
            <g key={s.name}>
              {area && <path d={`${d} L${px(s.values.length - 1)},${py(0)} L${px(0)},${py(0)} Z`} fill={s.color} opacity={0.1} />}
              <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" />
              {s.values.length > 0 && <circle cx={px(s.values.length - 1)} cy={py(s.values[s.values.length - 1])} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />}
            </g>
          );
        })}
        {hi !== null && <line x1={px(hi)} x2={px(hi)} y1={T} y2={H - B} stroke="var(--ink-3)" strokeDasharray="3 3" />}
        {hi !== null && series.map((s) => <circle key={s.name} cx={px(hi)} cy={py(s.values[hi] || 0)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} />)}
      </svg>
      {hi !== null && <Tip tip={{ x: (px(hi) / W) * 100, y: 10, title: x[hi], rows: series.map((s) => ({ label: s.name, value: s.values[hi], color: s.color })) }} />}
      {series.length > 1 && <div className="legend">{series.map((s) => <span key={s.name}><i style={{ background: s.color }} />{s.name}</span>)}</div>}
    </div>
  );
}

/** Vertical bars by category with per-bar tooltip. */
export function VBars({ items, height = 170, color = "var(--chart-1)" }) {
  const L = 40, B = 24, T = 10, H = height;
  const max = niceMax(Math.max(1, ...items.map((i) => i.value)));
  const bw = (W - L) / Math.max(items.length, 1);
  const [hi, setHi] = useState(null);
  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img">
        {[0, max / 2, max].map((t) => <g key={t}><line x1={L} x2={W} y1={T + (H - T - B) * (1 - t / max)} y2={T + (H - T - B) * (1 - t / max)} stroke="var(--chart-grid)" /><text x={L - 6} y={T + (H - T - B) * (1 - t / max) + 4} textAnchor="end">{fmt(t)}</text></g>)}
        {items.map((it, i) => {
          const h = ((H - T - B) * it.value) / max;
          const x = L + i * bw + 2;
          return (
            <g key={it.label} onMouseEnter={() => setHi(i)} onMouseLeave={() => setHi(null)}>
              <rect x={x} y={T} width={bw - 4} height={H - T - B} fill="transparent" />
              <path d={`M${x},${H - B} V${H - B - h + 4} q0,-4 4,-4 h${Math.max(bw - 12, 2)} q4,0 4,4 V${H - B} Z`} fill={it.color || color} opacity={hi === null || hi === i ? 1 : 0.55} />
              <text x={x + (bw - 4) / 2} y={H - 8} textAnchor="middle">{it.label}</text>
            </g>
          );
        })}
      </svg>
      {hi !== null && <Tip tip={{ x: ((L + hi * bw + bw / 2) / W) * 100, y: 8, title: items[hi].title || items[hi].label, rows: [{ label: items[hi].seriesName || "Count", value: items[hi].value, color: items[hi].color || color }] }} />}
    </div>
  );
}

/** Segmented progress: [{value, color, label}] */
export function Segments({ parts, total }) {
  const t = total || parts.reduce((a, p) => a + p.value, 0) || 1;
  return (
    <div className="progress" role="img" aria-label={parts.map((p) => `${p.label} ${p.value}`).join(", ")}>
      {parts.map((p) => p.value > 0 && <i key={p.label} title={`${p.label}: ${fmt(p.value)}`} style={{ width: `${(p.value / t) * 100}%`, background: p.color, borderRight: "2px solid var(--surface)" }} />)}
    </div>
  );
}

export function Sparkline({ values, color = "var(--chart-1)", width = 120, height = 28 }) {
  if (!values || values.length < 2) return <span className="faint">—</span>;
  const max = Math.max(...values, 1), min = Math.min(...values, 0);
  const px = (i) => (i * (width - 6)) / (values.length - 1) + 3;
  const py = (v) => height - 3 - ((height - 6) * (v - min)) / (max - min || 1);
  const d = values.map((v, i) => `${i ? "L" : "M"}${px(i)},${py(v)}`).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <path d={`${d} L${px(values.length - 1)},${height - 2} L${px(0)},${height - 2} Z`} fill={color} opacity={0.12} />
      <path d={d} fill="none" stroke={color} strokeWidth={1.6} />
      <circle cx={px(values.length - 1)} cy={py(values[values.length - 1])} r={2.6} fill={color} />
    </svg>
  );
}

/** Sequential single-hue cell color for 0..100 scores. */
export const heatColor = (v) => `color-mix(in srgb, var(--chart-1) ${Math.max(8, Math.min(90, Math.round(10 + (v - 80) * 4)))}%, var(--surface))`;
