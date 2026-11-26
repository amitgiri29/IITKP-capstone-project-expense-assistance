"""SPARKS AI Lab design system for the Streamlit UI (light enterprise theme from the approved mock-ups,
specified in DESIGN.md). Colour roles follow the dataviz method:

- Text uses text tokens only; badge text uses darker steps of the spec hues so every badge clears 4.5:1
  (#047857 on #ECFDF5 5.21, #B45309 on #FFFBEB 4.84, #BE123C on #FFE4E6 5.24).
- Primary buttons use #E11D48 -> #BE123C so white text clears 4.5:1 (the spec's #F43F5E gives 3.67).
- Eligible / over cap / excluded use #1baf7a, #eb6834, #2a78d6: all-pairs PASS on #FFFFFF (CVD dE 9.2,
  normal dE 24.0); aqua is 2.82:1 against white, so the bar always carries labels, a legend and a ledger.
- Status always pairs colour with an icon or dot and a text label.
Every dynamic string placed in HTML is escaped.
"""
from html import escape

import streamlit as st

PARTS = {'eligible': ('#1baf7a', 'Eligible'), 'over_cap': ('#eb6834', 'Over cap'), 'excluded': ('#2a78d6', 'Excluded')}
TONES = {  # dot, text, background, border
    'ok': ('#059669', '#047857', '#ECFDF5', 'rgba(5,150,105,.22)'),
    'warn': ('#D97706', '#B45309', '#FFFBEB', 'rgba(217,119,6,.25)'),
    'bad': ('#E11D48', '#BE123C', '#FFE4E6', 'rgba(225,29,72,.22)'),
    'neutral': ('#94A3B8', '#475569', '#F1F5F9', '#E2E8F0'),
    'ai': ('#6366F1', '#4F46E5', '#EEF2FF', 'rgba(99,102,241,.25)'),
}
ICON = {'ok': '✓', 'warn': '!', 'bad': '✕', 'neutral': '•', 'ai': '✦'}
READINESS = {'READY_FOR_REVIEW': ('ok', 'Ready for review'), 'HUMAN_REVIEW': ('warn', 'Requires human review'),
             'NEEDS_EVIDENCE': ('warn', 'Needs evidence'), 'NEEDS_CLARIFICATION': ('warn', 'Needs clarification'),
             'INPUT_ERROR': ('bad', 'Input error')}
COMPLIANCE = {'WITHIN_POLICY': ('ok', 'Within policy'), 'EXCEEDS_POLICY': ('warn', 'Exceeds policy'),
              'HAS_EXCLUSIONS': ('bad', 'Has exclusions'), 'MIXED': ('bad', 'Over cap and exclusions'),
              'UNKNOWN': ('neutral', 'Compliance unknown')}
BUDGET = {'WITHIN_BUDGET': ('ok', 'Within budget'), 'OVER_BUDGET': ('bad', 'Over budget'),
          'UNKNOWN': ('neutral', 'Budget not compared')}

# Heroicons (MIT) outline paths, as used in the mock-ups.
SVG = {
    'chat': 'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
    'clipboard': 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01',
    'globe': 'M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
    'shield': 'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
    'check': 'M5 13l4 4L19 7',
    'alert': 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z',
    'x': 'M6 18L18 6M6 6l12 12',
    'info': 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
}
SPARK = 'M12 2L14.39 9.61L22 12L14.39 14.39L12 22L9.61 14.39L2 12L9.61 9.61L12 2Z'
FONT_URL = '/app/static/fonts/'

