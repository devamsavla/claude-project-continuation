/* Your Mind: the 3D brain that lights up as Mindy gets to know you, plus the family tree, money, clipboard and
   "your own Mindy" settings. Loaded after power.js and before app.js; screens register on window.MPV. */
(() => {
"use strict";
const V = window.MPV = window.MPV || {};
const REG_COL = { family: "#FFB8E8", goals: "#25D366", habits: "#B8FFE0", schedule: "#9FF7FF", money: "#FFE29A", places: "#C7B8FF",
  documents: "#F5F3EE", style: "#FF9DB0", work: "#8FD3FF", travel: "#FFC58A" };
const M = () => window.M;

// ---------------------------------------------------------------- the brain: a point cloud in two hemispheres, drawn on canvas
function brainPoints(n = 2200) {
  const pts = [], regs = Object.keys(REG_COL);
  let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  for (let i = 0; i < n; i++) {
    const side = i % 2 ? 1 : -1;
    const u = rnd() * Math.PI * 2, v = Math.acos(2 * rnd() - 1);
    const fold = 1 + 0.07 * Math.sin(u * 7 + v * 5) + 0.05 * Math.sin(v * 11);   // the folds of a brain
    let x = 0.62 * Math.sin(v) * Math.cos(u) * fold, y = 0.7 * Math.cos(v) * fold, z = 0.95 * Math.sin(v) * Math.sin(u) * fold;
    x = x * 0.92 + side * 0.5; if (side * x < 0.06) x = side * (0.06 + Math.abs(x) * 0.2);     // the gap between hemispheres
    y = y < 0 ? y * 0.75 : y;
    const ang = (Math.atan2(z, y) + Math.PI) / (Math.PI * 2);                                     // regions wrap around the brain
    const reg = regs[Math.floor(((ang + (side > 0 ? 0.5 : 0)) % 1) * 5) + (side > 0 ? 5 : 0)];
    pts.push({ x, y, z, reg });
  }
  return pts;
}

function mountBrain(canvas, data, onPick) {
  const pts = brainPoints(), ctx = canvas.getContext("2d"), dpr = Math.min(2, window.devicePixelRatio || 1);
  const fill = {}; data.regions.forEach(r => fill[r.id] = r.fill);
  let rotY = 0.6, rotX = -0.25, drag = null, sel = null, raf, t0 = performance.now(), auto = true;
  function size() { const w = canvas.clientWidth; canvas.width = w * dpr; canvas.height = w * 0.82 * dpr; canvas.style.height = w * 0.82 + "px"; }
  size(); window.addEventListener("resize", size);
  function proj(p) {
    const cy = Math.cos(rotY), sy = Math.sin(rotY), cx = Math.cos(rotX), sx = Math.sin(rotX);
    let x = p.x * cy + p.z * sy, z = -p.x * sy + p.z * cy, y = p.y * cx - z * sx; z = p.y * sx + z * cx;
    const s = canvas.width * 0.36, k = 2.6 / (2.6 + z);
    return { X: canvas.width / 2 + x * s * k, Y: canvas.height / 2 - y * s * k, z, k };
  }
  function draw(now) {
    if (auto && !drag) rotY += 0.0035;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const pulse = 0.5 + 0.5 * Math.sin((now - t0) / 600);
    const P = pts.map(p => ({ p, ...proj(p) })).sort((a, b) => b.z - a.z);
    for (const q of P) {
      const f = fill[q.p.reg] || 0, lit = f > 0, on = sel === q.p.reg;
      const a = (lit ? 0.35 + 0.65 * f : 0.22) * (0.55 + 0.45 * (1 - (q.z + 1) / 2)) * (on ? 0.7 + 0.3 * pulse : 1);
      ctx.fillStyle = lit || on ? REG_COL[q.p.reg] : "#6B747B";
      ctx.globalAlpha = Math.max(0.05, Math.min(1, on ? a + 0.35 : a));
      const r = (lit ? 1.7 : 1.2) * q.k * dpr * (on ? 1.4 : 1);
      ctx.beginPath(); ctx.arc(q.X, q.Y, r, 0, 6.283); ctx.fill();
    }
    ctx.globalAlpha = 1;
    raf = requestAnimationFrame(draw);
  }
  raf = requestAnimationFrame(draw);
  const pos = e => { const b = canvas.getBoundingClientRect(), t = e.touches ? e.touches[0] : e; return [(t.clientX - b.left) * dpr, (t.clientY - b.top) * dpr]; };
  canvas.addEventListener("pointerdown", e => { drag = { p: pos(e), r: [rotY, rotX], moved: 0 }; canvas.setPointerCapture(e.pointerId); });
  canvas.addEventListener("pointermove", e => { if (!drag) return; const [x, y] = pos(e); const dx = x - drag.p[0], dy = y - drag.p[1];
    drag.moved = Math.max(drag.moved, Math.abs(dx) + Math.abs(dy)); rotY = drag.r[0] + dx / 220; rotX = Math.max(-1, Math.min(1, drag.r[1] + dy / 260)); });
  canvas.addEventListener("pointerup", e => {
    const d = drag; drag = null; if (!d || d.moved > 8) return; auto = false;
    const [x, y] = pos(e); let best = null, bd = 1e9;
    for (const p of pts) { const q = proj(p); if (q.z > 0.3) continue; const dd = (q.X - x) ** 2 + (q.Y - y) ** 2; if (dd < bd) { bd = dd; best = p; } }
    if (best && bd < (40 * dpr) ** 2) { sel = best.reg; onPick(best.reg); }
  });
  return { select(r) { sel = r; auto = false; }, update(regions) { regions.forEach(r => fill[r.id] = r.fill); }, stop() { cancelAnimationFrame(raf); } };
}


// ---------------------------------------------------------------- the mind map: 8 branches, 48 neurons. Dark until you use them.
const BR_COL = { people: "#25D366", memory: "#C7B8FF", time: "#9FF7FF", money: "#FFE29A", family: "#FFB8E8", safety: "#FF9DB0", papers: "#F5F3EE", create: "#8FD3FF" };
function mapSVG(D, focus) {
  const C = 200, rad = d => (d - 90) * Math.PI / 180, pt = (a, r) => [C + r * Math.cos(rad(a)), C + r * Math.sin(rad(a))];
  let lines = "", dots = "", labels = "";
  D.branches.forEach((b, i) => {
    const a = i * 45, col = BR_COL[b.id], dim = focus && focus !== b.id;
    const [bx, by] = pt(a, 86), [cx1, cy1] = pt(a + 14, 46);
    const on = b.lit > 0;
    lines += `<path d="M${C} ${C} Q${cx1.toFixed(1)} ${cy1.toFixed(1)} ${bx.toFixed(1)} ${by.toFixed(1)}" stroke="${on ? col : "#2A3238"}" stroke-width="${on ? 2.6 : 1.6}" fill="none" opacity="${dim ? .25 : on ? .9 : .7}"/>`;
    b.nodes.forEach((n, j) => {
      const off = (j - 2.5) * 7.4, r = j % 2 ? 176 : 148, [nx, ny] = pt(a + off, r), [mx, my] = pt(a + off * .45, 118);
      const st = n.state, c = st === "dark" ? "#3A434A" : col;
      lines += `<path d="M${bx.toFixed(1)} ${by.toFixed(1)} Q${mx.toFixed(1)} ${my.toFixed(1)} ${nx.toFixed(1)} ${ny.toFixed(1)}" stroke="${c}" stroke-width="${st === "wired" ? 2 : 1}" fill="none" opacity="${dim ? .2 : st === "dark" ? .55 : .8}" ${st === "dark" ? 'stroke-dasharray="2 3"' : ""}/>`;
      dots += `<g class="nr ${st}${D.spark && D.spark.id === n.id ? " spark" : ""}" data-n="${n.id}" opacity="${dim ? .3 : 1}" role="button" tabindex="0" aria-label="${n.name}, ${st}">
        <circle cx="${nx.toFixed(1)}" cy="${ny.toFixed(1)}" r="15" fill="transparent"/>
        ${st === "wired" ? `<circle cx="${nx.toFixed(1)}" cy="${ny.toFixed(1)}" r="11" fill="${col}" opacity=".22"/>` : ""}
        <circle cx="${nx.toFixed(1)}" cy="${ny.toFixed(1)}" r="${st === "wired" ? 7 : st === "sparked" ? 5.5 : 4.5}" fill="${st === "dark" ? "#0B0E10" : col}" stroke="${st === "dark" ? "#59636B" : col}" stroke-width="1.4"/></g>`;
    });
    dots += `<g class="brn" data-br="${b.id}" role="button" tabindex="0" aria-label="${b.name} branch, ${b.lit} of 6 lit" opacity="${dim ? .35 : 1}">
      <circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="19" fill="#0B0E10" stroke="${on ? col : "#3A434A"}" stroke-width="2"/>
      <text x="${bx.toFixed(1)}" y="${(by + 6).toFixed(1)}" text-anchor="middle" font-size="16">${b.emoji}</text></g>`;
    const lx = bx, ly = by + 28;
    labels += `<text x="${lx.toFixed(1)}" y="${(ly + 3).toFixed(1)}" text-anchor="middle" stroke="#000" stroke-width="3" paint-order="stroke" font-size="8.5" font-weight="700" fill="${on ? col : "#6B747B"}" opacity="${dim ? .3 : 1}" letter-spacing=".06em">${b.name.toUpperCase()}</text>`;
  });
  return `<svg viewBox="-6 -6 412 412" class="mindmap" aria-label="Your mind map">${lines}
    <circle cx="${C}" cy="${C}" r="34" fill="#0B0E10" stroke="#25D366" stroke-width="2"/>
    <text x="${C}" y="${C - 2}" text-anchor="middle" font-size="19" font-weight="800" fill="#F5F3EE">${D.lit}</text>
    <text x="${C}" y="${C + 13}" text-anchor="middle" font-size="8" fill="#8C959D" letter-spacing=".08em">OF ${D.total} LIT</text>${dots}<g pointer-events="none">${labels}</g></svg>`;
}

V.mindmap = async function (host, opts = {}) {
  const { esc, api, toast, sheet, closeSheet } = M();
  let D, focus = opts.focus || null;
  try { D = await api("/mind/map"); } catch (e) { host.innerHTML = ""; return; }
  const find = id => { for (const b of D.branches) for (const n of b.nodes) if (n.id === id) return [n, b]; return [null, null]; };
  function draw() {
    const fb = focus && D.branches.find(b => b.id === focus);
    const sp = D.spark;
    host.innerHTML = `${mapSVG(D, focus)}
      <div class="mm-key small muted"><span><i class="k dark"></i>dark</span><span><i class="k sparked"></i>sparked · tried once</span><span><i class="k wired"></i>wired · 3+ times</span></div>
      ${fb ? `<div class="card"><div class="row"><div class="grow"><div class="eyebrow" style="color:${BR_COL[fb.id]}">${fb.emoji} ${esc(fb.name)} · ${fb.lit}/6 lit</div>
          <div class="small muted">${esc(fb.line)}</div></div><button class="btn sm ghost" data-all>All</button></div>
          ${fb.nodes.map(n => `<button class="list-item nrow" data-n="${n.id}"><span class="dotk ${n.state}" style="--c:${BR_COL[fb.id]}"></span>
            <div class="grow" style="text-align:left"><b>${n.emoji} ${esc(n.name)}</b><div class="small muted">${esc(n.why)}${n.rare != null && n.state === "wired" ? ` · only ${n.rare}% have this wired` : ""}</div></div>
            <span class="small ${n.state === "dark" ? "g" : "muted"}">${n.state === "dark" ? "TRY →" : n.state === "wired" ? "⚡" : "✓"}</span></button>`).join("")}</div>`
        : sp ? `<button class="sticker spark-card" data-n="${sp.id}"><div class="eyebrow">Today's spark</div>
          <h3 style="margin:6px 0 4px">${sp.emoji} ${esc(sp.name)}</h3><div>${esc(sp.why)}</div>
          <div class="small" style="margin-top:8px;opacity:.7">${sp.left_in_branch} still dark on this branch · one tap, no typing</div></button>` : ""}`;
    host.querySelectorAll("[data-n]").forEach(el => { el.onclick = () => open(el.dataset.n); el.onkeydown = e => { if (e.key === "Enter") open(el.dataset.n); }; });
    host.querySelectorAll("[data-br]").forEach(el => { el.onclick = () => { focus = focus === el.dataset.br ? null : el.dataset.br; draw(); }; el.onkeydown = e => { if (e.key === "Enter") el.onclick(); }; });
    const all = host.querySelector("[data-all]"); if (all) all.onclick = () => { focus = null; draw(); };
    if (opts.onChange) opts.onChange(D);
  }
  function open(id) {
    const [n, b] = find(id); if (!n) return;
    sheet(`<div class="eyebrow" style="color:${BR_COL[b.id]}">${b.emoji} ${esc(b.name)} · ${n.state === "dark" ? "dark" : n.state === "wired" ? "⚡ wired" : "sparked"}</div>
      <h2 style="margin:6px 0">${n.emoji} ${esc(n.name)}</h2><p class="muted" style="margin-top:0">${esc(n.why)}</p>
      <div id="tryout"></div>
      <button class="btn" data-try style="width:100%;margin-top:8px">${n.kind === "demo" ? "👀 See it happen" : n.state === "dark" ? "⚡ Try it. One tap" : "Do it again"}</button>
      ${n.kind === "demo" ? `<div class="small muted" style="margin-top:8px;text-align:center">A preview. Nothing gets sent to anyone.</div>` : ""}`);
    const btn = document.querySelector("#overlay [data-try]"), out = document.querySelector("#overlay #tryout");
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = "…";
      try {
        const r = await api(`/neurons/${id}/try`, { body: {} });
        if (r.kind === "open") { closeSheet(); focus = r.to; }
        else if (r.kind === "demo") out.innerHTML = `<div class="card demo">${r.preview.split("\n").filter(Boolean).map(l => `<div class="small" style="margin:4px 0">${esc(l)}</div>`).join("")}</div>`;
        else out.innerHTML = `<div class="card"><div class="small muted">You: “${esc(r.said)}”</div><div style="margin-top:6px;white-space:pre-wrap">${esc((r.reply || "Done.").replace(/\n\n[✨⚡].*$/s, ""))}</div>
          ${(r.links || []).slice(0, 2).map(([l, u]) => `<a class="btn sm ghost" style="margin:8px 6px 0 0" href="${esc(u)}" target="_blank" rel="noopener">${esc(l)}</a>`).join("")}
          ${(r.images || []).slice(0, 3).map(u => `<img src="${esc(u)}" alt="" style="width:31%;border-radius:10px;margin:6px 1% 0 0">`).join("")}</div>`;
        D = r.map;
        btn.disabled = false;
        btn.textContent = r.lit ? (n.state === "dark" ? "✨ Neuron lit · close" : "⚡ Wired · close") : "Close";
        btn.onclick = () => closeSheet();
        if (r.lit) toast(n.state === "dark" ? `✨ ${n.name} lit` : `⚡ ${n.name} wired`, `${D.lit}/${D.total} neurons lit`);
        draw();
      } catch (e) { btn.disabled = false; btn.textContent = "Try again"; toast(e.message); }
    };
  }
  draw();
};

// ---------------------------------------------------------------- Brain screen
let brainCtl = null;
V.brain = async function (v, arg) {
  const { esc, api, toast, mindy } = M();
  if (brainCtl) brainCtl.stop();
  v.innerHTML = `<div class="empty">${mindy("think", 90)}</div>`;
  let D; try { D = await api("/mind"); } catch (e) { v.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const B = D.brain;
  v.innerHTML = `
    <header class="top"><div><div class="eyebrow g">Your mind</div><h1 class="big">${B.score}<i style="font-size:22px"> / 1000</i></h1>
      <div class="small muted">${esc(B.level)} · ${esc(D.mindy.name)} knows you ${Math.round(D.score)}%</div></div>
      <button class="btn sm ghost" data-b="share">Share</button></header>
    <div id="mapbox"></div>
    <h2 class="sec"><span>What ${esc(D.mindy.name)} knows about you</span></h2>
    <canvas id="brain" style="width:100%;display:block;touch-action:none;margin-top:6px" aria-label="Your brain. Tap a glowing area."></canvas>
    <div class="chips" id="regions" role="group" aria-label="Areas of your mind">${D.regions.map(r =>
      `<button class="chip" data-reg="${r.id}" style="border-color:${REG_COL[r.id]}55">${esc(r.label)} <span class="muted">${Math.round(r.fill * 100)}%</span></button>`).join("")}</div>
    <div id="qcard"></div>
    <h2 class="sec"><span>Habits</span><button data-b="habit">+ ADD</button></h2>
    <div class="card">${D.habits.length ? D.habits.map(h => `<div class="list-item"><button class="check ${h.today ? "on" : ""}" data-hab="${h.id}" aria-label="Done today"></button>
      <div class="grow"><b>${esc(h.title)}</b><div class="small muted">🔥 ${h.streak}-day streak</div></div></div>`).join("") : `<div class="small muted">Pick one tiny daily habit. Mindy keeps the streak.</div>`}</div>
    <h2 class="sec"><span>Score breakdown</span></h2>
    <div class="card">${Object.entries(B.parts).map(([k, n]) => `<div class="list-item"><div class="grow">${esc(k)}</div><b>${n}</b></div>`).join("")}</div>
    <h2 class="sec"><span>What ${esc(D.mindy.name)} knows · ${D.facts.length}</span><button data-b="tree">FAMILY TREE →</button></h2>
    <div class="card">${D.facts.length ? D.facts.map(f => `<div class="list-item"><div class="grow"><div class="small muted">${esc(f.region)}</div>${esc(f.key.replace(/_/g, " "))}: <b>${esc(f.value)}</b></div>
      <button class="btn sm ghost" data-delf="${f.id}" aria-label="Delete">✕</button></div>`).join("") : `<div class="small muted">Nothing yet. Answer a question above.</div>`}
      <div class="small muted" style="margin-top:10px">You can delete anything. It's your mind.</div></div>
    <h2 class="sec"><span>Documents</span><button data-b="doc">+ ADD</button></h2>
    <div class="card">${D.docs.length ? D.docs.map(d => `<div class="list-item"><div class="grow"><b>${esc(d.name)}</b></div><span class="small muted">${esc(d.expires)}</span></div>`).join("") : `<div class="small muted">Passport, insurance, licence… Mindy reminds you before they expire.</div>`}</div>
    <h2 class="sec"><span>Your Mindy</span></h2>
    <div class="card" id="mymindy"></div>`;
  brainCtl = mountBrain(v.querySelector("#brain"), D, reg => showQ(reg));
  V.mindmap(v.querySelector("#mapbox"), { focus: arg || null, onChange: m => { const h = v.querySelector("h1.big"); if (h && m.score != null) h.firstChild.nodeValue = m.score; } });
  renderMindy(v.querySelector("#mymindy"), D.mindy);
  const qcard = v.querySelector("#qcard");
  async function showQ(reg) {
    v.querySelectorAll("[data-reg]").forEach(b => b.classList.toggle("on", b.dataset.reg === reg));
    brainCtl.select(reg);
    const r = await api("/mind/question" + (reg ? "?region=" + reg : ""));
    renderQ(r.next, reg);
  }
  function renderQ(q, reg) {
    if (!q) { qcard.innerHTML = `<div class="card"><b>✨ ${reg ? "This area is full." : "All caught up."}</b><div class="small muted">Tap another part of your brain.</div></div>`; return; }
    qcard.innerHTML = `<div class="sticker"><div class="eyebrow">${esc(q.region)}</div><h3 style="margin:6px 0 12px">${esc(q.q)}</h3>
      ${q.opts.length ? `<div class="row" style="flex-wrap:wrap;gap:8px">${q.opts.map(o => `<button class="btn sm dark" data-ans="${esc(o.value)}">${esc(o.label)}</button>`).join("")}</div>`
        : `<form class="inline-form" data-free><input class="field" name="v" placeholder="Type here" autocomplete="off"><button class="btn sm dark">Save</button></form>`}
      <button class="link small" data-ans="skip" style="margin-top:10px">Skip</button></div>`;
    const send = async val => {
      try {
        const r = await api("/mind/answer", { body: { key: q.key, value: val } });
        toast(r.reply.replace(/\*/g, ""));
        if (r.rename) toast(`Call me ${r.rename}?`, "", { label: "Yes!", run: () => api("/mindy", { method: "PATCH", body: { name: r.rename } }).then(() => V.brain(v)) }, 9000);
        if (r.again) return;
        v.querySelector("h1.big").firstChild.nodeValue = r.brain.score;
        const D2 = await api("/mind"); brainCtl.update(D2.regions);
        v.querySelectorAll("[data-reg]").forEach(b => { const x = D2.regions.find(z => z.id === b.dataset.reg); b.querySelector("span").textContent = Math.round(x.fill * 100) + "%"; });
        renderQ(r.next, reg);
      } catch (e) { toast(e.message); }
    };
    qcard.querySelectorAll("[data-ans]").forEach(b => b.onclick = () => send(b.dataset.ans));
    const f = qcard.querySelector("[data-free]"); if (f) f.onsubmit = e => { e.preventDefault(); const val = f.v.value.trim(); if (val) send(val); };
  }
  renderQ(D.next, null);
  v.querySelectorAll("[data-reg]").forEach(b => b.onclick = () => showQ(b.dataset.reg));
  v.querySelectorAll("[data-hab]").forEach(b => b.onclick = async () => { const r = await api(`/habits/${b.dataset.hab}/done`, { body: {} }); toast(`🔥 ${r.streak}-day streak`); V.brain(v); });
  v.querySelectorAll("[data-delf]").forEach(b => b.onclick = async () => { await api(`/mind/fact/${b.dataset.delf}`, { method: "DELETE" }); b.closest(".list-item").remove(); });
  v.querySelector("[data-b=tree]").onclick = () => location.hash = "tree";
  v.querySelector("[data-b=share]").onclick = () => shareCard();
  v.querySelector("[data-b=habit]").onclick = () => { const t = prompt("A tiny daily habit (e.g. Walk 20 minutes)"); if (t) api("/habits", { body: { title: t } }).then(() => V.brain(v)); };
  v.querySelector("[data-b=doc]").onclick = () => { const n = prompt("Which document? (passport, insurance…)"); if (!n) return; const d = prompt("When does it expire? (e.g. 3 May 2027)");
    if (d) api("/docs", { body: { name: n, expires: d } }).then(r => { toast(`Saved. ${r.reminders.length} reminders set.`); V.brain(v); }).catch(e => toast(e.message)); };
};

async function shareCard() {
  const { api, S, toast } = M();
  const me = await api("/me/key").catch(() => null);
  const key = me && me.share_key;
  const url = key ? `${location.origin}/s/${key}` : location.origin;
  try {
    if (key && navigator.canShare) {
      const blob = await (await fetch(`/card/${key}.png`)).blob();
      const file = new File([blob], "my-brain-score.png", { type: "image/png" });
      if (navigator.canShare({ files: [file] })) return navigator.share({ files: [file], text: "My brain score 🧠 " + url });
    }
    if (navigator.share) return navigator.share({ text: "My brain score 🧠", url });
    await navigator.clipboard.writeText(url); toast("Link copied");
  } catch (_) {}
}

function renderMindy(el, m) {
  const { api, esc, toast } = M();
  const hues = [150, 175, 210, 270, 330, 0, 30, 50];
  el.innerHTML = `<label class="small muted">Name</label><form class="inline-form" data-n><input class="field" name="n" value="${esc(m.name)}" maxlength="18"><button class="btn sm">Save</button></form>
    <div class="small muted" style="margin-top:12px">Colour</div><div class="row" style="gap:8px;margin-top:6px">${hues.map(h =>
      `<button data-h="${h}" aria-label="colour" style="width:30px;height:30px;border-radius:50%;background:hsl(${h} 70% 55%);box-shadow:${m.hue === h ? "0 0 0 3px #000,0 0 0 5px #F5F3EE" : "none"}"></button>`).join("")}</div>
    <div class="small muted" style="margin-top:12px">Personality</div><div class="chips" style="margin:6px 0 0">${["sweet", "cheeky", "calm"].map(p =>
      `<button class="chip ${m.persona === p ? "on" : ""}" data-p="${p}">${{ sweet: "🥰 Sweet", cheeky: "😏 Cheeky", calm: "🌿 Calm" }[p]}</button>`).join("")}</div>
    <div class="small muted" style="margin-top:12px">Language</div><select class="field" data-l>${[["en", "English"], ["hi", "हिंदी"], ["hinglish", "Hinglish"], ["gu", "ગુજરાતી"],
      ["mr", "मराठी"], ["ta", "தமிழ்"], ["te", "తెలుగు"], ["bn", "বাংলা"], ["ur", "اردو"], ["es", "Español"], ["pt", "Português"], ["fr", "Français"], ["de", "Deutsch"],
      ["ar", "العربية"], ["sw", "Kiswahili"], ["id", "Bahasa Indonesia"], ["tl", "Filipino"], ["yo", "Yorùbá"]].map(([c, n]) => `<option value="${c}" ${m.lang === c ? "selected" : ""}>${n}</option>`).join("")}</select>`;
  const save = body => api("/mindy", { method: "PATCH", body }).then(r => { toast("Saved 💚"); renderMindy(el, r); });
  el.querySelector("[data-n]").onsubmit = e => { e.preventDefault(); save({ name: e.target.n.value }); };
  el.querySelectorAll("[data-h]").forEach(b => b.onclick = () => save({ hue: Number(b.dataset.h) }));
  el.querySelectorAll("[data-p]").forEach(b => b.onclick = () => save({ persona: b.dataset.p }));
  el.querySelector("[data-l]").onchange = e => save({ lang: e.target.value });
}

// ---------------------------------------------------------------- Family tree
V.tree = async function (v) {
  const { esc, api, toast } = M();
  const D = await api("/mind");
  const people = D.people;
  const groups = { up: ["grandparent", "mother", "father", "parent"], mid: ["partner", "sibling", "friend", "other", ""], down: ["child"] };
  const row = (list, label) => list.length ? `<div class="eyebrow" style="text-align:center;margin:18px 0 8px">${label}</div><div class="row" style="justify-content:center;flex-wrap:wrap;gap:10px">${list.map(p =>
    `<button class="card" data-p="${p.id}" style="margin:0;padding:12px 14px;text-align:center;min-width:104px"><div style="font-size:26px">${({ mother: "👩", father: "👨", grandparent: "👵", partner: "💞", child: "🧒", sibling: "🧑", friend: "🫶" })[p.relation] || "🙂"}</div>
      <b>${esc(p.name)}</b><div class="small muted">${p.birthday ? "🎂 " + esc(p.birthday.split("-").reverse().join("/")) : "+ birthday"}</div></button>`).join("")}</div>` : "";
  const by = g => people.filter(p => groups[g].includes(p.relation || ""));
  v.innerHTML = `<header class="top"><div><div class="eyebrow g">Family tree</div><h1 class="big">${people.length} <i>people</i></h1>
      <div class="small muted">Everyone you add gets birthday reminders and gift ideas.</div></div><a class="btn sm ghost" href="#brain">Brain</a></header>
    ${row(by("up"), "Elders")}
    <div style="text-align:center;margin:18px 0"><span class="btn g">You</span></div>
    ${row(by("mid"), "Your circle")}${row(by("down"), "Little ones")}
    ${people.length ? "" : `<div class="empty">Start with the person whose birthday you'd hate to forget.</div>`}
    <h2 class="sec"><span>Add someone</span></h2>
    <form class="card" data-add style="display:grid;gap:10px"><input class="field" name="name" placeholder="Name" required>
      <select class="field" name="relation">${[["mother", "Mother"], ["father", "Father"], ["partner", "Partner"], ["child", "Child"], ["sibling", "Brother / Sister"],
        ["grandparent", "Grandparent"], ["friend", "Friend"], ["other", "Someone else"]].map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select>
      <input class="field" name="birthday" placeholder="Birthday, e.g. 4 April (optional)"><input class="field" name="gift_ideas" placeholder="What they love (for gift ideas)">
      <button class="btn g block">Add to my tree</button></form>`;
  v.querySelector("[data-add]").onsubmit = async e => { e.preventDefault(); const f = e.target;
    try { const r = await api("/tree", { body: { name: f.name.value, relation: f.relation.value, birthday: f.birthday.value, gift_ideas: f.gift_ideas.value } });
      toast(`🌳 ${f.name.value} added · brain score ${r.brain.score}`); V.tree(v); } catch (err) { toast(err.message); } };
  v.querySelectorAll("[data-p]").forEach(b => b.onclick = () => { const p = people.find(x => x.id == b.dataset.p);
    if (confirm(`Remove ${p.name} from your tree?`)) api(`/tree/${p.id}`, { method: "DELETE" }).then(() => V.tree(v)); });
};

// ---------------------------------------------------------------- Clipboard
V.clip = async function (v) {
  const { esc, api, toast } = M();
  const me = await api("/me/key").catch(() => ({}));
  const rows = await api("/clipboard").catch(() => []);
  const url = me.button_key ? `${location.origin}/clip/${me.button_key}` : "";
  v.innerHTML = `<header class="top"><div><div class="eyebrow g">Clipboard</div><h1 class="big">Everything <i>you copied</i></h1></div></header>
    <div class="card">${rows.length ? rows.map(r => `<div class="list-item"><div class="grow" style="word-break:break-word">${esc(r.text.slice(0, 300))}</div>
      <button class="btn sm" data-copy="${r.id}">Copy</button></div>`).join("") : `<div class="small muted">Nothing yet. Set up the shortcut below, copy something, double-tap the back of your iPhone.</div>`}</div>
    <h2 class="sec"><span>iPhone: save with a double-tap</span></h2>
    <div class="card small" style="line-height:1.6">1. Open <b>Shortcuts</b> → + → add <b>Get Clipboard</b><br>2. Add <b>Get Contents of URL</b>, URL:<br><code style="word-break:break-all">${esc(url)}</code><br>
      Method <b>POST</b>, Request Body <b>File</b> → Clipboard<br>3. Add <b>Show Notification</b>: "Saved to Mindy"<br>4. Name it <b>Save to Mindy</b><br>
      5. Settings → Accessibility → Touch → <b>Back Tap</b> → Double Tap → Save to Mindy<br>
      <button class="btn sm" data-u style="margin-top:10px">Copy my link</button><div class="muted" style="margin-top:8px">Keep this link private: anyone with it can add to your clipboard.</div></div>`;
  v.querySelectorAll("[data-copy]").forEach(b => b.onclick = () => { navigator.clipboard.writeText(rows.find(r => r.id == b.dataset.copy).text).then(() => toast("Copied ✓")); });
  v.querySelector("[data-u]").onclick = () => navigator.clipboard.writeText(url).then(() => toast("Link copied"));
};

// ---------------------------------------------------------------- Money
V.money = async function (v) {
  const { esc, api } = M();
  const D = await api("/money").catch(() => ({ month: null }));
  const max = D.cats && D.cats.length ? D.cats[0].total : 1;
  v.innerHTML = `<header class="top"><div><div class="eyebrow g">Money</div><h1 class="big">${D.month ? esc(D.cur + Math.round(D.total).toLocaleString()) : "Your <i>spend</i>"}</h1>
      <div class="small muted">${D.month ? esc(D.month) + " · money out" : "Forward a bank statement to Mindy on WhatsApp"}</div></div></header>
    ${D.month ? `<div class="card">${D.cats.map(c => `<div style="margin:10px 0"><div class="row" style="justify-content:space-between"><span>${esc(c.category)}</span>
      <b>${esc(D.cur + Math.round(c.total).toLocaleString())}${c.change != null && Math.abs(c.change) >= 10 ? ` <span class="small ${c.change > 0 ? "" : "muted"}" style="color:${c.change > 0 ? "var(--red)" : "var(--green)"}">${c.change > 0 ? "+" : ""}${c.change}%</span>` : ""}</b></div>
      <div style="height:8px;border-radius:8px;background:var(--panel2);margin-top:6px"><div style="height:8px;border-radius:8px;width:${Math.max(3, c.total / max * 100)}%;background:var(--green)"></div></div></div>`).join("")}</div>
      <h2 class="sec"><span>Top places</span></h2><div class="card">${(D.top || []).map(t => `<div class="list-item"><div class="grow">${esc(t.merchant || "—")}</div><span class="small muted">${t.n}×</span><b>${esc(D.cur + Math.round(t.total).toLocaleString())}</b></div>`).join("")}</div>`
      : `<div class="sticker"><h3>Send your statement to Mindy</h3><p>Export a CSV or PDF from your bank app and send it to Mindy on WhatsApp with the word <b>statement</b>. Mindy keeps only dates, amounts and shop names, and deletes the file.</p></div>`}`;
};

// ---------------------------------------------------------------- People: your Mindy talks to their Mindy
V.people = async function (v) {
  const { esc, api, toast } = M();
  let D; try { D = await api("/m2m"); } catch (e) { v.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const KIND = { money: "💸", ask: "💬", safe: "💚", decline: "💌", poll: "🗳️" };
  v.innerHTML = `<header class="top"><div><div class="eyebrow g">Mindy to Mindy</div><h1 class="big">Your <i>people</i></h1>
      <div class="small muted">Your Mindy talks to their Mindy, so you don't have to.</div></div><button class="btn sm g" data-b="link">+ Link</button></header>
    ${D.inbox.length ? `<h2 class="sec"><span>Waiting for you · ${D.inbox.length}</span></h2>` + D.inbox.map(x => `<div class="sticker" data-in="${x.id}"><div class="eyebrow">${esc(x.from)}'s Mindy asks</div>
      <h3 style="margin:6px 0 12px">${KIND[x.kind]} ${esc(x.text || "Are you OK?")}</h3><div class="row" style="flex-wrap:wrap;gap:8px">${x.taps.map(t => `<button class="btn sm dark" data-ans="${t.value}">${esc(t.label)}</button>`).join("")}</div></div>`).join("") : ""}
    <h2 class="sec"><span>Linked · ${D.people.length}</span></h2>
    ${D.people.length ? D.people.map(p => `<div class="card" data-p="${p.id}"><b style="font-size:18px">${esc(p.name || "Friend")}</b>
      <div class="row" style="flex-wrap:wrap;gap:8px;margin-top:10px"><button class="btn sm" data-k="money">💸 Ask for money</button><button class="btn sm" data-k="ask">💬 Ask something</button>
      <button class="btn sm" data-k="safe">💚 Check in</button><button class="btn sm ghost" data-k="decline">💌 Can't make it</button></div></div>`).join("")
      : `<div class="sticker"><h3>Link your first person</h3><p>Send them your link. The moment they tap it, your Mindys can talk: money, plans, check-ins, all in taps.</p><button class="btn dark" data-b="link" style="margin-top:12px">Share my link</button></div>`}
    ${D.people.length > 1 ? `<button class="btn block g" data-b="group" style="margin-top:14px">🗳️ Ask everyone something</button>` : ""}
    ${(D.polls || []).length ? `<h2 class="sec"><span>Your group asks</span></h2>` + D.polls.map(g => `<div class="card"><b>${esc(g.question)}</b>
      <div class="small" style="white-space:pre-line;margin-top:8px">${esc(g.text)}</div></div>`).join("") : ""}
    ${D.sent.length ? `<h2 class="sec"><span>Asked for you</span></h2><div class="card">` + D.sent.map(x => `<div class="list-item"><div class="grow">${KIND[x.kind]} <b>${esc(x.to)}</b> <span class="muted">${esc(x.text || "check-in")}</span></div>
      <span class="small ${x.answer ? "" : "muted"}">${x.answer ? esc(x.answer) : "waiting…"}</span></div>`).join("") + `</div>` : ""}
    ${D.handled.rows.length ? `<h2 class="sec"><span>Handled for you this week</span></h2><div class="card">` + D.handled.rows.map(r => `<div class="list-item"><div class="grow">${r.icon} ${esc(r.label)}</div><b>${r.n}</b></div>`).join("") + `</div>` : ""}`;
  v.querySelectorAll("[data-b=link]").forEach(b => b.onclick = async () => {
    const text = "Get your own Mindy and link with me: " + D.link;
    try { if (navigator.share) await navigator.share({ text }); else { await navigator.clipboard.writeText(text); toast("Link copied. Send it to anyone."); } } catch (_) {}
  });
  const gb = v.querySelector("[data-b=group]");
  if (gb) gb.onclick = async () => {
    const q = prompt("What should I ask everyone? (e.g. Dinner this week?)"); if (!q) return;
    const o = prompt("Options, separated by commas (leave empty for Yes / No)", "Friday, Saturday, Sunday");
    try { const r = await api("/m2m/group", { body: { question: q, options: (o || "").split(",").map(x => x.trim()).filter(Boolean) } });
      toast(r.reply.replace(/\*/g, "").split("\n")[0]); V.people(v); } catch (e) { toast(e.message); }
  };
  v.querySelectorAll("[data-in]").forEach(card => card.querySelectorAll("[data-ans]").forEach(b => b.onclick = async () => {
    try { const r = await api(`/m2m/${card.dataset.in}/answer`, { body: { answer: b.dataset.ans } }); toast(r.reply); V.people(v); } catch (e) { toast(e.message); }
  }));
  v.querySelectorAll("[data-p]").forEach(card => card.querySelectorAll("[data-k]").forEach(b => b.onclick = async () => {
    const kind = b.dataset.k, body = { to: Number(card.dataset.p), kind };
    if (kind === "money") { const a = prompt("How much?"); if (!a) return; body.amount = a.replace(/[^\d.]/g, ""); body.text = prompt("What for? (optional)") || ""; }
    if (kind === "ask") { body.text = prompt("What should I ask them?"); if (!body.text) return; }
    if (kind === "decline") { body.text = prompt("Can't make it to what? (optional)") || ""; }
    try { const r = await api("/m2m/send", { body }); toast(r.reply.replace(/\*/g, "")); V.people(v); } catch (e) { toast(e.message); }
  }));
};

// ---------------------------------------------------------------- Now opens on your mind
const prevNow = V.nowCards;
V.nowCards = function (H) {
  const html = prevNow ? prevNow(H) : "";
  setTimeout(async () => {
    const el = document.getElementById("braincard"); if (!el) return;
    try {
      const b = await M().api("/brain");
      el.innerHTML = `<h2 class="sec"><span>Your mind · ${b.score} / 1000</span><button onclick="location.hash='brain'">OPEN →</button></h2><div id="nowmap"></div>`;
      V.mindmap(el.querySelector("#nowmap"));
    } catch (_) { el.remove(); }
  }, 0);
  return `<div id="braincard"></div>` + html;
};
})();
