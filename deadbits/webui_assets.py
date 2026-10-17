"""Static assets of the local web interface, embedded so packaged builds need no data files."""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>DeadBits Salvage</title>
<link rel="stylesheet" href="/app.css">
<link rel="icon" href="data:,">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="bar">
  <div class="brand"><span class="mark" aria-hidden="true"></span><span class="word">DeadBits</span><span class="sub">Salvage</span></div>
  <ol class="steps" id="steps" aria-label="Progress"></ol>
  <div class="bar-end">
    <span class="pill" id="pill" title="This page only talks to the program running on this computer (127.0.0.1). No account, no upload.">
      <span class="dot" aria-hidden="true"></span><span id="pill-text">Offline</span>
    </span>
    <button class="icon-btn" id="theme" type="button" aria-label="Change colour theme"></button>
  </div>
</header>
<div class="banner" id="banner" role="alert" hidden></div>
<div class="layout" id="layout">
  <aside class="side" id="side" aria-label="Files"></aside>
  <main class="main" id="main" tabindex="-1"></main>
</div>
<div class="veil" id="veil" hidden><div><strong>Drop to add</strong><span>Files or a folder</span></div></div>
<div class="toasts" id="toasts" role="status" aria-live="polite"></div>
<input id="pick-files" type="file" multiple hidden>
<input id="pick-folder" type="file" webkitdirectory multiple hidden>
<script src="/app.js"></script>
</body>
</html>
"""

APP_CSS = r"""
:root{
  --paper:#f1eee7;--surface:#f8f6f1;--raised:#fff;--ink:#1c1a16;--ink2:#47433b;--muted:#767064;
  --line:#e1dccf;--line2:#cdc6b6;--brand:#b8400b;--brand-ink:#fff;--brand-soft:#f8e5d8;--focus:#1f5fd1;
  --ok:#17684f;--ok-bg:#dcefe6;--partial:#80520a;--partial-bg:#f7e8c4;--lost:#a82a22;--lost-bg:#f8dbd6;
  --unknown:#555b63;--unknown-bg:#e5e6e8;--prot:#464a9a;--prot-bg:#e3e4f5;
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Book Antiqua",Georgia,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
  --shadow:0 1px 2px rgba(40,30,10,.06),0 6px 20px rgba(40,30,10,.06);
}
:root[data-theme="dark"]{
  --paper:#0e0e0c;--surface:#151512;--raised:#1d1d19;--ink:#f1eee6;--ink2:#c8c3b6;--muted:#938d7f;
  --line:#2a2923;--line2:#3b392f;--brand:#ff8f57;--brand-ink:#1b0c04;--brand-soft:#33200f;--focus:#8ab4ff;
  --ok:#6fd3a8;--ok-bg:#12352a;--partial:#f2c160;--partial-bg:#3a2d0c;--lost:#ff9d93;--lost-bg:#44201d;
  --unknown:#b4bbc4;--unknown-bg:#2a2e33;--prot:#aaadff;--prot-bg:#25264b;--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.35);
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --paper:#0e0e0c;--surface:#151512;--raised:#1d1d19;--ink:#f1eee6;--ink2:#c8c3b6;--muted:#938d7f;
  --line:#2a2923;--line2:#3b392f;--brand:#ff8f57;--brand-ink:#1b0c04;--brand-soft:#33200f;--focus:#8ab4ff;
  --ok:#6fd3a8;--ok-bg:#12352a;--partial:#f2c160;--partial-bg:#3a2d0c;--lost:#ff9d93;--lost-bg:#44201d;
  --unknown:#b4bbc4;--unknown-bg:#2a2e33;--prot:#aaadff;--prot-bg:#25264b;--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.35);}}
*{box-sizing:border-box}
html{color-scheme:light dark;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 var(--sans);font-variant-numeric:tabular-nums;min-height:100vh}
button,input,select{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:6px}
.skip{position:absolute;left:-999px;top:8px;background:var(--raised);padding:8px 12px;border-radius:8px;z-index:50}
.skip:focus{left:8px}
[hidden]{display:none!important}

/* top bar */
.bar{position:sticky;top:0;z-index:20;height:56px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:16px;
  padding:0 20px;background:color-mix(in srgb,var(--paper) 88%,transparent);backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:10px;min-width:0}
.mark{width:22px;height:22px;border-radius:6px;flex:none;background:
  linear-gradient(90deg,var(--brand) 0 50%,transparent 50%) 0 0/8px 100%,var(--ink);position:relative;overflow:hidden}
.mark::after{content:"";position:absolute;inset:5px 5px 5px 11px;background:var(--paper);border-radius:2px}
.word{font:700 20px/1 var(--serif);letter-spacing:-.01em}
.sub{font:600 11px/1 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line2);padding:4px 6px;border-radius:5px}
.steps{display:flex;gap:6px;list-style:none;margin:0;padding:0;align-items:center}
.steps li{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px;font-weight:500}
.steps li+li::before{content:"";width:28px;height:1px;background:var(--line2);margin-right:2px}
.steps .n{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;font:600 11px var(--mono);border:1px solid var(--line2);background:var(--raised)}
.steps .cur{color:var(--ink);font-weight:650}.steps .cur .n{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.steps .done .n{background:var(--ok-bg);color:var(--ok);border-color:transparent}
.bar-end{display:flex;justify-content:flex-end;align-items:center;gap:10px}
.pill{display:inline-flex;align-items:center;gap:7px;font:600 12px var(--sans);padding:5px 10px;border-radius:999px;background:var(--ok-bg);color:var(--ok)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor}
.pill.down{background:var(--lost-bg);color:var(--lost)}
.banner{position:sticky;top:56px;z-index:19;padding:11px 20px;background:var(--lost);color:#fff;font-weight:600;font-size:14px;text-align:center}
.banner code{font:600 13px var(--mono);background:rgba(0,0,0,.25);padding:2px 7px;border-radius:5px}
.side{top:56px}
.icon-btn{width:34px;height:34px;display:grid;place-items:center;border-radius:9px;border:1px solid var(--line);background:var(--raised);cursor:pointer}
.icon-btn:hover{border-color:var(--line2)}

/* layout */
.layout{display:grid;grid-template-columns:344px minmax(0,1fr);min-height:calc(100vh - 56px)}
.side{border-right:1px solid var(--line);background:var(--surface);display:flex;flex-direction:column;position:sticky;top:56px;height:calc(100vh - 56px);overflow:hidden}
.main{padding:32px clamp(18px,4vw,48px) 64px;min-width:0;outline:none}
.main>.inner{max-width:960px;margin:0 auto}
.side-head{display:flex;justify-content:space-between;align-items:center;padding:16px 16px 10px}
.side-head h2{margin:0;font:650 13px var(--sans);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.count{font:600 12px var(--mono);color:var(--muted)}
.queue{list-style:none;margin:0;padding:4px 8px;overflow:auto;flex:1}
.q{display:grid;grid-template-columns:20px minmax(0,1fr) auto;gap:10px;align-items:center;width:100%;text-align:left;
  padding:9px 10px;border-radius:10px;border:1px solid transparent;background:transparent;cursor:pointer;position:relative}
.q:hover{background:var(--raised)}
.q[aria-selected="true"]{background:var(--raised);border-color:var(--line);box-shadow:var(--shadow)}
.q[aria-selected="true"]::before{content:"";position:absolute;left:-8px;top:10px;bottom:10px;width:3px;border-radius:3px;background:var(--brand)}
.q .nm{font:500 13px var(--mono);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.q .mt{font-size:12px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.q .rm{opacity:0;width:26px;height:26px;border-radius:7px;border:0;background:transparent;display:grid;place-items:center;cursor:pointer;color:var(--muted)}
.q:hover .rm,.q:focus-within .rm{opacity:1}.rm:hover{background:var(--line);color:var(--ink)}
.sdot{width:10px;height:10px;border-radius:50%;justify-self:center}
.t-ok{--tone:var(--ok);--tone-bg:var(--ok-bg)}.t-partial{--tone:var(--partial);--tone-bg:var(--partial-bg)}
.t-lost{--tone:var(--lost);--tone-bg:var(--lost-bg)}.t-unknown{--tone:var(--unknown);--tone-bg:var(--unknown-bg)}
.t-prot{--tone:var(--prot);--tone-bg:var(--prot-bg)}
.sdot{background:var(--tone)}
.side-sum{padding:4px 16px 12px}
.stack{display:flex;height:8px;border-radius:5px;overflow:hidden;background:var(--line);gap:2px}
.stack i{display:block;background:var(--tone);min-width:6px}
.legend{display:flex;flex-wrap:wrap;gap:4px 12px;margin:10px 0 0;font-size:12px;color:var(--ink2)}
.legend span{display:inline-flex;gap:6px;align-items:center}.legend b{font-weight:650}
.side-foot{padding:12px 16px 16px;border-top:1px solid var(--line);display:grid;gap:8px;background:var(--surface)}
.tiny{font-size:12px;color:var(--muted);margin:0}

/* buttons */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:40px;padding:0 16px;border-radius:10px;border:1px solid var(--line2);
  background:var(--raised);font-weight:600;cursor:pointer;white-space:nowrap}
.btn:hover{border-color:var(--ink2)}
.btn.primary{background:var(--brand);color:var(--brand-ink);border-color:transparent}
.btn.primary:hover{filter:brightness(1.07)}
.btn.sm{min-height:32px;padding:0 11px;font-size:13px;border-radius:8px}
.btn.ghost{background:transparent}
.btn:disabled{opacity:.5;cursor:not-allowed;filter:none}
.btn svg,.icon-btn svg{width:18px;height:18px;flex:none}

/* hero */
.eyebrow{font:600 12px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--brand);margin:0 0 14px}
.hero h1{font:700 clamp(30px,4.2vw,46px)/1.08 var(--serif);letter-spacing:-.02em;margin:0 0 14px;max-width:18ch}
.lead{font-size:17px;color:var(--ink2);max-width:58ch;margin:0 0 26px}
.drop{border:1.5px dashed var(--line2);border-radius:18px;background:var(--raised);padding:34px 24px;display:grid;justify-items:center;gap:10px;text-align:center;
  transition:border-color .15s,background .15s}
.drop.over{border-color:var(--brand);background:var(--brand-soft)}
.drop .ic{width:46px;height:46px;border-radius:13px;background:var(--brand-soft);color:var(--brand);display:grid;place-items:center}
.drop .ic svg{width:24px;height:24px}
.drop strong{font-size:17px}
.drop .row{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin-top:6px}
.how{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:22px}
.how div{padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
.how b{display:block;font-size:13px;margin-bottom:2px}.how span{font-size:13px;color:var(--muted)}
.card{background:var(--raised);border:1px solid var(--line);border-radius:16px;padding:20px;margin-top:18px;box-shadow:var(--shadow)}
.card h2,.card h3{margin:0 0 4px;font:650 16px var(--sans)}
.card .desc{margin:0 0 14px;color:var(--muted);font-size:13.5px}
.seg{display:inline-grid;grid-auto-flow:column;border:1px solid var(--line2);border-radius:10px;padding:3px;background:var(--surface);gap:2px}
.seg label{position:relative}.seg input{position:absolute;opacity:0;inset:0;cursor:pointer}
.seg span{display:block;padding:6px 12px;border-radius:7px;font-size:13px;font-weight:550;color:var(--ink2);cursor:pointer}
.seg input:checked+span{background:var(--ink);color:var(--paper)}
.seg input:focus-visible+span{outline:2px solid var(--focus);outline-offset:2px}
.samples{border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:12px 0;max-height:340px;overflow-y:auto}
.srow{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:12px;align-items:center;padding:9px 14px;border-bottom:1px solid var(--line);cursor:pointer;background:var(--raised)}
.srow:last-child{border-bottom:0}.srow:hover{background:var(--surface)}
.srow input{width:16px;height:16px;accent-color:var(--brand)}
.srow .nm{font:500 13px var(--mono)}.srow .hn{font-size:12.5px;color:var(--muted)}.srow .sz{font:12px var(--mono);color:var(--muted)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between}

/* results */
.headline{display:flex;flex-wrap:wrap;align-items:center;gap:10px 14px;justify-content:space-between;margin-bottom:6px}
.headline h1{margin:0;font:600 19px var(--mono);word-break:break-all}
.chips{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font:600 12px var(--sans);background:var(--tone-bg);color:var(--tone)}
.chip.mono{font-family:var(--mono);letter-spacing:.02em}.chip.plain{background:transparent;border:1px solid var(--line2);color:var(--ink2)}
.verdict{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:18px;align-items:center}
.vicon{width:52px;height:52px;border-radius:15px;display:grid;place-items:center;background:var(--tone-bg);color:var(--tone)}
.vicon svg{width:28px;height:28px}
.verdict h2{font:700 22px/1.2 var(--serif);margin:0 0 4px;letter-spacing:-.01em}
.verdict p{margin:0;color:var(--ink2);max-width:62ch}
.stats{display:flex;gap:22px}.stat b{display:block;font:700 26px/1 var(--serif)}.stat span{font-size:12px;color:var(--muted)}
.stat.warn b{color:var(--partial)}.stat.bad b{color:var(--lost)}
.map{position:relative;height:36px;border-radius:9px;background:
  repeating-linear-gradient(90deg,transparent 0 calc(25% - 1px),var(--line) calc(25% - 1px) 25%),var(--ok-bg);border:1px solid var(--line);margin-top:6px}
.map button{position:absolute;top:-5px;bottom:-5px;width:11px;margin-left:-5px;border:0;padding:0;background:transparent;cursor:pointer}
.map button::after{content:"";position:absolute;left:4px;top:0;bottom:0;width:3px;border-radius:2px;background:var(--partial)}
.map button.lossy::after{background:var(--lost)}
.map button:hover::after{width:5px;left:3px}
.axis{display:flex;justify-content:space-between;font:12px var(--mono);color:var(--muted);margin-top:6px}
.ribbon{display:flex;gap:2px;margin-top:6px;height:12px}.ribbon i{flex:1;min-width:2px;border-radius:2px;background:var(--ok)}.ribbon i.u{background:var(--partial)}
.cap{font-size:12.5px;color:var(--muted);margin:10px 0 0}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin:26px 0 0;overflow-x:auto;overflow-y:hidden;scrollbar-width:none}
.tab{padding:10px 14px;border:0;background:transparent;font-weight:600;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
.tab[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--brand)}
.tab .n{font:600 11px var(--mono);background:var(--line);padding:1px 6px;border-radius:9px;margin-left:6px}
.panel{padding-top:16px}
.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.search{flex:1;min-width:180px;max-width:320px;height:36px;border-radius:9px;border:1px solid var(--line2);background:var(--raised);padding:0 12px}
.check{display:inline-flex;gap:8px;align-items:center;font-size:13.5px;color:var(--ink2)}.check input{accent-color:var(--brand);width:16px;height:16px}
.tablewrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--raised);max-height:520px}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px}
th{position:sticky;top:0;background:var(--surface);text-align:left;font:600 11.5px var(--sans);letter-spacing:.04em;text-transform:uppercase;color:var(--muted);padding:9px 12px;border-bottom:1px solid var(--line);white-space:nowrap;z-index:1}
td{padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top;font-family:var(--mono);font-size:12.5px;white-space:nowrap}
td .clamp{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:break-word;word-break:normal;white-space:pre-wrap;max-width:40ch}
tr:last-child td{border-bottom:0}
tr.unv td{background:color-mix(in srgb,var(--partial-bg) 55%,transparent)}
tr.unv td:first-child{box-shadow:inset 3px 0 var(--partial)}
.badge{display:inline-block;font:700 10.5px var(--sans);letter-spacing:.05em;text-transform:uppercase;padding:2px 7px;border-radius:5px;background:var(--tone-bg);color:var(--tone)}
.dmg{display:grid;gap:10px}
.dm{display:grid;grid-template-columns:auto minmax(0,1fr);gap:14px;padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--raised);scroll-margin:90px}
.dm.hl{border-color:var(--brand);box-shadow:0 0 0 3px var(--brand-soft)}
.dm h4{margin:0 0 2px;font:650 14px var(--sans)}.dm p{margin:0;color:var(--ink2);font-size:13.5px}
.dm .det{font:12.5px var(--mono);color:var(--muted);margin-top:6px;word-break:break-word}
.dm .bar2{width:4px;border-radius:3px;background:var(--tone)}
.kv{display:grid;grid-template-columns:minmax(120px,200px) 1fr;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--raised)}
.kv dt,.kv dd{margin:0;padding:9px 14px;border-bottom:1px solid var(--line);font-size:13px}
.kv dt{color:var(--muted);background:var(--surface);font-weight:600}.kv dd{font-family:var(--mono);font-size:12.5px;word-break:break-word}
.kv dt:last-of-type,.kv dd:last-of-type{border-bottom:0}
.hex{font:12.5px/1.65 var(--mono);white-space:pre;overflow-x:auto;padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--raised);margin:0}
.hex .o{color:var(--muted)}.hex .d{background:var(--lost-bg);color:var(--lost);font-weight:700;border-radius:3px}
.hex .gap{color:var(--muted)}
.jump{display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
.jump input{height:34px;width:150px;border-radius:9px;border:1px solid var(--line2);background:var(--raised);padding:0 10px;font-family:var(--mono)}
pre.json{font:12.5px/1.6 var(--mono);margin:0;max-height:480px;overflow:auto;padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--raised);white-space:pre-wrap;word-break:break-word}
.cmd{display:flex;gap:8px;align-items:stretch}
.cmd code{flex:1;font:12.5px var(--mono);padding:10px 12px;border-radius:10px;background:var(--ink);color:var(--paper);overflow-x:auto;white-space:nowrap}
.empty{padding:26px;text-align:center;color:var(--muted);border:1px dashed var(--line2);border-radius:12px}
.busy{display:grid;justify-items:center;gap:14px;padding:80px 0;text-align:center}
.busy h2{font:700 26px var(--serif);margin:0}
.prog{width:min(360px,80%);height:6px;background:var(--line);border-radius:4px;overflow:hidden;position:relative}
.prog::after{content:"";position:absolute;inset:0 auto 0 -40%;width:40%;background:var(--brand);border-radius:4px;animation:slide 1.2s ease-in-out infinite}
@keyframes slide{to{left:100%}}
.totals{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px}
.tot{padding:14px 16px;border-radius:12px;background:var(--tone-bg);color:var(--tone)}.tot b{display:block;font:700 28px/1 var(--serif)}.tot span{font-size:12.5px;font-weight:600}
.notes{margin:10px 0 0;padding:12px 14px;border-radius:10px;background:var(--surface);border:1px solid var(--line);font:12.5px var(--mono);color:var(--ink2);white-space:pre-wrap}
.veil{position:fixed;inset:0;z-index:40;background:color-mix(in srgb,var(--paper) 82%,transparent);backdrop-filter:blur(6px);display:grid;place-items:center;pointer-events:none}
.veil div{display:grid;gap:4px;justify-items:center;padding:36px 56px;border:2px dashed var(--brand);border-radius:22px;background:var(--raised);font-size:22px}
.veil span{font-size:14px;color:var(--muted)}
.toasts{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);display:grid;gap:8px;z-index:60;width:min(440px,92vw)}
.toast{background:var(--ink);color:var(--paper);padding:11px 16px;border-radius:12px;font-size:14px;box-shadow:var(--shadow);animation:rise .18s ease-out}
.toast.err{background:var(--lost);color:#fff}
@keyframes rise{from{transform:translateY(8px);opacity:0}}

/* measured accuracy (additions only) */
.acc-basis{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;padding:12px 14px;border:1px solid var(--line);border-radius:12px;background:var(--tone-bg)}
.acc-basis strong{color:var(--ink)}
.acc-basis .badge{background:var(--raised)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:14px}
.metric{display:grid;gap:2px;padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--raised)}
.metric b{font:700 30px/1.05 var(--serif);letter-spacing:-.01em}
.metric .ml{font-weight:650;font-size:13px}.metric .mn{font:12px var(--mono);color:var(--muted)}
.acc-sentence{margin:14px 0 0;font-size:16px;max-width:70ch}
.acc-warn{margin-top:14px;padding:14px 16px;border-radius:12px;background:var(--partial-bg);color:var(--partial);border:1px solid color-mix(in srgb,var(--partial) 35%,transparent)}
.acc-warn p{margin:6px 0 0;color:var(--ink2);font-size:13.5px}
.acc-h{font:650 14px var(--sans);margin:22px 0 10px}
.how{margin-top:18px;border:1px solid var(--line);border-radius:12px;background:var(--surface)}
.how summary{cursor:pointer;padding:11px 14px;font-weight:600;font-size:13.5px}
.defs{margin:0;padding:0 14px 14px;display:grid;gap:10px}
.defs dt{font-weight:650;font-size:13px}.defs dd{margin:2px 0 0;color:var(--ink2);font-size:13px}
@media (max-width:980px){
  .layout{grid-template-columns:1fr}
  .side{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line)}
  .queue{max-height:240px}
  .steps li span.t{display:none}.steps li.cur span.t{display:inline}
  .verdict{grid-template-columns:auto 1fr}.stats{grid-column:1/-1}
  .how{grid-template-columns:1fr}
  .bar{grid-template-columns:auto 1fr auto;padding:0 12px}.steps{justify-content:center}
  .sub{display:none}
}
@media (max-width:560px){.kv{grid-template-columns:1fr}.main{padding-top:22px}.stats{gap:16px}.bar-end .pill{display:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

APP_JS = r"""
(function(){
'use strict';

/* ---------- small helpers ---------- */
var $=function(id){return document.getElementById(id);};
function h(tag,props){
  var e=document.createElement(tag),p=props||{};
  Object.keys(p).forEach(function(k){
    var v=p[k];if(v===null||v===undefined||v===false)return;
    if(k==='class')e.className=v;
    else if(k.slice(0,2)==='on')e.addEventListener(k.slice(2),v);
    else if(k==='text')e.textContent=v;
    else if(v===true)e.setAttribute(k,'');
    else e.setAttribute(k,v);
  });
  for(var i=2;i<arguments.length;i++)add(e,arguments[i]);
  return e;
}
function add(parent,c){
  if(c===null||c===undefined||c===false)return;
  if(Array.isArray(c)){c.forEach(function(x){add(parent,x);});return;}
  parent.appendChild(c.nodeType?c:document.createTextNode(String(c)));
}
var SVGNS='http://www.w3.org/2000/svg';
var ICONS={
  file:'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z M14 3v5h5',
  check:'M20 6 9 17l-5-5',
  alert:'M12 9v4 M12 17h.01 M10.3 3.9 2.4 17.6A2 2 0 0 0 4.1 20.6h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  lock:'M6 11h12v9H6z M8.5 11V8a3.5 3.5 0 0 1 7 0v3',
  question:'M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4.5 M12 18h.01 M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z',
  x:'M18 6 6 18 M6 6l12 12',
  upload:'M12 16V4 M7 9l5-5 5 5 M5 20h14',
  download:'M12 4v12 M7 11l5 5 5-5 M5 20h14',
  copy:'M9 9h10v11H9z M5 15V4h10',
  folder:'M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z',
  play:'M7 4.5v15l12-7.5z',
  sun:'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z M12 1v2 M12 21v2 M4.2 4.2l1.4 1.4 M18.4 18.4l1.4 1.4 M1 12h2 M21 12h2 M4.2 19.8l1.4-1.4 M18.4 5.6l1.4-1.4',
  moon:'M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z',
  auto:'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M12 2v20',
  report:'M6 3h9l4 4v14H6z M9 12h7 M9 16h7 M9 8h3'
};
function icon(name){
  var s=document.createElementNS(SVGNS,'svg');
  s.setAttribute('viewBox','0 0 24 24');s.setAttribute('fill','none');s.setAttribute('stroke','currentColor');
  s.setAttribute('stroke-width','1.8');s.setAttribute('stroke-linecap','round');s.setAttribute('stroke-linejoin','round');
  s.setAttribute('aria-hidden','true');
  (ICONS[name]||'').split(' M').forEach(function(d,i){
    var p=document.createElementNS(SVGNS,'path');p.setAttribute('d',(i?'M':'')+d);s.appendChild(p);
  });
  return s;
}
function fmtBytes(n){return n<1024?n+' B':n<1048576?(n/1024).toFixed(1)+' KiB':(n/1048576).toFixed(1)+' MiB';}
function hex(n,w){var s=n.toString(16);while(s.length<w)s='0'+s;return s;}
function plural(n,w,pl){return n+' '+(n===1?w:(pl||w+'s'));}
function toast(msg,err){
  var t=h('div',{class:'toast'+(err?' err':'')},msg);$('toasts').appendChild(t);
  setTimeout(function(){t.remove();},err?6500:3200);
}
function copyText(text){
  var done=function(){toast('Copied to clipboard');};
  if(navigator.clipboard&&window.isSecureContext!==false){navigator.clipboard.writeText(text).then(done,fallback);}else fallback();
  function fallback(){
    var ta=h('textarea',{style:'position:fixed;opacity:0'});ta.value=text;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');done();}catch(e){toast('Copy is not available here',true);}ta.remove();
  }
}
function saveBlob(name,type,text){
  var u=URL.createObjectURL(new Blob([text],{type:type})),a=h('a',{href:u,download:name});
  document.body.appendChild(a);a.click();a.remove();setTimeout(function(){URL.revokeObjectURL(u);},1500);
}

/* ---------- vocabulary (plain language for the contract's terms) ---------- */
var STATUS={
  ok:{label:'Fully recovered',tone:'ok',icon:'check'},
  partial:{label:'Partly recovered',tone:'partial',icon:'alert'},
  unsupported:{label:'Recognised, not readable',tone:'prot',icon:'lock'},
  unrecognized:{label:'Format not recognised',tone:'unknown',icon:'question'},
  failed:{label:'Could not be read',tone:'lost',icon:'x'}
};
var ORDER=['ok','partial','unsupported','unrecognized','failed'];
var FORMATS={
  'LIBRA-98':'Library circulation file','LABLOG':'Lab instrument log','VAULT':'Archive container','WKS':'Spreadsheet',
  'WPD':'Word-processor document','BRAVO':'Workstation text document','CVT':'Commodore 64 disk image',
  'EBCDIC-DUMP':'Mainframe record dump','WAD':'Game data archive','PAK':'Game data archive','UNKNOWN':'Unknown format'
};
var KINDS={
  truncated:['File ends early','The file stops before the data it announces. Everything after that point is gone.'],
  crc_mismatch:['Block checksum failed','A block\u2019s CRC does not match its contents, so its values may have been altered.'],
  checksum_mismatch:['Checksum failed','A stored checksum or total does not match the data, so it may have been altered.'],
  bad_length:['Length field is wrong','A size stored in the file contradicts the bytes that are actually there.'],
  unparsed_bytes:['Bytes could not be read','Some bytes did not fit any known structure and were skipped.'],
  count_mismatch:['Record count disagrees','The file declares a different number of items than it contains.'],
  invalid_value:['Value is not valid','A field holds a value that cannot be right, so it was flagged instead of trusted.'],
  oob_pointer:['Pointer leads outside the file','An offset points outside the file or into the wrong place.'],
  index_missing:['Index is missing','The table that locates the contents is gone, so nothing could be located safely.'],
  header_checksum:['Header checksum failed','The header\u2019s checksum does not match; values derived from it are less certain.'],
  encrypted:['Protected by a password','The contents are encrypted. DeadBits does not guess keys.'],
  unknown_record:['Unknown record type','The file contains a record type this tool does not know, so it was skipped.']
};
var MUT_LABEL={'':'None','truncate_50':'Cut in half','flip_middle':'Flip a byte','zero_block':'Zero a block'};

/* ---------- state ---------- */
var S={info:null,session:null,staged:[],busy:null,progress:null,run:null,selected:null,tab:'records',
  picked:{},damage:'',filter:'',unvOnly:false,shown:100,theme:'auto',hl:null,down:false};

function store(k,v){try{if(v===undefined)return localStorage.getItem(k);localStorage.setItem(k,v);}catch(e){return null;}}

var DOWN_MSG='DeadBits is not running any more. Start it again with "python -m deadbits.webui", then reload this page.';
function api(path,opts){
  return fetch(path,opts).catch(function(){setUp(false);throw new Error(DOWN_MSG);}).then(function(r){
    var ct=r.headers.get('Content-Type')||'';
    var body=ct.indexOf('json')>=0?r.json():r.text();
    return body.then(function(b){
      if(!r.ok)throw new Error(b&&b.error?b.error:('Request failed ('+r.status+')'));
      return b;
    });
  });
}
function ensureSession(){
  if(S.session)return Promise.resolve(S.session);
  return api('/api/sessions',{method:'POST'}).then(function(j){S.session=j.id;return j.id;});
}
function sessionGone(e){
  if(/session has ended/i.test(e.message)){S.session=null;S.staged=[];S.run=null;S.selected=null;render();toast('The working session expired. Add your files again.',true);return true;}
  return false;
}

/* ---------- actions ---------- */
function invalidate(){S.run=null;S.selected=null;S.tab='records';}
function uploadOne(file,kind){
  var q='?name='+encodeURIComponent(file.name)+(kind?'&mutate='+encodeURIComponent(kind):'');
  // Reading one byte first tells "this file cannot be read from your disk" (for example a cloud-only placeholder)
  // apart from "the program is not running": both make fetch fail with the same opaque error.
  return file.slice(0,Math.min(1,file.size)).arrayBuffer().then(function(){return sendFile(file,q);},function(){
    throw new Error('Could not read '+file.name+' from your disk. If it lives in a cloud folder, make it available offline first.');
  });
}
function sendFile(file,q){
  return api('/api/sessions/'+S.session+'/files'+q,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
}
function addFiles(files){
  files=Array.prototype.slice.call(files);
  if(!files.length)return;
  var big=files.filter(function(f){return f.size>S.info.maxUploadBytes;});
  if(big.length)toast(big[0].name+' is larger than the '+fmtBytes(S.info.maxUploadBytes)+' this screen accepts. Use the command line for very large files.',true);
  files=files.filter(function(f){return f.size<=S.info.maxUploadBytes;});
  if(!files.length)return;
  invalidate();S.busy='add';S.progress={done:0,total:files.length};render();
  ensureSession().then(function(){
    return files.reduce(function(p,f){
      return p.then(function(){return uploadOne(f,S.damage).then(function(r){S.progress.done++;render();if(r.renamed)toast('Saved as '+r.name+' to avoid a clash');});});
    },Promise.resolve());
  }).then(refreshStaged).catch(function(e){if(!sessionGone(e))toast(e.message,true);}).then(function(){S.busy=null;S.progress=null;render();});
}
function refreshStaged(){return api('/api/sessions/'+S.session+'/files').then(function(j){S.staged=j.files;});}
function addSamples(){
  var names=Object.keys(S.picked).filter(function(k){return S.picked[k];});
  if(!names.length){toast('Tick at least one sample first',true);return;}
  invalidate();S.busy='add';S.progress={done:0,total:names.length};render();
  ensureSession().then(function(){
    return api('/api/sessions/'+S.session+'/samples',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({names:names,mutate:S.damage})});
  }).then(function(){S.picked={};return refreshStaged();})
    .catch(function(e){if(!sessionGone(e))toast(e.message,true);}).then(function(){S.busy=null;S.progress=null;render();});
}
function removeStaged(name){
  invalidate();
  api('/api/sessions/'+S.session+'/files/'+encodeURIComponent(name),{method:'DELETE'}).then(refreshStaged)
    .catch(function(e){if(!sessionGone(e))toast(e.message,true);}).then(render);
}
function recover(){
  if(!S.staged.length||S.busy)return;
  S.busy='run';render();
  api('/api/sessions/'+S.session+'/run',{method:'POST'}).then(function(r){
    S.run=r;S.selected=r.files.length===1?r.files[0].name:'__report__';S.tab='records';
    S.busy=null;render();$('main').focus({preventScroll:true});window.scrollTo(0,0);loadAccuracy();
  }).catch(function(e){S.busy=null;if(!sessionGone(e)){toast(e.message,true);render();}});
}
function clearAll(){
  var id=S.session;S.session=null;S.staged=[];S.run=null;S.selected=null;S.picked={};render();
  if(id)api('/api/sessions/'+id,{method:'DELETE'}).catch(function(){});
}
function select(name){S.selected=name;S.hl=null;if(name==='__report__')S.tab='overview';else if(S.tab==='overview')S.tab='records';render();if(window.innerWidth<=980)$('main').scrollIntoView();else window.scrollTo(0,0);}

/* ---------- drag & drop / pickers ---------- */
function readEntry(entry){
  return new Promise(function(resolve){
    if(entry.isFile){entry.file(function(f){resolve([f]);},function(){resolve([]);});return;}
    if(entry.isDirectory){
      var reader=entry.createReader(),out=[];
      (function more(){reader.readEntries(function(list){
        if(!list.length){resolve(out);return;}
        Promise.all(list.filter(function(e){return e.isFile;}).map(readEntry)).then(function(parts){parts.forEach(function(p){out=out.concat(p);});more();});
      },function(){resolve(out);});})();
      return;
    }
    resolve([]);
  });
}
function handleDrop(dt){
  // Entries and files must be taken synchronously while the drop event is still alive.
  var tasks=[],items=dt.items||[];
  for(var i=0;i<items.length;i++){
    if(items[i].kind!=='file')continue;
    var entry=items[i].webkitGetAsEntry?items[i].webkitGetAsEntry():null;
    if(entry){tasks.push(readEntry(entry));continue;}
    var file=items[i].getAsFile();
    if(file)tasks.push(Promise.resolve([file]));
  }
  if(!tasks.length){addFiles(dt.files||[]);return;}
  Promise.all(tasks).then(function(parts){addFiles([].concat.apply([],parts));});
}
var dragDepth=0;
window.addEventListener('dragenter',function(e){if(e.dataTransfer&&Array.prototype.indexOf.call(e.dataTransfer.types,'Files')>=0){dragDepth++;$('veil').hidden=false;}});
window.addEventListener('dragleave',function(){dragDepth=Math.max(0,dragDepth-1);if(!dragDepth)$('veil').hidden=true;});
window.addEventListener('dragover',function(e){e.preventDefault();});
window.addEventListener('drop',function(e){e.preventDefault();dragDepth=0;$('veil').hidden=true;if(e.dataTransfer)handleDrop(e.dataTransfer);});

/* ---------- derived facts ---------- */
function unverifiedCount(doc){return doc.records.filter(function(r){return r.verified===false;}).length;}
function lossyCount(doc){return doc.damage.filter(function(d){return d.lossy;}).length;}
function sentence(doc){
  var n=doc.records.length,u=unverifiedCount(doc),l=lossyCount(doc),f=FORMATS[doc.format]||doc.format;
  if(doc.status==='ok')return n?'All '+plural(n,'record')+' in this '+f.toLowerCase()+' were read and nothing was lost.':'This '+f.toLowerCase()+' was read completely and nothing was lost. It holds no records.';
  if(doc.status==='partial'){
    var bits=[];
    bits.push('Recovered '+plural(n,'record')+'.');
    if(u)bits.push(plural(u,'record is','records are')+' flagged as unverified, so check '+(u===1?'it':'them')+' before relying on '+(u===1?'it':'them')+'.');
    if(l)bits.push(plural(l,'problem')+' cost data that could not be restored.');
    if(!u&&!l)bits.push('Some details could not be confirmed.');
    return bits.join(' ');
  }
  if(doc.status==='unsupported')return 'DeadBits recognised this as a '+f.toLowerCase()+' but cannot read its contents, for example because it is protected.';
  if(doc.status==='failed')return 'This looks like a '+f.toLowerCase()+' but is too damaged to read. Nothing was invented.';
  return 'The bytes do not match any format DeadBits knows, so nothing was decoded. It never guesses.';
}
function findFile(name){return S.run&&S.run.files.filter(function(f){return f.name===name;})[0];}

/* ---------- sidebar ---------- */
function renderSteps(){
  var step=S.run?3:(S.staged.length?2:1),labels=['Add files','Recover','Review'];
  var ol=$('steps');ol.textContent='';
  labels.forEach(function(t,i){
    var n=i+1,cls=n<step?'done':(n===step?'cur':'');
    ol.appendChild(h('li',{class:cls,'aria-current':n===step?'step':null},h('span',{class:'n'},n<step?icon('check'):String(n)),h('span',{class:'t'},t)));
  });
  ol.querySelectorAll('.n svg').forEach(function(s){s.style.width='12px';s.style.height='12px';});
}
function summaryBar(){
  var counts={};S.run.files.forEach(function(f){if(f.doc)counts[f.doc.status]=(counts[f.doc.status]||0)+1;});
  var stack=h('div',{class:'stack',role:'img','aria-label':'Status breakdown'}),legend=h('div',{class:'legend'});
  ORDER.forEach(function(s){
    if(!counts[s])return;var t='t-'+STATUS[s].tone;
    stack.appendChild(h('i',{class:t,style:'flex:'+counts[s],title:counts[s]+' '+STATUS[s].label}));
    legend.appendChild(h('span',{class:t},h('span',{class:'sdot'}),h('b',null,counts[s]),' '+STATUS[s].label.toLowerCase()));
  });
  return h('div',{class:'side-sum'},stack,legend);
}
function queueItem(opts){
  var el=h('div',{class:'q',role:'option',tabindex:opts.selected?'0':'-1','aria-selected':opts.selected?'true':'false',onclick:opts.onclick,
    onkeydown:function(e){
      if(e.key==='Enter'||e.key===' '){e.preventDefault();opts.onclick();}
      else if(e.key==='ArrowDown'||e.key==='ArrowUp'){
        e.preventDefault();var list=Array.prototype.slice.call(document.querySelectorAll('.q')),i=list.indexOf(el)+(e.key==='ArrowDown'?1:-1);
        if(list[i]){list[i].focus();if(opts.arrow)list[i].click();}
      }
    }},opts.lead,h('div',{style:'min-width:0'},h('div',{class:'nm',title:opts.name},opts.name),h('div',{class:'mt'},opts.meta)),opts.trail);
  return el;
}
function renderSide(){
  var side=$('side');side.textContent='';
  var total=S.staged.length;
  side.appendChild(h('div',{class:'side-head'},h('h2',null,S.run?'Results':'Your files'),h('span',{class:'count'},total?plural(total,'file'):'')));
  if(S.run)side.appendChild(summaryBar());
  var list=h('div',{class:'queue',role:'listbox','aria-label':'Files'});
  if(S.run){
    list.appendChild(queueItem({name:'Batch report',meta:plural(S.run.files.length,'file')+' \u00b7 report.json',selected:S.selected==='__report__',arrow:true,
      lead:h('span',{style:'display:grid;place-items:center;color:var(--muted)'},icon('report')),onclick:function(){select('__report__');}}));
    S.run.files.forEach(function(f){
      var d=f.doc,st=d?STATUS[d.status]:STATUS.failed;
      list.appendChild(queueItem({name:f.name,selected:S.selected===f.name,arrow:true,onclick:function(){select(f.name);},
        meta:(d?FORMATS[d.format]||d.format:'No result')+' \u00b7 '+st.label,lead:h('span',{class:'sdot t-'+st.tone,title:st.label})}));
    });
  }else if(total){
    S.staged.forEach(function(f){
      list.appendChild(queueItem({name:f.name,selected:false,onclick:function(){},meta:fmtBytes(f.size)+(f.note?' \u00b7 damaged for demo':''),
        lead:h('span',{style:'display:grid;place-items:center;color:var(--muted)'},icon('file')),
        trail:h('button',{class:'rm',type:'button','aria-label':'Remove '+f.name,title:'Remove',onclick:function(e){e.stopPropagation();removeStaged(f.name);}},icon('x'))}));
    });
    list.querySelectorAll('.rm svg').forEach(function(s){s.style.width='14px';s.style.height='14px';});
  }else list.appendChild(h('p',{class:'tiny',style:'padding:8px 10px'},'Nothing added yet. Files you add appear here.'));
  side.appendChild(list);
  var foot=h('div',{class:'side-foot'});
  if(S.run){
    foot.appendChild(h('a',{class:'btn primary',href:'/api/sessions/'+S.session+'/results.zip',download:'salvage-results.zip'},icon('download'),'Save all results (.zip)'));
    foot.appendChild(h('button',{class:'btn ghost',type:'button',onclick:clearAll},'Start over'));
    foot.appendChild(h('p',{class:'tiny'},'The zip holds the same per-file JSON and report.json the command line writes.'));
  }else if(total){
    foot.appendChild(h('button',{class:'btn primary',type:'button',disabled:(S.busy||S.down)?true:null,onclick:recover},icon('play'),'Recover '+plural(total,'file')));
    foot.appendChild(h('button',{class:'btn ghost',type:'button',onclick:clearAll},'Clear list'));
  }
  if(foot.childNodes.length)side.appendChild(foot);
}

/* ---------- main: add / ready ---------- */
function samplesCard(){
  var samples=S.info.samples;
  if(!samples.length)return null;
  var list=h('div',{class:'samples'});
  samples.forEach(function(s){
    var cb=h('input',{type:'checkbox','data-sample':s.name,checked:S.picked[s.name]?true:null,onchange:function(){S.picked[s.name]=cb.checked;}});
    list.appendChild(h('label',{class:'srow'},cb,h('div',null,h('div',{class:'nm'},s.name),h('div',{class:'hn'},s.hint||'No context hint')),h('span',{class:'sz'},fmtBytes(s.size))));
  });
  var dmg=h('div',{class:'seg',role:'radiogroup','aria-label':'Damage them first'});
  Object.keys(MUT_LABEL).forEach(function(k){
    dmg.appendChild(h('label',null,h('input',{type:'radio',name:'dmg',value:k,checked:S.damage===k?true:null,onchange:function(){S.damage=k;var c=$('dmg-cap');if(c)c.textContent=damageCaption();}}),h('span',null,MUT_LABEL[k])));
  });
  return h('section',{class:'card'},
    h('h2',null,'No damaged file handy? Try the organizer\u2019s samples'),
    h('p',{class:'desc'},'These are read-only copies of the kit. Tick some, optionally damage them on purpose, and watch what is recovered and how honestly the loss is reported.'),
    list,
    h('div',{class:'toolbar'},
      h('div',{style:'display:grid;gap:6px'},h('span',{class:'tiny'},'Damage the copies first (demo)'),dmg),
      h('div',{style:'display:flex;gap:8px'},
        h('button',{class:'btn sm',type:'button',onclick:function(){var all=samples.every(function(s){return S.picked[s.name];});samples.forEach(function(s){S.picked[s.name]=!all;});
          Array.prototype.forEach.call(document.querySelectorAll('input[data-sample]'),function(c){c.checked=!all;});}},'Select all / none'),
        h('button',{class:'btn sm primary',type:'button',onclick:addSamples},'Add selected'))),
    h('p',{class:'cap',id:'dmg-cap'},damageCaption()));
}
function damageCaption(){
  var tag={truncate_50:'cut-in-half',flip_middle:'flipped-byte',zero_block:'zeroed-block'}[S.damage];
  return tag?'Copies get a suffix in their name (for example .'+tag+') so an original and its damaged copy can sit side by side. The same choice also applies to files you add yourself.':'Choose a damage option to add deliberately damaged copies instead. It also applies to files you add yourself.';
}
function dropZone(compact){
  var z=h('div',{class:'drop',onclick:function(e){if(e.target.closest('button'))return;$('pick-files').click();}},
    h('div',{class:'ic'},icon('upload')),
    h('strong',null,compact?'Add more files':'Drop files or a folder here'),
    h('span',{class:'tiny'},'Only the files directly inside a folder are read, exactly like the command line.'),
    h('div',{class:'row'},
      h('button',{class:'btn primary',type:'button',onclick:function(){$('pick-files').click();}},icon('file'),'Choose files'),
      h('button',{class:'btn',type:'button',onclick:function(){$('pick-folder').click();}},icon('folder'),'Choose a folder')));
  return z;
}
function renderIntake(){
  var ready=S.staged.length;
  var inner=h('div',{class:'inner hero'});
  if(ready){
    inner.appendChild(h('p',{class:'eyebrow'},'Step 2 of 3'));
    inner.appendChild(h('h1',null,plural(ready,'file')+' ready to recover.'));
    inner.appendChild(h('p',{class:'lead'},'Nothing has been read yet. Press Recover and DeadBits will identify each file from its bytes, decode what is provably intact and report exactly what was lost.'));
    inner.appendChild(h('button',{class:'btn primary',type:'button',style:'min-height:48px;padding:0 24px;font-size:16px;margin-bottom:22px',disabled:(S.busy||S.down)?true:null,onclick:recover},icon('play'),'Recover '+plural(ready,'file')));
  }else{
    inner.appendChild(h('p',{class:'eyebrow'},'Offline \u00b7 no account \u00b7 nothing is uploaded'));
    inner.appendChild(h('h1',null,'Open the files nobody can open anymore.'));
    inner.appendChild(h('p',{class:'lead'},'DeadBits reads damaged legacy files, recovers what is provably intact, and tells you exactly what was lost. It never guesses a value and calls it verified.'));
  }
  inner.appendChild(dropZone(!!ready));
  if(!ready)inner.appendChild(h('div',{class:'how'},
    h('div',null,h('b',null,'1. Identify'),h('span',null,'The format is worked out from the bytes, not the file name.')),
    h('div',null,h('b',null,'2. Recover'),h('span',null,'Records are decoded and checked against checksums and bounds.')),
    h('div',null,h('b',null,'3. Report'),h('span',null,'Every loss is listed. Unconfirmed values are flagged, never passed off as verified.'))));
  var sc=samplesCard();if(sc)inner.appendChild(sc);
  return inner;
}
function renderBusy(){
  var run=S.busy==='run',p=S.progress;
  return h('div',{class:'inner busy'},h('div',{class:'prog','aria-hidden':'true'}),
    h('h2',null,run?'Recovering '+plural(S.staged.length,'file')+'\u2026':'Adding files\u2026'),
    h('p',{class:'lead',style:'margin:0'},run?'Same engine as ./salvage, running on this computer.':(p?p.done+' of '+p.total+' added':'')));
}

/* ---------- main: results ---------- */
function commands(){
  var base=S.run.location.replace(/[\\\/]out$/,'');
  var sep=S.run.location.indexOf('\\')>=0?'\\':'/';
  return './salvage "'+base+sep+'in" "'+base+sep+'out"';
}
function renderBatch(){
  var r=S.run,counts={};ORDER.forEach(function(s){counts[s]=0;});
  r.files.forEach(function(f){if(f.doc)counts[f.doc.status]++;});
  var inner=h('div',{class:'inner'});
  inner.appendChild(h('div',{class:'headline'},h('h1',{style:'font-family:var(--serif);font-size:28px'},'Batch report'),
    h('div',{class:'chips'},h('span',{class:'chip plain mono'},'v'+r.report.tool_version))));
  inner.appendChild(h('p',{class:'lead',style:'margin:4px 0 0'},plural(r.files.length,'file')+' processed. Select any file on the left for its records, damage and bytes.'));
  var tot=h('div',{class:'totals',style:'margin-top:18px'});
  ORDER.forEach(function(s){tot.appendChild(h('div',{class:'tot t-'+STATUS[s].tone},h('b',null,counts[s]),h('span',null,STATUS[s].label)));});
  inner.appendChild(tot);
  inner.appendChild(h('section',{class:'card'},h('h3',null,'Same result as the command line'),
    h('p',{class:'desc'},'This screen runs the program\u2019s own recovery code on a private copy of your files. Run the command below yourself and you get byte-identical output.'),
    h('div',{class:'cmd'},h('code',null,commands()),h('button',{class:'btn sm',type:'button',onclick:function(){copyText(commands());}},icon('copy'),'Copy')),
    h('p',{class:'cap'},'report.json SHA-256: '+r.reportSha256)));
  inner.appendChild(h('section',{class:'card'},h('h3',null,'Files'),
    h('div',{class:'tablewrap',style:'margin-top:10px'},h('table',null,
      h('thead',null,h('tr',null,['file','format','status','records','damage'].map(function(c){return h('th',null,c);}))),
      h('tbody',null,r.report.files.map(function(row){
        var st=STATUS[row.status];
        return h('tr',{style:'cursor:pointer',onclick:function(){select(row.file);}},h('td',null,row.file),h('td',null,row.format),
          h('td',null,h('span',{class:'badge t-'+st.tone},row.status)),h('td',null,row.records),h('td',null,row.damage));
      }))))));
  inner.appendChild(accuracyCard());
  if(r.stderr.length)inner.appendChild(h('section',{class:'card'},h('h3',null,'Messages from the tool'),h('p',{class:'desc'},'The command line prints these to its error stream.'),h('div',{class:'notes'},r.stderr.join('\n'))));
  inner.appendChild(h('div',{style:'display:flex;gap:10px;margin-top:18px;flex-wrap:wrap'},
    h('a',{class:'btn',href:'/api/sessions/'+S.session+'/out/report.json',download:'report.json'},icon('download'),'Download report.json')));
  return inner;
}
function fileMap(f){
  var doc=f.doc,size=f.size,box=h('div');
  if(!size){box.appendChild(h('p',{class:'cap'},'This file is empty, so there is nothing to map.'));return box;}
  var map=h('div',{class:'map',role:'group','aria-label':'File map with reported problems'});
  doc.damage.forEach(function(d,i){
    var pct=Math.min(100,d.offset/size*100),st=KINDS[d.kind]?KINDS[d.kind][0]:d.kind;
    map.appendChild(h('button',{type:'button',class:d.lossy?'lossy':'',style:'left:'+pct+'%',title:st+' at byte '+d.offset,
      'aria-label':st+' at byte '+d.offset,onclick:function(){S.tab='damage';S.hl=i;render();var n=document.querySelector('.dm.hl');if(n)n.scrollIntoView({block:'center'});}}));
  });
  box.appendChild(map);
  box.appendChild(h('div',{class:'axis'},h('span',null,'byte 0'),h('span',null,fmtBytes(size)+' ('+size+' bytes)')));
  var n=doc.records.length;
  if(n){
    var rb=h('div',{class:'ribbon',role:'img','aria-label':plural(n,'record')+', '+unverifiedCount(doc)+' unverified'});
    var cap=Math.min(n,90),step=n/cap;
    for(var i=0;i<cap;i++){
      var from=Math.floor(i*step),to=Math.max(from+1,Math.floor((i+1)*step)),u=false;
      for(var k=from;k<to&&k<n;k++)if(doc.records[k].verified===false)u=true;
      rb.appendChild(h('i',{class:u?'u':''}));
    }
    box.appendChild(rb);
  }
  box.appendChild(h('p',{class:'cap'},(doc.damage.length?'Each mark is a problem the decoder reported at that position (red: data lost, amber: nothing lost). ':'No problems were reported. ')+
    (n?'Below it, each cell is a record: green verified, amber unverified.':'')));
  return box;
}
function recordsPanel(f){
  var doc=f.doc,wrap=h('div',{class:'panel'});
  if(!doc.records.length){wrap.appendChild(h('div',{class:'empty'},doc.status==='unrecognized'?'Nothing was decoded from this file.':'No records were recovered.'));return wrap;}
  var cols=[],seen={};
  doc.records.forEach(function(r){Object.keys(r).forEach(function(k){if(!seen[k]&&k!=='verified'&&k!=='issues'){seen[k]=1;cols.push(k);}});});
  var holder=h('div'),count=h('span',{class:'tiny'});
  function rows(){
    var q=S.filter.toLowerCase();
    return doc.records.filter(function(r){
      if(S.unvOnly&&r.verified!==false)return false;
      if(!q)return true;
      return cols.some(function(c){var v=r[c];return v!==undefined&&v!==null&&String(typeof v==='object'?JSON.stringify(v):v).toLowerCase().indexOf(q)>=0;});
    });
  }
  function draw(){
    var list=rows();holder.textContent='';
    count.textContent=list.length===doc.records.length?plural(list.length,'record'):list.length+' of '+doc.records.length+' records';
    if(!list.length){holder.appendChild(h('div',{class:'empty'},'No records match.'));return;}
    var shown=list.slice(0,S.shown),tb=h('tbody');
    shown.forEach(function(r){
      var tr=h('tr',{class:r.verified===false?'unv':''});
      tr.appendChild(h('td',{style:'white-space:nowrap'},r.verified===false?h('span',{class:'badge t-partial',title:(r.issues&&r.issues.length?'Issues: '+r.issues.join(', '):'Could not be verified')},'Unverified'):h('span',{class:'badge t-ok'},'Verified')));
      cols.forEach(function(c){var v=r[c];tr.appendChild(h('td',null,v===undefined?'':h('span',{class:'clamp',title:typeof v==='object'?JSON.stringify(v):String(v)},v===null?'null':(typeof v==='object'?JSON.stringify(v):String(v)))));});
      tb.appendChild(tr);
    });
    holder.appendChild(h('div',{class:'tablewrap'},h('table',null,h('thead',null,h('tr',null,[h('th',null,'Status')].concat(cols.map(function(c){return h('th',null,c);})))),tb)));
    if(list.length>shown.length)holder.appendChild(h('p',{style:'margin:12px 0 0'},h('button',{class:'btn sm',type:'button',onclick:function(){S.shown+=200;draw();}},'Show '+Math.min(200,list.length-shown.length)+' more')));
  }
  var search=h('input',{class:'search',type:'search',placeholder:'Search records',value:S.filter,'aria-label':'Search records',oninput:function(){S.filter=search.value;S.shown=100;draw();}});
  var unv=unverifiedCount(doc);
  wrap.appendChild(h('div',{class:'filters'},search,
    unv?h('label',{class:'check'},h('input',{type:'checkbox',checked:S.unvOnly?true:null,onchange:function(e){S.unvOnly=e.target.checked;S.shown=100;draw();}}),'Only unverified ('+unv+')'):null,
    count,h('span',{style:'flex:1'}),
    h('button',{class:'btn sm',type:'button',onclick:function(){exportCsv(f,cols);}},icon('download'),'Export CSV')));
  wrap.appendChild(holder);draw();
  return wrap;
}
function exportCsv(f,cols){
  var all=['verified'].concat(cols,['issues']);
  function cell(v){if(v===undefined||v===null)return '';var s=typeof v==='object'?JSON.stringify(v):String(v);return /[",\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;}
  var lines=[all.join(',')];
  f.doc.records.forEach(function(r){lines.push(all.map(function(c){return c==='verified'?(r.verified===false?'no':'yes'):(c==='issues'?cell((r.issues||[]).join(' ')):cell(r[c]));}).join(','));});
  saveBlob(f.name+'.records.csv','text/csv;charset=utf-8','\ufeff'+lines.join('\r\n')+'\r\n');
}
function damagePanel(f){
  var doc=f.doc,wrap=h('div',{class:'panel'});
  if(!doc.damage.length){wrap.appendChild(h('div',{class:'empty'},'No damage was reported for this file.'));return wrap;}
  var list=h('div',{class:'dmg'});
  doc.damage.forEach(function(d,i){
    var k=KINDS[d.kind]||[d.kind,''],tone=d.lossy?'lost':'partial';
    list.appendChild(h('div',{class:'dm t-'+tone+(S.hl===i?' hl':'')},h('div',{class:'bar2'}),h('div',null,
      h('h4',null,k[0],' ',h('span',{class:'badge t-'+tone,style:'margin-left:6px'},d.lossy?'Data lost':'Nothing lost')),
      h('p',null,k[1]),
      h('div',{class:'det'},'byte '+d.offset+' (0x'+hex(d.offset,4)+') \u00b7 '+d.kind+(d.detail?' \u00b7 '+d.detail:'')))));
  });
  wrap.appendChild(list);return wrap;
}
function detailsPanel(f){
  var doc=f.doc,wrap=h('div',{class:'panel'}),kv=h('dl',{class:'kv'});
  function row(k,v){kv.appendChild(h('dt',null,k));kv.appendChild(h('dd',null,v===null||v===undefined?'null':(typeof v==='object'?JSON.stringify(v):String(v))));}
  row('File',doc.source_file);row('Size',fmtBytes(f.size)+' ('+f.size+' bytes)');row('Format',doc.format+' \u00b7 '+(FORMATS[doc.format]||''));row('Status',doc.status);
  Object.keys(doc.metadata).forEach(function(k){row(k,doc.metadata[k]);});
  wrap.appendChild(kv);return wrap;
}
function bytesPanel(f){
  var doc=f.doc,wrap=h('div',{class:'panel'}),out=h('div');
  var marks={};doc.damage.forEach(function(d){marks[d.offset]=1;});
  function window_(offset,len){return api('/api/sessions/'+S.session+'/bytes/'+encodeURIComponent(f.name)+'?offset='+offset+'&length='+len);}
  function dump(chunks){
    var pre=h('pre',{class:'hex',tabindex:'0','aria-label':'Hex dump'});
    chunks.forEach(function(c,ci){
      if(ci)pre.appendChild(h('span',{class:'gap'},'   \u2026\n'));
      var b=atob(c.base64),base=c.offset;
      for(var row=0;row<b.length;row+=16){
        pre.appendChild(h('span',{class:'o'},hex(base+row,6)+'  '));
        var ascii='';
        for(var i=0;i<16;i++){
          if(row+i<b.length){
            var code=b.charCodeAt(row+i),t=hex(code,2);
            pre.appendChild(marks[base+row+i]?h('span',{class:'d'},t):document.createTextNode(t));
            ascii+=(code>=32&&code<127)?String.fromCharCode(code):'.';
          }else{pre.appendChild(document.createTextNode('  '));ascii+=' ';}
          pre.appendChild(document.createTextNode(i===7?'  ':' '));
        }
        pre.appendChild(document.createTextNode(' |'+ascii+'|\n'));
      }
    });
    if(marks[f.size])pre.appendChild(h('span',{class:'gap'},'   (a reported problem sits at the end of the file, byte '+f.size+')\n'));
    out.textContent='';out.appendChild(pre);
  }
  function plan(){
    var starts=[0],seen={};
    doc.damage.slice(0,6).forEach(function(d){var s=Math.max(0,d.offset-48);s-=s%16;if(s<f.size&&!seen[s]){seen[s]=1;starts.push(s);}});
    starts.sort(function(a,b){return a-b;});
    var merged=[];starts.forEach(function(s){var e=s+(s===0?256:176),l=merged[merged.length-1];if(l&&s<=l[1])l[1]=Math.max(l[1],e);else merged.push([s,e]);});
    return merged;
  }
  function load(ranges){
    out.textContent='Loading\u2026';
    Promise.all(ranges.map(function(r){return window_(r[0],r[1]-r[0]);})).then(dump).catch(function(e){out.textContent=e.message;});
  }
  var input=h('input',{type:'text',placeholder:'Offset, e.g. 0x40 or 64','aria-label':'Jump to offset',onkeydown:function(e){if(e.key==='Enter')go();}});
  function go(){
    var v=input.value.trim(),n=/^0x/i.test(v)?parseInt(v,16):parseInt(v,10);
    if(!isFinite(n)||n<0||n>=Math.max(1,f.size)){toast('Enter an offset between 0 and '+Math.max(0,f.size-1),true);return;}
    n-=n%16;load([[n,n+256]]);
  }
  wrap.appendChild(h('div',{class:'jump'},input,h('button',{class:'btn sm',type:'button',onclick:go},'Go'),h('button',{class:'btn sm ghost',type:'button',onclick:function(){load(plan());}},'Reset view')));
  wrap.appendChild(h('p',{class:'cap',style:'margin:0 0 10px'},'Red bytes sit at an offset the decoder reported as a problem. This is not a map of what was recovered. Showing the start of the file and the surroundings of reported problems.'));
  wrap.appendChild(out);
  if(!f.size)out.appendChild(h('div',{class:'empty'},'This file is empty.'));else load(plan());
  return wrap;
}
function jsonPanel(f){
  var wrap=h('div',{class:'panel'}),pre=h('pre',{class:'json'},'Loading\u2026'),text='';
  api('/api/sessions/'+S.session+'/out/'+encodeURIComponent(f.name+'.json')).then(function(t){
    text=t;pre.textContent=t.length>300000?t.slice(0,300000)+'\n\u2026 (cut for display; download the file for everything)':t;
  }).catch(function(e){pre.textContent=e.message;});
  wrap.appendChild(h('div',{class:'filters'},
    h('a',{class:'btn sm',href:'/api/sessions/'+S.session+'/out/'+encodeURIComponent(f.name+'.json'),download:f.name+'.json'},icon('download'),'Download '+f.name+'.json'),
    h('button',{class:'btn sm',type:'button',onclick:function(){if(text)copyText(text);}},icon('copy'),'Copy'),
    h('span',{class:'tiny'},'The exact file the command line writes.')));
  wrap.appendChild(pre);return wrap;
}
function renderFile(f){
  var inner=h('div',{class:'inner'}),doc=f.doc;
  if(!doc){
    inner.appendChild(h('div',{class:'headline'},h('h1',null,f.name)));
    inner.appendChild(h('div',{class:'empty'},'No result file was written for this input.'));return inner;
  }
  var st=STATUS[doc.status],t='t-'+st.tone;
  inner.appendChild(h('div',{class:'headline'},h('h1',null,doc.source_file),
    h('div',{class:'chips'},h('span',{class:'chip '+t},st.label),h('span',{class:'chip plain'},doc.format+' \u00b7 '+(FORMATS[doc.format]||'')),h('span',{class:'chip plain mono',title:'status in the JSON'},doc.status))));
  var u=unverifiedCount(doc),l=lossyCount(doc);
  inner.appendChild(h('section',{class:'card '+t},
    h('div',{class:'verdict'},h('div',{class:'vicon'},icon(st.icon)),
      h('div',null,h('h2',null,st.label),h('p',null,sentence(doc)),f.note?h('p',{class:'cap'},f.note):null),
      h('div',{class:'stats'},h('div',{class:'stat'},h('b',null,doc.records.length),h('span',null,'records')),
        h('div',{class:'stat'+(u?' warn':'')},h('b',null,u),h('span',null,'unverified')),
        h('div',{class:'stat'+(l?' bad':'')},h('b',null,l),h('span',null,'data lost')))),
    h('div',{style:'margin-top:20px'},fileMap(f))));
  var tabs=[['records','Records',doc.records.length],['damage','Damage',doc.damage.length],['bytes','Bytes'],['details','Details'],['json','JSON'],['accuracy','Accuracy']];
  var bar=h('div',{class:'tabs',role:'tablist','aria-label':'Details'});
  tabs.forEach(function(tb){
    var el=h('button',{class:'tab',type:'button',role:'tab','aria-selected':S.tab===tb[0]?'true':'false',tabindex:S.tab===tb[0]?'0':'-1',
      onclick:function(){S.tab=tb[0];render();},
      onkeydown:function(e){var i=tabs.indexOf(tb);if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();S.tab=tabs[(i+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length][0];render();var n=document.querySelector('.tab[aria-selected="true"]');if(n)n.focus();}}},
      tb[1],tb[2]!==undefined?h('span',{class:'n'},tb[2]):null);
    bar.appendChild(el);
  });
  inner.appendChild(bar);
  var panels={records:recordsPanel,damage:damagePanel,bytes:bytesPanel,details:detailsPanel,json:jsonPanel,accuracy:accuracyPanel};
  inner.appendChild(panels[S.tab]?panels[S.tab](f):recordsPanel(f));
  return inner;
}

/* ---------- measured accuracy (additive: its own tab and batch card) ---------- */
function pct(v){return v===null||v===undefined?'-':(Math.round(v*1000)/10)+'%';}
function ratioText(r){return r&&r.denominator?r.numerator+' of '+r.denominator:'no records to compare';}
function fmtVal(v){
  if(v===undefined)return '(missing)';
  var s=v===null?'null':(typeof v==='object'?JSON.stringify(v):String(v));
  return s.length>90?s.slice(0,90)+'...':s;
}
var BASIS_TONE={'organizer':'ok','organizer-damaged':'prot','undamaged':'partial','none':'unknown'};
var BASIS_SHORT={'organizer':'Organizer answer key','organizer-damaged':'Organizer key, damaged copies','undamaged':'Undamaged copy (regression)'};
function howMeasured(){
  var d=h('details',{class:'how'},h('summary',null,'How is this measured?'));
  var dl=h('dl',{class:'defs'});
  [['Recovery','Records present in the recovered file, divided by the records in the answer key.'],
   ['Accuracy','Records whose every graded field equals the answer key, divided by the records in the key. A missing or wrong record counts as not accurate.'],
   ['Precision','Exactly right records, divided by recovered records plus extra records the key does not contain.'],
   ['Field accuracy','Individual fields that match the key, divided by all fields in the key.'],
   ['Answer key','The organizer’s published expected output for a kit file. For a damaged copy the key is that same file before damage. Where none is published, a damaged copy is compared with this tool’s own verified output for the undamaged file, which is a regression check and is labelled so.'],
   ['What it does not claim','These figures describe this file only. They are not a prediction for other files, and files without an answer key are never scored.']
  ].forEach(function(p){dl.appendChild(h('dt',null,p[0]));dl.appendChild(h('dd',null,p[1]));});
  d.appendChild(dl);return d;
}
function metric(label,ratio,value,hint){
  return h('div',{class:'metric',title:hint},h('b',null,pct(value)),h('span',{class:'ml'},label),h('span',{class:'mn'},ratioText(ratio)));
}
function accuracySentence(a){
  var c=a.counts,n=c.expected;
  if(!n)return 'The answer key lists no records for this file.';
  if(c.correct===n&&!c.unexpected)return 'All '+plural(n,'record')+' match the answer key, field for field.';
  var bits=[c.correct+' of '+plural(n,'record')+(n===1?' is':' are')+' exactly right'];
  if(c.wrong)bits.push(c.wrong+(c.wrong===1?' is wrong':' are wrong'));
  if(c.missing)bits.push(c.missing+(c.missing===1?' is gone':' are gone'));
  var s=bits.join(', ')+'.';
  if(c.unexpected)s+=' '+plural(c.unexpected,'extra record')+' the answer key does not contain.';
  return s;
}
function accuracyPanel(f){
  var wrap=h('div',{class:'panel'}),acc=S.run.accuracy;
  if(!acc){wrap.appendChild(h('div',{class:'empty'},'Measuring accuracy...'));return wrap;}
  var a=acc.files[f.name];
  if(!a){wrap.appendChild(h('div',{class:'empty'},'No accuracy information for this file.'));return wrap;}
  var tone=BASIS_TONE[a.basis]||'unknown';
  wrap.appendChild(h('div',{class:'acc-basis t-'+tone},h('span',{class:'badge t-'+tone},a.basis==='none'?'No answer key':'Measured against'),
    h('strong',null,a.basisLabel),a.sample&&a.basis!=='none'?h('span',{class:'tiny'},'kit file '+a.sample):null));
  if(!a.available){
    wrap.appendChild(h('div',{class:'empty',style:'margin-top:12px'},a.reason||'No answer key is available.'));
    var doc=f.doc;
    if(doc)wrap.appendChild(h('p',{class:'cap'},'What the tool can still tell you, without a key: '+plural(doc.records.length,'record')+' recovered, '+unverifiedCount(doc)+' flagged unverified, '+lossyCount(doc)+' damage entr'+(lossyCount(doc)===1?'y':'ies')+' with data lost. These are signals, not an accuracy figure.'));
    wrap.appendChild(howMeasured());return wrap;
  }
  var m=a.counts.measurements;
  wrap.appendChild(h('div',{class:'metrics'},
    metric('Recovery',m.recovery,m.recovery.value,'Records present divided by records in the answer key'),
    metric('Accuracy',m.accuracy,m.accuracy.value,'Records exactly right divided by records in the answer key'),
    metric('Precision',m.precision,m.precision.value,'Exactly right divided by recovered plus extra records'),
    metric('Field accuracy',{numerator:a.fields.correct,denominator:a.fields.expected},a.fields.expected?a.fields.correct/a.fields.expected:null,'Fields that match divided by fields in the key')));
  wrap.appendChild(h('p',{class:'acc-sentence'},accuracySentence(a)));
  if(a.basis==='undamaged')wrap.appendChild(h('p',{class:'cap'},'This is a regression comparison: the key is this tool’s own verified output for the undamaged file, so it shows how much survives damage, not independent correctness.'));
  if(a.agreement)wrap.appendChild(h('div',{class:'chips',style:'margin-top:10px'},
    h('span',{class:'chip t-'+(a.agreement.status?'ok':'lost')},'Status '+(a.agreement.status?'matches':'differs from')+' the key'),
    h('span',{class:'chip t-'+(a.agreement.damage?'ok':'lost')},'Damage report '+(a.agreement.damage?'matches':'differs from')+' the key'),
    h('span',{class:'chip t-'+(a.agreement.metadata?'ok':'lost')},'Metadata '+(a.agreement.metadata?'matches':'differs from')+' the key')));
  if(a.falseVerified>0){
    var why=a.integrity==='checksum'?'This format has checksums, so a wrong value should have been caught: treat this as a defect to report.'
      :(a.integrity==='size'?'This format only checks sizes, which cannot catch a change that keeps the length the same.'
        :'This format has no checksum or size check that could catch a change like this.');
    wrap.appendChild(h('div',{class:'acc-warn'},h('b',null,plural(a.falseVerified,'record')+(a.falseVerified===1?' is':' are')+' wrong but was not flagged as unverified.'),
      h('p',null,why+' So "verified" means "no check failed", not "proven correct". This is the system’s honest limit for this kind of damage.')));
  }
  if(a.wrong.length){
    var tb=h('tbody');
    a.wrong.forEach(function(w){
      w.fields.forEach(function(d,i){
        tb.appendChild(h('tr',{class:w.verified?'':'unv'},h('td',null,i===0?w.key.join(', '):''),h('td',null,d.field),h('td',null,fmtVal(d.expected)),h('td',null,fmtVal(d.actual)),
          h('td',null,i===0?(w.verified?h('span',{class:'badge t-lost'},'Not flagged'):h('span',{class:'badge t-ok'},'Flagged unverified')):'')));
      });
    });
    wrap.appendChild(h('h3',{class:'acc-h'},'Wrong records ('+(a.wrong.length+a.moreWrong)+')'));
    wrap.appendChild(h('div',{class:'tablewrap'},h('table',null,h('thead',null,h('tr',null,['record','field','answer key says','recovered','flagged?'].map(function(c){return h('th',null,c);}))),tb)));
    if(a.moreWrong)wrap.appendChild(h('p',{class:'cap'},'Showing the first '+a.wrong.length+'; '+a.moreWrong+' more are not listed.'));
  }
  if(a.missing.length)wrap.appendChild(h('p',{class:'cap'},'Records in the key that were not recovered: '+a.missing.map(function(k){return k.join(', ');}).join(' | ')));
  if(a.unexpected.length)wrap.appendChild(h('p',{class:'cap'},'Extra records the key does not contain: '+a.unexpected.map(function(k){return k.join(', ');}).join(' | ')));
  wrap.appendChild(howMeasured());
  return wrap;
}
function accuracyCard(){
  var acc=S.run.accuracy,card=h('section',{class:'card'},h('h3',null,'Measured accuracy'));
  if(!acc){card.appendChild(h('p',{class:'desc'},'Measuring...'));return card;}
  var groups=acc.summary.groups,keys=['organizer','organizer-damaged','undamaged'].filter(function(k){return groups[k];});
  card.appendChild(h('p',{class:'desc'},'Only files with an answer key are scored, and different answer keys are never averaged together. Open a file’s Accuracy tab for the detail.'));
  if(!keys.length){card.appendChild(h('div',{class:'empty'},'None of these files has an answer key, so no accuracy is claimed.'));}
  else{
    card.appendChild(h('div',{class:'tablewrap'},h('table',null,
      h('thead',null,h('tr',null,['measured against','files','in key','recovered','correct','wrong','missing','recovery','accuracy'].map(function(c){return h('th',null,c);}))),
      h('tbody',null,keys.map(function(k){var g=groups[k];
        return h('tr',null,h('td',null,BASIS_SHORT[k]),
          h('td',null,g.files),h('td',null,g.expected),h('td',null,g.recovered),h('td',null,g.correct),h('td',null,g.wrong),h('td',null,g.missing),h('td',null,pct(g.recovery)),h('td',null,pct(g.accuracy)));
      })))));
  }
  if(acc.summary.withoutAnswerKey)card.appendChild(h('p',{class:'cap'},plural(acc.summary.withoutAnswerKey,'file')+' without an answer key '+(acc.summary.withoutAnswerKey===1?'is':'are')+' not scored.'));
  card.appendChild(howMeasured());
  return card;
}
function loadAccuracy(){
  var id=S.session,run=S.run;
  api('/api/sessions/'+id+'/accuracy').then(function(a){if(S.run===run){run.accuracy=a;render();}}).catch(function(){});
}

/* ---------- render ---------- */
function render(){
  renderSteps();renderSide();
  var main=$('main');main.textContent='';
  if(!S.info){main.appendChild(h('div',{class:'inner busy'},h('div',{class:'prog'}),h('p',{class:'lead',style:'margin:0'},'Starting\u2026')));return;}
  if(S.busy)main.appendChild(renderBusy());
  else if(S.run){
    if(S.selected==='__report__')main.appendChild(renderBatch());
    else{var f=findFile(S.selected);main.appendChild(f?renderFile(f):renderBatch());}
  }else main.appendChild(renderIntake());
}

/* ---------- theme ---------- */
function applyTheme(){
  var r=document.documentElement;
  if(S.theme==='auto')r.removeAttribute('data-theme');else r.setAttribute('data-theme',S.theme);
  var b=$('theme');b.textContent='';b.appendChild(icon(S.theme==='light'?'sun':S.theme==='dark'?'moon':'auto'));
  b.title='Theme: '+S.theme+' (click to change)';b.setAttribute('aria-label','Colour theme: '+S.theme+'. Click to change.');
}
$('theme').addEventListener('click',function(){S.theme={auto:'light',light:'dark',dark:'auto'}[S.theme];store('deadbits-theme',S.theme);applyTheme();});
S.theme=store('deadbits-theme')||'auto';if(['auto','light','dark'].indexOf(S.theme)<0)S.theme='auto';applyTheme();

/* ---------- connection heartbeat ---------- */
function setUp(up){
  if(S.down===!up)return;
  S.down=!up;
  var pill=$('pill'),banner=$('banner');
  pill.classList.toggle('down',S.down);
  $('pill-text').textContent=S.down?'Stopped':'Offline';
  banner.hidden=!S.down;
  banner.textContent='';
  if(S.down){banner.appendChild(document.createTextNode('DeadBits has stopped running on this computer. Start it again with '));banner.appendChild(h('code',null,'python -m deadbits.webui'));banner.appendChild(document.createTextNode(' and reload this page.'));}
  else if(!S.info)loadInfo();
  render();
}
function ping(){
  fetch('/api/ping',{cache:'no-store'}).then(function(r){return r.ok;},function(){return false;}).then(setUp);
}
setInterval(ping,8000);

/* ---------- boot ---------- */
$('pick-files').addEventListener('change',function(e){addFiles(e.target.files);e.target.value='';});
$('pick-folder').addEventListener('change',function(e){
  var all=Array.prototype.slice.call(e.target.files),top=all.filter(function(f){return (f.webkitRelativePath||'').split('/').length<=2;});
  if(top.length<all.length)toast('Skipped '+plural(all.length-top.length,'file')+' in sub-folders. The command line reads one folder level only.');
  addFiles(top);e.target.value='';
});
window.addEventListener('pagehide',function(){if(S.session&&navigator.sendBeacon){/* sessions are removed when the server stops or after a day */}});
function loadInfo(){
  api('/api/info').then(function(info){S.info=info;render();}).catch(function(e){$('main').textContent=e.message;});
}
render();
loadInfo();
})();
"""