CSS = """
<style>
@font-face { font-family:'Inter'; font-weight:400; font-display:swap; src:url('FONTinter-latin-400-normal.woff2') format('woff2'); }
@font-face { font-family:'Inter'; font-weight:500; font-display:swap; src:url('FONTinter-latin-500-normal.woff2') format('woff2'); }
@font-face { font-family:'Inter'; font-weight:600; font-display:swap; src:url('FONTinter-latin-600-normal.woff2') format('woff2'); }
@font-face { font-family:'Inter'; font-weight:700; font-display:swap; src:url('FONTinter-latin-700-normal.woff2') format('woff2'); }
@font-face { font-family:'Inter'; font-weight:800; font-display:swap; src:url('FONTinter-latin-800-normal.woff2') format('woff2'); }
@font-face { font-family:'JetBrains Mono'; font-weight:400; font-display:swap; src:url('FONTjetbrains-mono-latin-400-normal.woff2') format('woff2'); }
@font-face { font-family:'JetBrains Mono'; font-weight:500; font-display:swap; src:url('FONTjetbrains-mono-latin-500-normal.woff2') format('woff2'); }
@font-face { font-family:'JetBrains Mono'; font-weight:600; font-display:swap; src:url('FONTjetbrains-mono-latin-600-normal.woff2') format('woff2'); }
:root {
  --bg:#F8FAFC; --card:#FFFFFF; --layer:#F1F5F9; --line:#E2E8F0; --line-2:#CBD5E1;
  --text:#0F172A; --text-2:#334155; --muted:#64748B;
  --rose:#E11D48; --rose-2:#BE123C; --rose-50:#FFF1F2; --rose-200:#FECDD3; --violet:#6366F1; --indigo:#4F46E5;
  --sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
  --sh1: 0 1px 3px 0 rgba(15,23,42,.04), 0 1px 2px -1px rgba(15,23,42,.02);
  --sh2: 0 4px 6px -1px rgba(15,23,42,.06), 0 2px 4px -2px rgba(15,23,42,.04);
}
html, body, .stApp, [class*="css"], button, input, textarea, select, p, li, label { font-family: var(--sans) !important; }
.stApp { background: var(--bg); color: var(--text); }
header[data-testid="stHeader"] { background: rgba(255,255,255,.9); backdrop-filter: blur(12px); border-bottom:1px solid var(--line); }
.block-container { padding-top: 3.6rem; max-width: 1280px; }
h1, h2, h3, h4, h5 { color: var(--text) !important; letter-spacing: -.02em; }
p, li { color: var(--text-2); }
input::placeholder, textarea::placeholder { color: #64748B !important; opacity: 1; }
.mono { font-family: var(--mono) !important; font-variant-numeric: tabular-nums slashed-zero; }

/* sidebar */
section[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid var(--line); }
section[data-testid="stSidebar"] .block-container, section[data-testid="stSidebarUserContent"] { padding-top: .5rem; }
.sp-persona { background: #F8FAFC; border:1px solid var(--line); border-radius: 12px; padding: 12px; }
.sp-persona .k { display:flex; justify-content:space-between; align-items:center; font-size:10px; font-weight:700;
  letter-spacing:.08em; text-transform:uppercase; color: var(--muted); }
.sp-persona .n { font-size:14px; font-weight:600; color:var(--text); margin-top:6px; }
.sp-persona .r { font-size:11.5px; color:var(--muted); }
.sp-persona .f { display:flex; justify-content:space-between; margin-top:10px; padding-top:8px; border-top:1px solid var(--line);
  font-size:11.5px; color:var(--muted); }
.sp-persona .f b { font-family: var(--mono); font-weight:600; color: #047857; }
.sp-status { background:#FFFFFF; border:1px solid var(--line); border-radius:12px; padding:12px; box-shadow: var(--sh1);
  font-size:12px; margin-top: 14px; }
.sp-status .h { display:flex; align-items:center; gap:8px; font-weight:600; color: var(--text); }
.sp-status .d { width:8px; height:8px; border-radius:50%; display:inline-block; }
.sp-status p { font-size: 11.5px; color: var(--muted); margin: 6px 0 0; line-height: 1.45; }
.sp-navlabel { font-size:10.5px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted);
  margin: 18px 0 14px 4px; }
[data-testid="stSidebar"] [data-testid="stPageLink"] a { border-radius: 8px; padding: 6px 10px; border:1px solid transparent; }
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover { background: var(--layer); }
[data-testid="stSidebar"] [data-testid="stPageLink"] a p { font-size: 14px; font-weight: 500; color: #475569; }
[class*="st-key-nav-active"] [data-testid="stPageLink"] a { background: var(--rose-50); border-color: rgba(254,205,211,.9); box-shadow: var(--sh1); }
[class*="st-key-nav-active"] [data-testid="stPageLink"] a p, [class*="st-key-nav-active"] [data-testid="stPageLink"] a span { color: var(--rose-2) !important; font-weight: 600; }
[data-testid="stSidebar"] [data-testid="stHorizontalBlock"] { align-items: center; gap: .25rem; }
[data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] { gap: .45rem; }
[data-testid="stSidebar"] [class*="st-key-nav"] { margin: -2px 0; position: relative; }
[data-testid="stSidebar"] [class*="st-key-nav"] [data-testid="stVerticalBlock"] { gap: 0; }
/* the badge floats over the right end of its own link row, vertically centred, so it never drifts to the next row */
[data-testid="stSidebar"] [class*="st-key-nav"] [data-testid="stElementContainer"]:has(.sp-navbadge) {
  position: absolute; right: 8px; top: -4px; height: 42px; width: 0 !important; pointer-events: none; z-index: 2; }
/* centred on the link box itself (Streamlit's markdown wrappers report ~5px height, so centre the badge, not them) */
[data-testid="stSidebar"] [class*="st-key-nav"] .sp-navbadge { position: absolute; right: 0; top: 50%; transform: translateY(-50%); }
.sp-navbadge { display:flex; justify-content:flex-end; }
.sp-navbadge p { margin: 0; }
.sp-avatar { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
  font-size: 14px; font-weight: 700; color: #FFFFFF; letter-spacing: .02em; }
.sp-persona .who { display:flex; gap: 10px; align-items: center; margin-top: 8px; }
.sp-persona .who .sp-avatar { width: 34px; height: 34px; font-size: 12.5px; }
.sp-persona .who .n { margin-top: 0; }

/* sign-in screen */
.sp-signin-brand { padding: 30px 6px 0 2px; }
.sp-signin-brand h1 { font-size: 40px; line-height: 1.1; font-weight: 800; letter-spacing: -.03em; margin: 18px 0 12px; }
.sp-signin-brand > p { font-size: 16px; line-height: 1.6; color: #475569; margin: 0 0 22px; max-width: 520px; }
.sp-points { display: grid; gap: 12px; margin: 0; padding: 0; list-style: none; }
.sp-points li { display: flex; gap: 10px; align-items: flex-start; font-size: 14px; color: var(--text-2); }
.sp-points li svg { width: 18px; height: 18px; flex-shrink: 0; margin-top: 2px; }
.sp-signin-head .sp-title { font-size: 20px; }
.sp-signin-head p { font-size: 13.5px; color: var(--muted); margin: 4px 0 6px; }
.sp-account { display: flex; gap: 12px; align-items: center; }
.sp-account .n { font-size: 15px; font-weight: 700; color: var(--text); }
.sp-account .t { font-size: 12.5px; color: var(--muted); margin-top: 1px; }
.sp-account .e { font-family: var(--mono) !important; font-size: 11px; color: #64748B; margin-top: 3px; }
[class*="st-key-acct-"] { background: #FFFFFF; border: 1px solid var(--line) !important; border-radius: 12px; padding: 14px 16px;
  box-shadow: var(--sh1); transition: all .15s ease; }
[class*="st-key-acct-"]:hover { border-color: var(--rose-200) !important; box-shadow: var(--sh2); }
[class*="st-key-acct-"] [data-testid="stHorizontalBlock"] { align-items: center; }
.sp-signin-note { font-size: 12px; color: var(--muted); line-height: 1.5; margin-top: 6px; }

/* top bar */
.sp-crumbs { display:flex; align-items:center; gap:10px; font-size:12.5px; color:var(--muted); flex-wrap: wrap; padding-top: 6px; }
.sp-crumbs b { color: var(--text); font-weight:600; }
[class*="st-key-topbar"] { border-bottom: 1px solid var(--line); padding-bottom: 6px; margin-bottom: 18px; }

/* badges */
.sp-badge { display:inline-flex; align-items:center; gap:6px; padding: 3px 10px; border-radius: 999px; font-size: 11.5px;
  font-weight: 600; border:1px solid; white-space: nowrap; line-height: 1.4; }
.sp-badge i { width:6px; height:6px; border-radius:50%; display:inline-block; }
.sp-badge.mono { font-family: var(--mono) !important; font-size: 10.5px; border-radius: 6px; padding: 2px 7px; }
.sp-badges { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin: 6px 0; }

/* hero */
.sp-hero { position:relative; overflow:hidden; border-radius:16px; border:1px solid var(--line); padding: 34px 36px;
  background: radial-gradient(circle at 85% 15%, rgba(254,205,211,.45) 0%, transparent 50%),
              radial-gradient(circle at 15% 45%, rgba(224,231,255,.7) 0%, transparent 50%),
              linear-gradient(135deg, #FFFFFF 0%, #FFF5F6 50%, #F8FAFC 100%);
  box-shadow: 0 4px 20px -2px rgba(15,23,42,.06); margin-bottom: 18px; }
.sp-hero.compact { padding: 26px 30px; }
.sp-tag { display:inline-flex; align-items:center; gap:7px; padding: 4px 12px; border-radius: 999px; background: var(--rose-50);
  border:1px solid var(--rose-200); color: var(--rose-2); font-size: 11.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.sp-tag svg { width:13px; height:13px; fill: var(--rose); }
.sp-hero h1 { font-size: 42px; line-height: 1.1; font-weight: 800; letter-spacing: -.03em; margin: 14px 0 10px; }
.sp-hero.compact h1 { font-size: 30px; font-weight: 700; margin: 12px 0 8px; }
.sp-hero p { font-size: 16.5px; line-height: 1.6; color: #475569; max-width: 860px; margin: 0; }
.sp-hero.compact p { font-size: 14.5px; }
.sp-grad { background: linear-gradient(90deg, #F43F5E, #E11D48); -webkit-background-clip:text; background-clip:text; color:transparent; }

/* cards */
[class*="st-key-card"] { background: var(--card); border: 1px solid var(--line) !important; border-radius: 12px; box-shadow: var(--sh1);
  padding: 18px 20px; }
div[data-testid="stVerticalBlockBorderWrapper"] { background: var(--card); border-color: var(--line) !important; border-radius: 12px !important; box-shadow: var(--sh1); }
.sp-feature { background: var(--card); border:1px solid var(--line); border-radius: 12px; padding: 20px; box-shadow: var(--sh1);
  transition: all .2s ease; min-height: 222px; margin-bottom: 12px; }
.sp-feature:hover { transform: translateY(-2px); box-shadow: var(--sh2); }
.sp-feature .ic { width:44px; height:44px; border-radius: 12px; display:grid; place-items:center; border:1px solid; margin-bottom: 14px; }
.sp-feature .ic svg { width:20px; height:20px; fill:none; stroke: currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }
.sp-feature h4 { font-size: 16px; font-weight: 700; margin: 0 0 6px; }
.sp-feature p { font-size: 13px; line-height: 1.6; color: var(--muted); margin: 0; }
.sp-section { display:flex; justify-content:space-between; align-items:center; margin: 6px 0 10px; }
.sp-eyebrow { font-family: var(--mono) !important; font-size: 11px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: #64748B; }
.sp-title { font-size: 16px; font-weight: 700; color: var(--text); }

/* stat tiles */
.sp-tiles { display:grid; gap: 12px; margin: 4px 0 16px; }
.sp-tile { background: var(--card); border:1px solid var(--line); border-radius: 12px; padding: 14px 16px; box-shadow: var(--sh1); }
.sp-tile .l { font-size: 12px; color: var(--muted); font-weight: 500; }
.sp-tile .v { font-family: var(--mono) !important; font-size: 22px; font-weight: 600; color: var(--text); margin-top: 4px; letter-spacing: -.01em; }
.sp-tile .s { font-size: 11.5px; color: var(--muted); margin-top: 2px; }

/* rule-check cards */
.sp-rule { display:flex; gap: 12px; align-items:flex-start; padding: 13px 14px; border-radius: 12px; border:1px solid; margin-bottom: 10px; }
.sp-rule .ri { width:24px; height:24px; border-radius:50%; display:grid; place-items:center; flex-shrink:0; margin-top:1px; }
.sp-rule .ri svg { width:14px; height:14px; fill:none; stroke-width:2.2; stroke-linecap:round; stroke-linejoin:round; }
.sp-rule .rt { display:flex; justify-content:space-between; gap: 10px; align-items:flex-start; }
.sp-rule .rt b { font-size: 13px; color: var(--text); }
.sp-rule .rb { font-size: 12.5px; color: #475569; margin-top: 4px; line-height: 1.55; }
.sp-rule .rc { margin-top: 7px; display:flex; flex-wrap:wrap; gap:6px; }
.sp-cite { font-family: var(--mono) !important; font-size: 10.5px; font-weight: 600; color: var(--rose-2); background:#FFFFFF;
  border:1px solid var(--rose-200); border-radius: 6px; padding: 2px 7px; }

/* ledger */
.sp-ledger { background:#FFFFFF; border:1px solid var(--line); border-radius: 10px; padding: 12px 14px; }
.sp-ledger .row { display:flex; justify-content:space-between; font-size: 12.5px; padding: 5px 0; color: #475569; }
.sp-ledger .row span:last-child { font-family: var(--mono) !important; color: var(--text); font-weight: 500; }
.sp-ledger .tot { border-top:1px solid var(--line); margin-top: 6px; padding-top: 9px; font-weight: 700; color: var(--text); }
.sp-ledger .tot span:last-child { color: var(--rose-2); font-size: 14px; font-weight: 700; }
.sp-hero-num { font-family: var(--mono) !important; font-size: 34px; font-weight: 600; color: var(--text); letter-spacing: -.02em; }

/* segmented bar */
.sp-seg { display:flex; gap:2px; height: 26px; margin: 12px 0 8px; }
.sp-seg div { border-radius: 4px; display:flex; align-items:center; padding-left: 8px; font-size: 11.5px; font-weight: 700;
  color: #0F172A; white-space: nowrap; overflow:hidden; min-width:0; font-family: var(--mono) !important; }
.sp-legend { display:flex; gap: 14px; flex-wrap: wrap; font-size: 12px; color: #475569; }
.sp-legend span:before { content:""; display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px;
  background: var(--sw); vertical-align:-1px; }

/* chat */
.sp-user { display:flex; justify-content:flex-end; margin: 6px 0 12px; }
.sp-user > div { max-width: 78%; background: var(--layer); border:1px solid var(--line); border-radius: 16px 4px 16px 16px; padding: 12px 14px; }
.sp-who { display:flex; justify-content:space-between; gap: 18px; font-size: 12px; font-weight: 600; color: var(--text); margin-bottom: 4px; }
.sp-who span { font-family: var(--mono) !important; font-size: 10.5px; color: var(--muted); font-weight: 500; }
.sp-msg { font-size: 13.5px; color: var(--text-2); line-height: 1.6; }
.sp-ai { display:flex; gap: 12px; margin: 6px 0 16px; }
.sp-ai .av { width:30px; height:30px; border-radius: 8px; background: var(--rose-50); border:1px solid var(--rose-200);
  display:grid; place-items:center; flex-shrink:0; }
.sp-ai .av svg { width:14px; height:14px; fill: var(--rose); }
.sp-ai .bd { flex:1; background:#FFFFFF; border:1px solid var(--line); border-radius: 4px 16px 16px 16px; padding: 16px; box-shadow: var(--sh1); }
.sp-ai .hd { display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px; }
.sp-ai .hd b { font-size: 13px; color: var(--text); }
.sp-ai .hd span { font-family: var(--mono) !important; font-size: 10.5px; color: var(--muted); }

/* tables */
.sp-table { width:100%; border-collapse: separate; border-spacing: 0; border:1px solid var(--line); border-radius: 8px; overflow:hidden;
  background:#FFFFFF; font-size: 13px; }
.sp-table th { background:#F8FAFC; color:#64748B; font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  text-align:left; padding: 10px 12px; border-bottom:1px solid var(--line); }
.sp-table td { padding: 11px 12px; border-bottom:1px solid var(--line); color: var(--text-2); }
.sp-table tr:last-child td { border-bottom: 0; }
.sp-table tr:hover td { background: #F8FAFC; }
.sp-table td.num { font-family: var(--mono) !important; font-variant-numeric: tabular-nums; color: var(--text); font-weight: 500; }

/* widgets */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button { border-radius: 10px !important; font-weight: 600 !important;
  border: 1px solid var(--line-2) !important; background: #FFFFFF; color: var(--text-2); box-shadow: var(--sh1); transition: all .15s ease; }
.stButton > button:hover, .stFormSubmitButton > button:hover { border-color: #94A3B8 !important; color: var(--text); background:#F8FAFC; }
.stButton > button[kind^="primary"], .stFormSubmitButton > button[kind^="primary"] {
  background: linear-gradient(90deg, #E11D48 0%, #BE123C 100%) !important; border: 0 !important; color: #FFFFFF !important;
  box-shadow: 0 4px 14px 0 rgba(225,29,72,.25); }
.stButton > button[kind^="primary"] *, .stFormSubmitButton > button[kind^="primary"] * { color:#FFFFFF !important; }
.stButton > button[kind^="primary"]:hover, .stFormSubmitButton > button[kind^="primary"]:hover { filter: brightness(1.05); }
div[data-baseweb="input"], div[data-baseweb="select"] > div, div[data-baseweb="textarea"] { border-radius: 10px !important;
  border-color: var(--line-2) !important; background: #FFFFFF !important; }
div[data-baseweb="input"] > div, div[data-baseweb="input"] input, div[data-baseweb="base-input"], div[data-baseweb="textarea"] textarea,
[data-testid="stDateInput"] input { background: #FFFFFF !important; }
div[data-baseweb="input"]:focus-within, div[data-baseweb="select"] > div:focus-within, div[data-baseweb="textarea"]:focus-within {
  border-color: #E11D48 !important; box-shadow: 0 0 0 2px rgba(225,29,72,.15); }
[data-testid="stFileUploaderDropzone"] { border-radius: 12px; border: 1.5px dashed var(--line-2); background: #F8FAFC; }
[data-testid="stExpander"] details { border-radius: 12px; border-color: var(--line); background: #FFFFFF; }
[data-testid="stChatInput"] { border-radius: 12px; border: 1px solid var(--line-2); }
[data-testid="stAlert"] { border-radius: 12px; }
[data-testid="stSegmentedControl"] button { border-radius: 10px !important; }
.sp-foot { display:flex; justify-content:space-between; gap: 16px; flex-wrap: wrap; margin-top: 36px; padding-top: 16px;
  border-top: 1px solid var(--line); font-size: 12px; color: var(--muted); }
</style>
""".replace('FONT', FONT_URL)


def inject():
    st.markdown(CSS, unsafe_allow_html=True)


SIGNED_OUT_CSS = """<style>
section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"], [data-testid="stExpandSidebarButton"] { display: none !important; }
.block-container { max-width: 1160px; padding-top: 4.2rem; }
</style>"""


def hide_sidebar():
    """Signed-out screens show no navigation: only the sign-in page exists until a session starts."""
    st.markdown(SIGNED_OUT_CSS, unsafe_allow_html=True)


AVATAR_COLOURS = ('#E11D48', '#4F46E5', '#0891B2', '#D97706', '#059669')


def avatar(name, key=''):
    """Initials in a coloured circle; the colour is stable per account."""
    initials = ''.join(part[0] for part in (name or '?').split()[:2]).upper()
    colour = AVATAR_COLOURS[sum(map(ord, key or name or '')) % len(AVATAR_COLOURS)]
    return '<div class="sp-avatar" style="background:%s">%s</div>' % (colour, escape(initials))


def html(markup):
    st.markdown(markup, unsafe_allow_html=True)


def svg(name, colour='currentColor'):
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="%s" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="%s"/></svg>' % (colour, SVG[name]))


def spark_svg():
    return '<svg viewBox="0 0 24 24"><path d="%s"/></svg>' % SPARK


def badge(tone, label, mono=False, dot=True):
    d, t, b, br = TONES[tone]
    return ('<span class="sp-badge%s" style="color:%s;background:%s;border-color:%s">%s%s</span>'
            % (' mono' if mono else '', t, b, br, '<i style="background:%s"></i>' % d if dot else '', escape(label)))


def badges(items):
    html('<div class="sp-badges">%s</div>' % ''.join(badge(tone, label) for tone, label in items))


def hero(tag, title, subtitle, gradient_words=None, compact=False, extra=''):
    title_html = escape(title)
    if gradient_words:
        title_html = title_html.replace(escape(gradient_words), '<span class="sp-grad">%s</span>' % escape(gradient_words))
    html('<div class="sp-hero%s"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">'
         '<span class="sp-tag">%s%s</span>%s</div><h1>%s</h1><p>%s</p></div>'
         % (' compact' if compact else '', spark_svg(), escape(tag), extra, title_html, escape(subtitle)))


def feature(icon, tone, title, text):
    hues = {'rose': ('#E11D48', '#FFF1F2', '#FECDD3'), 'amber': ('#D97706', '#FFFBEB', '#FDE68A'),
            'cyan': ('#0891B2', '#ECFEFF', '#A5F3FC'), 'indigo': ('#4F46E5', '#EEF2FF', '#C7D2FE')}
    c, b, br = hues[tone]
    html('<div class="sp-feature"><div class="ic" style="color:%s;background:%s;border-color:%s">%s</div><h4>%s</h4><p>%s</p></div>'
         % (c, b, br, svg(icon), escape(title), escape(text)))


def money(value, currency='INR'):
    if value in (None, ''):
        return '—'
    number = float(value)
    body = '{:,.2f}'.format(number) if number % 1 else '{:,.0f}'.format(number)
    return ('%s %s' % (currency, body)).strip()


def tiles(items, columns=4):
    cells = ''.join('<div class="sp-tile"><div class="l">%s</div><div class="v">%s</div><div class="s">%s</div></div>'
                    % (escape(l), escape(v), escape(s or '')) for l, v, s in items)
    html('<div class="sp-tiles" style="grid-template-columns:repeat(%d,minmax(0,1fr))">%s</div>' % (columns, cells))


def rule_card(tone, title, body, tag=None, citations=()):
    d, t, b, br = TONES[tone]
    icon = {'ok': 'check', 'warn': 'alert', 'bad': 'x', 'neutral': 'info', 'ai': 'info'}[tone]
    tag_html = badge(tone, tag, mono=True, dot=False) if tag else ''
    cites = ''.join('<span class="sp-cite">%s</span>' % escape(c) for c in citations)
    html('<div class="sp-rule" style="background:%s80;border-color:%s"><div class="ri" style="background:%s">%s</div>'
         '<div style="flex:1"><div class="rt"><b>%s</b>%s</div><div class="rb">%s</div>%s</div></div>'
         % (b, br, b, svg(icon, t), escape(title), tag_html, escape(body),
            '<div class="rc">%s</div>' % cites if cites else ''))


def ledger(rows, total=None):
    body = ''.join('<div class="row"><span>%s</span><span>%s</span></div>' % (escape(l), escape(v)) for l, v in rows)
    if total:
        body += '<div class="row tot"><span>%s</span><span>%s</span></div>' % (escape(total[0]), escape(total[1]))
    html('<div class="sp-ledger">%s</div>' % body)


def segmented_bar(values):
    total = sum(v for v in values.values() if v) or 0
    if not total:
        return
    blocks, legend = [], []
    for key in ('eligible', 'over_cap', 'excluded'):
        amount = values.get(key) or 0
        colour, name = PARTS[key]
        legend.append('<span style="--sw:%s">%s</span>' % (colour, name))
        if amount <= 0:
            continue
        share = amount / total
        label = '%d%%' % round(share * 100) if share >= 0.08 else ''
        blocks.append('<div style="flex:%f;background:%s" title="%s: %s (%d%%)">%s</div>'
                      % (share, colour, name, money(amount), round(share * 100), label))
    html('<div class="sp-seg" role="img" aria-label="Claimed total split into eligible, over cap and excluded">%s</div>'
         '<div class="sp-legend">%s</div>' % (''.join(blocks), ''.join(legend)))


def table(columns, rows, numeric=()):
    head = ''.join('<th>%s</th>' % escape(c) for c in columns)
    body = ''.join('<tr>%s</tr>' % ''.join('<td%s>%s</td>' % (' class="num"' if i in numeric else '', escape(str(v)))
                                           for i, v in enumerate(row)) for row in rows)
    html('<table class="sp-table"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (head, body))


def user_bubble(name, time_text, text):
    html('<div class="sp-user"><div><div class="sp-who">%s<span>%s</span></div><div class="sp-msg">%s</div></div></div>'
         % (escape(name), escape(time_text), escape(text)))


def ai_card_open(title, meta):
    return ('<div class="sp-ai"><div class="av">%s</div><div class="bd"><div class="hd"><b>%s</b><span>%s</span></div>'
            % (spark_svg(), escape(title), escape(meta)))


def paragraphs(text):
    return '<div class="sp-msg">%s</div>' % '<br>'.join(escape(line) for line in (text or '').splitlines())


def footer(company):
    html('<div class="sp-foot"><span>%s is a fictional company used for this capstone demonstration. The assistant searches '
         'and reviews only; it never books, pays or approves claims.</span><span>Policy 1.1 · fictional data only</span></div>'
         % escape(company))
