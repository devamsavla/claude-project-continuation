/* Mindy web app. Plain JavaScript, no build step. Talks to the same backend as Mindy on WhatsApp and Instagram:
   REST under /api for data, one WebSocket at /ws for everything live (presence, chat, games, watch parties, reminders). */
(() => {
"use strict";
const API = (window.MINDY_API || "").replace(/\/$/, "");
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (_) {} }
};
const S = { token: store.get("mindy_token"), me: null, cfg: {}, friends: [], online: new Set(), chats: [], unread: 0,
  games: {}, parties: {}, room: null, ws: null, wsTries: 0, mindTab: store.get("mindy_mindtab") || "remind", login: { step: "phone" },
  invite: new URLSearchParams(location.search).get("invite"), chatMsgs: [], chatId: null, savedQ: "", savedColl: "" };
const HUES = ["#9FF7FF", "#FFB8E8", "#B8FFE0", "#C7B8FF", "#FFE29A", "#FFC59A"];
const hue = id => HUES[Math.abs(Number(id) || 0) % HUES.length];
const initial = n => esc((n || "?").trim().charAt(0).toUpperCase());
const STATUSES = [["free", "🟢 Free"], ["study", "📚 Studying"], ["game", "🎮 Gaming"], ["match", "🏏 At the match"], ["busy", "⛔ Busy"], ["ghost", "👻 Ghost"]];
const STATUS_LABEL = { free: "Free now", study: "Studying", game: "Gaming", match: "At the match", busy: "Busy", away: "Away", ghost: "Ghost mode" };
const SERVICES = { Netflix: "https://www.netflix.com", "Prime Video": "https://www.primevideo.com", "JioHotstar": "https://www.hotstar.com", "Disney+": "https://www.disneyplus.com", "Apple TV": "https://tv.apple.com", "Other": "" };
const mindy = (mood, w = 120) => `<div style="width:${w}px">${(window.MINDY || {})[mood] || ""}</div>`;
if (S.invite) store.set("mindy_invite", S.invite);

// ------------------------------------------------------------------ helpers
async function api(path, opts = {}) {
  const r = await fetch(API + "/api" + path, {
    method: opts.method || (opts.body !== undefined ? "POST" : "GET"),
    headers: Object.assign({ "Content-Type": "application/json" }, S.token ? { Authorization: "Bearer " + S.token } : {}),
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined
  });
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && S.token && !path.startsWith("/auth")) { signOutLocal(); throw new Error("Please sign in again."); }
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Something went wrong. Try again.");
  return data;
}
function toast(title, body = "", action = null, ms = 5000) {
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `<div class="grow"><b>${esc(title)}</b>${body ? `<span class="small">${esc(body)}</span>` : ""}</div>${action ? `<button class="btn">${esc(action.label)}</button>` : ""}`;
  if (action) el.querySelector("button").onclick = () => { el.remove(); action.run(); };
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), action ? Math.max(ms, 9000) : ms);
}
const fail = e => toast("Hmm.", e.message || String(e));
function tz() { return (S.me && S.me.tz) || Intl.DateTimeFormat().resolvedOptions().timeZone; }
function fmtWhen(iso) {
  if (!iso) return "No time yet";
  const d = new Date(iso), now = new Date();
  const day = x => new Intl.DateTimeFormat("en-GB", { timeZone: tz(), year: "numeric", month: "2-digit", day: "2-digit" }).format(x);
  const time = new Intl.DateTimeFormat("en-GB", { timeZone: tz(), hour: "2-digit", minute: "2-digit" }).format(d);
  if (day(d) === day(now)) return "Today " + time;
  if (day(d) === day(new Date(now.getTime() + 864e5))) return "Tomorrow " + time;
  return new Intl.DateTimeFormat("en-GB", { timeZone: tz(), weekday: "short", day: "numeric", month: "short" }).format(d) + ", " + time;
}
function ago(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "now"; if (s < 3600) return Math.floor(s / 60) + "m"; if (s < 86400) return Math.floor(s / 3600) + "h";
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" }).format(new Date(iso));
}
function avatar(u, cls = "", dot = false) {
  return `<span class="avatar ${cls}" style="background:${hue(u.id)}">${initial(u.name)}${dot ? '<i class="dot"></i>' : ""}</span>`;
}
function nameOf(id) { if (String(id) === "0") return "Mindy"; const f = S.friends.find(x => x.id == id); return f ? f.name : (S.me && S.me.id == id ? "You" : "Friend"); }
async function share(text, url) {
  if (navigator.share) { try { await navigator.share({ title: "Mindy", text, url }); return; } catch (_) { return; } }
  try { await navigator.clipboard.writeText(url); toast("Link copied", "Paste it in WhatsApp, Instagram or anywhere."); }
  catch (_) { prompt("Copy this link", url); }
}

// ------------------------------------------------------------------ start
async function boot() {
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
  try { S.cfg = await api("/config"); } catch (_) { S.cfg = {}; }
  if (!S.token) return renderLogin();
  try {
    S.me = await api("/me");
  } catch (e) { return renderLogin(); }
  if (!S.me.name) { S.login = { step: "name" }; return renderLogin(); }
  const inv = store.get("mindy_invite");
  if (inv) {
    store.set("mindy_invite", null);
    try { await api("/friends/accept", { body: { code: inv } }); toast("You're friends now 🎉", "Say hi in Chats."); } catch (_) {}
    history.replaceState(null, "", location.pathname + location.hash);
  }
  connect();
  shell();
}
async function enter() {
  S.login = { step: "phone" };
  const inv = store.get("mindy_invite");
  if (inv) {
    store.set("mindy_invite", null); S.invite = null;
    try { await api("/friends/accept", { body: { code: inv } }); toast("You're friends now 🎉", "Your friend's invite worked. Say hi in Chats."); } catch (_) {}
  }
  history.replaceState(null, "", location.pathname + "#now");
  connect(); shell();
}
function signOutLocal() {
  S.token = null; S.me = null; store.set("mindy_token", null);
  if (S.ws) { S.ws.onclose = null; S.ws.close(); S.ws = null; }
  renderLogin();
}

// ------------------------------------------------------------------ sign in with WhatsApp
function renderLogin() {
  const L = S.login, wa = S.cfg.wa_number || "";
  document.body.classList.remove("in");
  $("#root").innerHTML = `<main class="login">
    ${mindy("wink", 120)}
    <h1>${L.step === "name" ? "Hey <i>there.</i>" : "Sign in with <i>WhatsApp.</i>"}</h1>
    <p class="muted">No password, no new account. Mindy sends a code to your WhatsApp, and everything you've already sent Mindy is waiting for you.${S.invite ? " <b style='color:var(--cream)'>A friend invited you.</b>" : ""}</p>
    ${L.step === "name" ? `
      <form data-form="name" style="margin-top:18px">
        <label class="lbl" for="nmi">You're in. What should friends call you?</label>
        <input class="field" id="nmi" name="name" maxlength="40" autocomplete="given-name" placeholder="Your first name" required>
        <button class="btn g block" style="margin-top:12px">Let's go</button>
      </form>` : L.step === "phone" ? `
      <form data-form="start" style="margin-top:18px">
        <label class="lbl" for="phone">Your WhatsApp number</label>
        <input class="field" id="phone" name="phone" type="tel" inputmode="tel" autocomplete="tel" placeholder="+91 98200 00000" value="${esc(L.phone || "")}" required>
        <button class="btn g block" style="margin-top:12px">Send my code</button>
      </form>
      ${S.cfg.google_client_id ? `<div class="or">or</div><div id="gbtn" style="display:flex;justify-content:center;min-height:44px"></div>` : ""}
      <div class="or">or</div>
      <div class="wa-card">
        <b>Already chatting with Mindy?</b>
        <p class="small muted" style="margin:6px 0 12px">Send <b style="color:var(--cream)">LOGIN</b> to Mindy on WhatsApp and you'll get a code back.</p>
        <div class="row"><a class="btn sm g" href="https://wa.me/${esc(wa)}?text=LOGIN" target="_blank" rel="noopener">Open WhatsApp</a>
        <button class="btn sm ghost" data-act="havecode">I have a code</button></div>
      </div>` : `
      <form data-form="verify" style="margin-top:18px">
        <label class="lbl" for="code">${L.phone ? `Code sent to ${esc(L.phone)} on WhatsApp` : "The 6-digit code from Mindy"}</label>
        <input class="field code" id="code" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" placeholder="••••••" required>
        <button class="btn g block" style="margin-top:12px">Sign in</button>
        ${L.dev ? `<p class="dev">Test mode (WhatsApp not connected yet): your code is ${esc(L.dev)}</p>` : ""}
        <p class="small muted" style="margin-top:14px">No message? Check the number, or send LOGIN to Mindy on WhatsApp. <button type="button" class="link" data-act="back-phone">Change number</button></p>
      </form>`}
    <p class="small muted" style="margin-top:26px">By signing in you agree to the <a href="https://whatsonyourmind.online/terms.html">terms</a> and <a href="https://whatsonyourmind.online/privacy.html">privacy policy</a>.</p>
  </main>`;
  const f = $("#phone") || $("#code") || $("#nmi"); if (f) f.focus();
  if ($("#gbtn") && window.MPV) window.MPV.google($("#gbtn"));
}

// ------------------------------------------------------------------ shell and tabs
function shell() {
  document.body.classList.add("in");
  $("#root").innerHTML = `<div class="app" id="view"></div>
    <nav class="tabbar" aria-label="Main">
      <button data-tab="now">NOW</button>
      <button data-tab="chats">CHATS<span class="badge" id="badge" hidden></span></button>
      <button data-act="think" aria-label="Tell Mindy what's on your mind"><span class="think"><span class="eyes"><i></i><i></i></span><span class="od"></span></span></button>
      <button data-tab="plans">PLANS</button>
      <button data-tab="mind">MIND</button>
    </nav><div id="overlay"></div>`;
  route();
  refreshChats();
}
window.addEventListener("hashchange", () => { if (S.me) route(); });
function route() {
  const h = location.hash.slice(1) || "now";
  const [tab, arg] = h.split("/");
  document.querySelectorAll(".tabbar [data-tab]").forEach(b => b.classList.toggle("on", b.dataset.tab === tab || (tab === "chat" && b.dataset.tab === "chats")));
  S.chatId = tab === "chat" ? Number(arg) : null;
  const v = $("#view"); if (!v) return;
  window.scrollTo(0, 0);
  const P = window.MPV || {};
  if (tab === "now" && S.me && S.me.simple && P.simple) return P.simple(v);
  ({ now: viewNow, chats: viewChats, chat: viewChat, plans: viewPlans, mind: viewMind, me: viewMe, care: P.care, khata: P.khata, tools: P.tools }[tab] || (["brain", "tree", "clip", "money", "people"].includes(tab) && P[tab]) || viewNow)(v, arg);
}
function setBadge() { const b = $("#badge"); if (b) { b.hidden = !S.unread; b.textContent = S.unread; } }
async function refreshChats() { try { S.chats = await api("/chats"); S.unread = S.chats.reduce((a, c) => a + c.unread, 0); setBadge(); } catch (_) {} }

// ------------------------------------------------------------------ NOW
async function viewNow(v) {
  v.innerHTML = `<div class="empty">${mindy("think", 90)}</div>`;
  let H;
  try { H = await api("/home"); } catch (e) { v.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  H.friends.forEach(f => { if (S.online.has(f.id) && f.status !== "away") f.online = true; });
  S.friends = H.friends; S.me = Object.assign(S.me || {}, H.me);
  const date = new Intl.DateTimeFormat("en-GB", { timeZone: tz(), weekday: "long", day: "numeric", month: "short" }).format(new Date());
  const hour = Number(new Intl.DateTimeFormat("en-GB", { timeZone: tz(), hour: "2-digit", hour12: false }).format(new Date()));
  const hello = hour < 5 ? "Up late," : hour < 12 ? "Morning," : hour < 17 ? "Hey" : "Evening,";
  const free = H.friends.filter(f => f.online && f.status === "free");
  v.innerHTML = `
    <header class="top"><div><div class="eyebrow g">${esc(date)}</div><h1 class="big">${hello} <i>${esc((S.me.name || "you").split(" ")[0])}</i></h1></div>
      <a href="#me" aria-label="Your profile">${avatar(S.me, "ring")}</a></header>
    <div class="chips" role="group" aria-label="Your status">${STATUSES.map(([k, l]) => `<button class="chip ${S.me.status === k ? "on" : ""}" data-act="status" data-v="${k}">${l}</button>`).join("")}</div>
    <h2 class="sec"><span>${H.friends.length ? `Your people · ${free.length} free` : "Your people"}</span><button data-act="invite">+ INVITE</button></h2>
    ${H.friends.length ? `<div class="people" id="people">${peopleRow()}</div>` : `
      <div class="sticker"><div class="eyebrow">Start here</div><h3>Bring your people.</h3><p>Send your invite link on WhatsApp. When they tap it, you're friends here: live status, chats, plans and games.</p>
      <div class="row" style="margin-top:12px"><button class="btn dark" data-act="invite">Share my invite link</button></div></div>`}
    ${!H.mood ? `<div class="sticker" style="margin-top:18px"><div class="eyebrow">Daily check-in · 5 seconds</div><h3>How's your head today?</h3>
      <div class="faces">${["😫", "😕", "😐", "🙂", "🤩"].map((f, i) => `<button data-act="mood" data-v="${i + 1}" aria-label="mood ${i + 1}">${f}</button>`).join("")}</div></div>` : ""}
    ${window.MPV ? window.MPV.nowCards(H) : ""}
    ${H.plans.length ? `<h2 class="sec"><span>Plans</span><button onclick="location.hash='plans'">ALL →</button></h2>${H.plans.map(planCard).join("")}` : ""}
    <h2 class="sec"><span>Coming up</span><button onclick="location.hash='mind'">ALL →</button></h2>
    <div class="card">${H.reminders.length ? H.reminders.map(remRow).join("") : `<p class="muted small" style="margin:0">Nothing yet. Tap the bubble and say “remind me to call mum Sunday 7pm”, or send it to Mindy on WhatsApp.</p>`}</div>
    ${H.items.length ? `<h2 class="sec"><span>Just saved</span><button data-act="mindtab" data-v="saved">ALL →</button></h2><div class="card">${H.items.map(itemRow).join("")}</div>` : ""}
    <div class="card" style="margin-top:22px"><div class="row"><div class="grow"><b>Mindy on WhatsApp</b><div class="small muted">Forward reels, tickets and notes to Mindy. They land here.</div></div>
      <a class="btn sm g" href="https://wa.me/${esc(S.cfg.wa_number || "")}?text=Hi%20Mindy!" target="_blank" rel="noopener">Open</a></div></div>`;
}
function peopleRow() {
  return S.friends.map(f => `<a class="person" href="#" data-act="dm" data-id="${f.id}" style="text-decoration:none">
      ${avatar(f, f.online ? "ring" : "", f.online)}<b>${esc(f.name || "Friend")}</b><small>${f.online ? esc(STATUS_LABEL[f.status] || "Online") : "Offline"}</small></a>`).join("");
}
function remRow(r) {
  const late = r.status !== "pending";
  return `<div class="list-item" data-rem="${r.id}"><button class="check" data-act="rem-done" data-id="${r.id}" aria-label="Mark done"></button>
    <div class="grow"><div class="t">${esc(r.text)}</div><div class="s">${late ? "Sent " : ""}${esc(fmtWhen(r.due_at))}${r.repeat ? " · repeats " + esc(r.repeat) : ""}</div></div>
    <button class="btn sm ghost" data-act="rem-snooze" data-id="${r.id}">+1h</button></div>`;
}
function itemRow(i) {
  const url = i.url ? `<a class="small link" href="${esc(i.url)}" target="_blank" rel="noopener">Open</a>` : "";
  return `<div class="list-item"><div class="grow"><div class="t ellipsis">${esc(i.title || i.text)}</div>
    <div class="s"><span class="pill">${esc(i.collection || "Notes")}</span> · ${esc(ago(i.created_at))}</div></div>${url}</div>`;
}
function planCard(p) {
  const mine = p.rsvp;
  return `<div class="card"><div class="row between"><div class="grow"><div class="eyebrow g">${esc(fmtWhen(p.when_at))}</div>
    <div style="font-family:var(--serif);font-size:28px;line-height:1.05;margin-top:4px">${esc(p.title)}</div></div></div>
    <div class="row" style="margin-top:10px;flex-wrap:wrap;gap:6px">${p.people.map(x => `<span class="pill ${x.rsvp === "going" ? "g" : ""}">${esc(x.name || "Friend")} · ${esc(x.rsvp)}</span>`).join("")}</div>
    <div class="row" style="margin-top:12px;gap:8px">${["going", "maybe", "no"].map(v => `<button class="btn sm ${mine === v ? "" : "ghost"}" data-act="rsvp" data-id="${p.id}" data-v="${v}">${v === "going" ? "I'm in" : v === "maybe" ? "Maybe" : "Can't"}</button>`).join("")}</div></div>`;
}

// ------------------------------------------------------------------ CHATS
async function viewChats(v) {
  await refreshChats();
  try { S.friends = await api("/friends"); } catch (_) {}
  v.innerHTML = `<header class="top"><div><div class="eyebrow">Mindy is in every chat. Just say @mindy</div><h1 class="big">Chats</h1></div>
      <button class="btn sm" data-act="newchat">+ New</button></header>
    <div style="margin-top:18px">${S.chats.length ? S.chats.map(c => `<a class="list-item" href="#chat/${c.id}" style="text-decoration:none">
        ${c.is_group ? `<span class="avatar sm" style="background:var(--cream)">${initial(c.name)}</span>` : avatar(c.members.find(m => m.id !== S.me.id) || c, "sm", S.friends.some(f => f.online && c.members.some(m => m.id === f.id)))}
        <div class="grow"><div class="t ellipsis">${esc(c.name)}</div><div class="s ellipsis">${c.last ? esc((c.last.kind === "mindy" ? "Mindy: " : "") + c.last.body) : "Say hi 👋"}</div></div>
        ${c.unread ? `<span class="pill g">${c.unread}</span>` : c.last ? `<span class="small muted">${esc(ago(c.last.created_at))}</span>` : ""}</a>`).join("")
      : `<div class="empty">${mindy("happy", 110)}<p>No chats yet. ${S.friends.length ? "Start one with a friend." : "Invite a friend first, then chat here."}</p>
         <button class="btn" data-act="${S.friends.length ? "newchat" : "invite"}">${S.friends.length ? "New chat" : "Share my invite link"}</button></div>`}</div>`;
}
async function viewChat(v, id) {
  v.innerHTML = `<div class="empty">${mindy("think", 80)}</div>`;
  if (!S.chats.find(c => c.id == id)) await refreshChats();
  const c = S.chats.find(x => x.id == id);
  if (!c) { v.innerHTML = `<div class="empty">That chat isn't here. <a class="link" href="#chats">Back to chats</a></div>`; return; }
  try { S.chatMsgs = await api(`/chats/${id}/messages`); } catch (e) { return fail(e); }
  refreshChats();
  const others = c.members.filter(m => m.id !== S.me.id);
  v.innerHTML = `<header class="row" style="position:sticky;top:0;background:#000;padding:6px 0 12px;z-index:5;border-bottom:1px solid var(--line);margin:0 -16px 12px;padding-left:16px;padding-right:16px">
      <a class="icon-btn" href="#chats" aria-label="Back">←</a>
      <div class="grow"><b class="ellipsis" style="display:block">${esc(c.name)}</b><span class="small muted">${others.map(o => esc(o.name || "Friend")).join(", ")} + Mindy</span></div>
      <button class="icon-btn" data-act="game-sheet" data-with="${others.map(o => o.id).join(",")}" aria-label="Play a game">🏏</button>
      <button class="icon-btn" data-act="party-sheet" data-with="${others.map(o => o.id).join(",")}" aria-label="Start a watch party">🎬</button></header>
    <div class="thread" id="thread">${S.chatMsgs.map(msgHtml).join("") || `<p class="muted small" style="text-align:center">Say hi. Or try “@mindy plan dinner Saturday 8pm”.</p>`}</div>
    <form class="composer" data-form="send" style="flex-direction:column;gap:0">
      <div class="hints">${["@mindy plan dinner Saturday 8pm", "@mindy split ₹1200", "@mindy remind me Sunday 6pm to book tickets"].map(h => `<button type="button" data-act="hint" data-v="${esc(h)}">${esc(h)}</button>`).join("")}</div>
      <div class="row" style="gap:8px"><input class="field" name="body" placeholder="Message" autocomplete="off" aria-label="Message"><button class="btn g">Send</button></div>
    </form>`;
  scrollThread();
}
function msgHtml(m) {
  const mine = m.user_id === S.me.id, mindyMsg = m.kind === "mindy";
  return `<div class="msg ${mindyMsg ? "mindy" : mine ? "me" : "them"}">${!mine ? `<span class="who">${esc(mindyMsg ? "Mindy 🧠" : m.name || "Friend")}</span>` : ""}${esc(m.body)}</div>`;
}
function scrollThread() { requestAnimationFrame(() => window.scrollTo(0, document.body.scrollHeight)); }

// ------------------------------------------------------------------ PLANS: watch parties, games, plans
async function viewPlans(v) {
  let plans = [];
  try { [plans, S.friends] = await Promise.all([api("/plans"), api("/friends")]); } catch (e) { fail(e); }
  const live = [...Object.entries(S.games).filter(([, g]) => !g.state.over).map(([id, g]) => ({ id, kind: "game", label: g.game === "hand" ? "🏏 Hand cricket" : "🃏 Last Card", who: g.state.players.filter(p => p !== S.me.id).map(nameOf).join(", ") })),
    ...Object.entries(S.parties).map(([id, p]) => ({ id, kind: "party", label: "🎬 " + p.title, who: p.members.filter(m => m.id !== S.me.id).map(m => m.name).join(", ") || "Waiting for friends" }))];
  v.innerHTML = `<header><div class="eyebrow">Stop saying “we should”</div><h1 class="big">Plans</h1></header>
    ${live.length ? `<h2 class="sec"><span>Live now</span></h2>${live.map(l => `<button class="card row" style="width:100%" data-act="open-${l.kind}" data-id="${l.id}"><div class="grow"><b>${esc(l.label)}</b><div class="small muted">${esc(l.who)}</div></div><span class="pill g">REJOIN</span></button>`).join("")}` : ""}
    <div class="sticker" style="margin-top:18px"><div class="eyebrow">Watch party</div><h3>Watch together, apart.</h3>
      <p>YouTube plays in sync for everyone, with reactions and chat. Netflix, Prime and the rest: one shared countdown and the link, so you all press play together.</p>
      <div class="row" style="margin-top:12px"><button class="btn dark" data-act="party-sheet">Start a watch party</button></div></div>
    <h2 class="sec"><span>Play</span></h2>
    <div class="row" style="gap:12px;align-items:stretch">
      <button class="card grow" style="margin:0" data-act="game-sheet" data-game="hand"><div style="font-size:34px">🏏</div><b>Hand cricket</b><div class="small muted">1v1, odd-even. Friend or Mindy.</div></button>
      <button class="card grow" style="margin:0" data-act="game-sheet" data-game="lastcard"><div style="font-size:34px">🃏</div><b>Last Card</b><div class="small muted">2 to 4 players. Don't forget to call it.</div></button></div>
    <h2 class="sec"><span>Make a plan</span></h2>
    <form class="card" data-form="plan">
      <input class="field" name="title" placeholder="Dinner at Bombay Canteen" required aria-label="What">
      <input class="field" name="when" placeholder="Saturday 8pm" style="margin-top:8px" aria-label="When">
      ${S.friends.length ? `<div class="chips" style="margin-top:10px">${S.friends.map(f => `<label class="chip"><input type="checkbox" name="people" value="${f.id}" style="margin-right:6px">${esc(f.name || "Friend")}</label>`).join("")}</div>` : ""}
      <button class="btn g block" style="margin-top:12px">Send invites</button></form>
    <h2 class="sec"><span>Coming up</span></h2>
    ${plans.length ? plans.map(planCard).join("") : `<div class="empty">${mindy("party", 110)}<p>No plans yet. Make one above, or say “@mindy plan Friday 9pm” in any chat.</p></div>`}`;
}
function pickFriends(max, preset = []) {
  if (!S.friends.length) return `<p class="small muted">No friends here yet. <button type="button" class="link" data-act="invite">Invite someone</button> or play against Mindy.</p>`;
  return `<div class="chips" style="flex-wrap:wrap;margin:8px 0 0;padding:0">${S.friends.map(f => `<label class="chip"><input type="checkbox" name="with" value="${f.id}" ${preset.includes(String(f.id)) ? "checked" : ""} data-max="${max}" style="margin-right:6px">${esc(f.name || "Friend")}${f.online ? " 🟢" : ""}</label>`).join("")}</div>`;
}
function sheet(html) {
  $("#overlay").innerHTML = `<div class="scrim" data-act="close-sheet"><div class="sheet" role="dialog" aria-modal="true"><div class="grab"></div>${html}</div></div>`;
  const f = $("#overlay input:not([type=checkbox]), #overlay textarea"); if (f) setTimeout(() => f.focus(), 50);
}
function closeSheet() { $("#overlay").innerHTML = ""; }

// ------------------------------------------------------------------ MIND
const MIND_TABS = [["remind", "⏰ Reminders"], ["saved", "🧠 Saved"], ["lists", "🛒 Lists"], ["charts", "📊 You"], ["passport", "🛂 Passport"]];
async function viewMind(v) {
  v.innerHTML = `<header><div class="eyebrow">Everything you told Mindy, anywhere</div><h1 class="big">Mind</h1></header>
    <div class="chips">${MIND_TABS.map(([k, l]) => `<button class="chip ${S.mindTab === k ? "on" : ""}" data-act="mindtab" data-v="${k}">${l}</button>`).join("")}</div>
    <div id="mind" style="margin-top:18px"><div class="empty">${mindy("think", 80)}</div></div>`;
  const m = $("#mind");
  try { await ({ remind: mindRemind, saved: mindSaved, lists: mindLists, charts: mindCharts, passport: mindPassport }[S.mindTab] || mindRemind)(m); }
  catch (e) { m.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}
async function mindRemind(m) {
  const rs = await api("/reminders");
  const pending = rs.filter(r => r.status === "pending"), past = rs.filter(r => r.status !== "pending");
  m.innerHTML = `<form class="inline-form" data-form="reminder"><input class="field" name="text" placeholder="call mum Sunday 7pm" aria-label="New reminder" required><button class="btn g">Add</button></form>
    <p class="small muted" style="margin:-4px 0 14px">Any time zone: “9am IST”, “in 2 hours”, “every Monday 8am”. Reminders reach you here and on WhatsApp.</p>
    <div class="card">${pending.length ? pending.map(remRow).join("") : `<p class="muted small" style="margin:0">Nothing coming up.</p>`}</div>
    ${past.length ? `<h2 class="sec"><span>Sent, not ticked off</span></h2><div class="card">${past.map(remRow).join("")}</div>` : ""}`;
}
async function mindSaved(m) {
  const [colls, items] = await Promise.all([api("/collections"), api("/items?" + new URLSearchParams({ q: S.savedQ, collection: S.savedColl }))]);
  m.innerHTML = `<form class="inline-form" data-form="search"><input class="field" name="q" value="${esc(S.savedQ)}" placeholder="that pasta reel from last month" aria-label="Search your saves"><button class="btn">Find</button></form>
    <div class="chips" style="margin-top:0"><button class="chip ${!S.savedColl ? "on" : ""}" data-act="coll" data-v="">All</button>${colls.map(c => `<button class="chip ${S.savedColl === c.collection ? "on" : ""}" data-act="coll" data-v="${esc(c.collection)}">${esc(c.collection)} · ${c.n}</button>`).join("")}</div>
    <form class="inline-form" data-form="save" style="margin-top:14px"><input class="field" name="text" placeholder="Paste a link or type a note" aria-label="Save something"><button class="btn g">Save</button></form>
    <div class="card">${items.length ? items.map(i => `<div class="list-item"><div class="grow"><div class="t" style="white-space:normal">${esc(i.text)}</div>
        <div class="s"><span class="pill">${esc(i.collection || "Notes")}</span> · ${esc(ago(i.created_at))}${i.url ? ` · <a class="link" href="${esc(i.url)}" target="_blank" rel="noopener">Open</a>` : ""}
        ${S.cfg.ai && /reel|food|recipe/i.test((i.collection || "") + i.text) ? ` · <button class="link" data-act="recipe" data-id="${i.id}">Recipe card</button>` : ""}</div>
        ${window.MPV ? window.MPV.itemActions(i) : ""}</div>
        <button class="icon-btn" data-act="del-item" data-id="${i.id}" aria-label="Delete">×</button></div>`).join("")
      : `<div class="empty">${mindy("cam", 100)}<p>${S.savedQ ? "Nothing matches that." : "Share reels to Mindy on Instagram, forward things on WhatsApp, or paste them here."}</p></div>`}</div>`;
}
async function mindLists(m) {
  const [lists, occ] = await Promise.all([api("/lists"), api("/occasions")]);
  m.innerHTML = `${lists.map(l => `<div class="card"><div class="row between"><b style="font-size:18px">${esc(l.name)}</b><span class="small muted">${l.items.filter(i => !i.done).length} to go</span></div>
      ${l.items.map(i => `<div class="list-item"><button class="check ${i.done ? "on" : ""}" data-act="toggle" data-id="${i.id}" aria-label="Tick">${i.done ? "✓" : ""}</button><div class="grow ${i.done ? "strike" : ""}">${esc(i.text)}</div></div>`).join("")}
      <form class="inline-form" data-form="listadd" data-list="${esc(l.name)}" style="margin:10px 0 0"><input class="field" name="text" placeholder="Add to ${esc(l.name)}" aria-label="Add item"><button class="btn sm">Add</button></form></div>`).join("")}
    <form class="card" data-form="newlist"><b>New list</b><input class="field" name="name" placeholder="Goa trip packing" style="margin-top:10px" required aria-label="List name">
      <input class="field" name="text" placeholder="sunscreen, charger, speaker" style="margin-top:8px" required aria-label="First items"><button class="btn g block" style="margin-top:10px">Make list</button></form>
    <h2 class="sec"><span>Birthdays and anniversaries</span></h2>
    <div class="card">${occ.length ? occ.map(o => `<div class="list-item"><span style="font-size:22px">🎂</span><div class="grow"><div class="t">${esc(o.person)}</div><div class="s">${esc(o.kind)} · ${o.day} ${new Date(2000, o.month - 1, 1).toLocaleString("en-GB", { month: "long" })}</div></div></div>`).join("") : `<p class="small muted" style="margin:0">None yet.</p>`}
      <form class="inline-form" data-form="occasion" style="margin:12px 0 0"><input class="field" name="text" placeholder="Zoya's birthday is 12 March" aria-label="Add a birthday"><button class="btn sm">Add</button></form></div>`;
}
async function mindCharts(m) {
  const st = await api("/stats");
  const maxR = Math.max(1, ...st.reminders.map(w => w.total));
  const maxC = Math.max(1, ...st.collections.map(c => c.n));
  const today = st.moods[st.moods.length - 1];
  m.innerHTML = `<div class="sticker"><div class="eyebrow">Today</div><h3>${today.mood ? "Checked in ✓" : "How's your head today?"}</h3>
      <div class="faces">${["😫", "😕", "😐", "🙂", "🤩"].map((f, i) => `<button class="${today.mood === i + 1 ? "on" : ""}" data-act="mood" data-v="${i + 1}" aria-label="mood ${i + 1}">${f}</button>`).join("")}</div></div>
    <div class="card"><b>Mood, last 14 days</b><div class="moodline">${st.moods.map(d => `<span title="${esc(d.day)}" style="height:${d.mood ? d.mood * 20 : 6}%;background:${d.mood ? ["#FF5C5C", "#FFC59A", "#FFE29A", "#B8FFE0", "#25D366"][d.mood - 1] : "#1E2429"}"></span>`).join("")}</div>
      <div class="row between small muted" style="margin-top:6px"><span>2 weeks ago</span><span>today</span></div></div>
    <div class="card"><b>Reminders done, by week</b><div class="small muted">Green is done, grey is everything that was due.</div>
      <div class="bars">${st.reminders.map(w => `<div class="b"><div style="display:flex;gap:3px;align-items:flex-end;height:100%;width:100%"><i class="total" style="height:${w.total / maxR * 100}%"></i><i style="height:${w.done / maxR * 100}%"></i></div><small>${esc(w.label)}</small></div>`).join("")}</div></div>
    <div class="card"><b>What you save</b> <span class="small muted">· ${st.saved_total} things</span>
      ${st.collections.length ? st.collections.map(c => `<div class="hbar"><span class="ellipsis">${esc(c.collection)}</span><i style="width:${c.n / maxC * 100}%"></i><span class="small muted">${c.n}</span></div>`).join("") : `<p class="small muted">Nothing saved yet.</p>`}</div>`;
}
async function mindPassport(m) {
  const st = await api("/stamps");
  const count = k => st.filter(s => s.kind === k).length;
  const icon = { country: "🌍", city: "🏙️", cafe: "☕", people: "🫂", wish: "✨" };
  const stamp = (s, i) => `<div class="stamp" style="--r:${(i * 37 % 15) - 7}deg;color:${HUES[i % HUES.length]}"><div>${icon[s.kind] || "📍"}<b>${esc(s.title)}</b>${esc(s.place || s.kind)}<br>${esc(new Date(s.created_at).toLocaleDateString("en-GB", { month: "short", year: "2-digit" }))}</div>
      <button data-act="del-stamp" data-id="${s.id}" aria-label="Remove">×</button></div>`;
  m.innerHTML = `<div class="passport"><div class="row between"><div class="eyebrow g">Passport · ${esc(S.me.name || "")}</div><span>🛂</span></div>
      <div style="font-family:var(--serif);font-size:40px;line-height:1;margin:10px 0">${st.filter(s => s.kind !== "wish").length} stamps</div>
      <div class="row small" style="gap:14px;flex-wrap:wrap"><span>🌍 ${count("country")} countries</span><span>🏙️ ${count("city")} cities</span><span>☕ ${count("cafe")} cafés</span><span>✨ ${count("wish")} on the wishlist</span></div></div>
    <form class="card" data-form="stamp"><b>Add a stamp</b>
      <div class="chips" style="margin:10px 0 0;padding:0;flex-wrap:wrap">${[["city", "🏙️ City"], ["country", "🌍 Country"], ["cafe", "☕ Café"], ["wish", "✨ Wishlist"]].map(([k, l], i) => `<label class="chip"><input type="radio" name="kind" value="${k}" ${i === 0 ? "checked" : ""} style="margin-right:6px">${l}</label>`).join("")}</div>
      <input class="field" name="title" placeholder="Jaipur" style="margin-top:10px" required aria-label="Name"><input class="field" name="place" placeholder="Where or with whom (optional)" style="margin-top:8px" aria-label="Where">
      <button class="btn g block" style="margin-top:10px">Stamp it</button></form>
    ${st.filter(s => s.kind !== "wish").length ? `<div class="stamps">${st.filter(s => s.kind !== "wish").map(stamp).join("")}</div>` : ""}
    ${count("wish") ? `<h2 class="sec"><span>Wishlist</span></h2><div class="stamps">${st.filter(s => s.kind === "wish").map(stamp).join("")}</div>` : ""}`;
}

// ------------------------------------------------------------------ ME
async function viewMe(v) {
  try { S.me = await api("/me"); } catch (e) { return fail(e); }
  const tzs = (Intl.supportedValuesOf ? Intl.supportedValuesOf("timeZone") : [S.me.tz]);
  if (!tzs.includes(S.me.tz)) tzs.unshift(S.me.tz);
  const ig = S.me.channels.includes("ig"), pushOK = "serviceWorker" in navigator && "PushManager" in window;
  const iOS = /iPhone|iPad|iPod/.test(navigator.userAgent), standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  v.innerHTML = `<header class="row"><a class="icon-btn" href="#now" aria-label="Back">←</a><div class="grow"></div><button class="btn sm ghost" data-act="logout">Sign out</button></header>
    <div style="text-align:center;margin-top:10px">${avatar(S.me, "ring")}<h1 class="big" style="font-size:40px">${esc(S.me.name || "You")}</h1></div>
    <form class="card" data-form="profile" style="margin-top:16px"><label class="lbl" for="nm" style="margin-top:0">Name your friends see</label>
      <input class="field" id="nm" name="name" value="${esc(S.me.name || "")}" maxlength="40">
      <label class="lbl" for="tzs">Time zone</label><select class="field" id="tzs" name="tz">${tzs.map(z => `<option ${z === S.me.tz ? "selected" : ""}>${esc(z)}</option>`).join("")}</select>
      <button class="btn block" style="margin-top:12px">Save</button></form>
    ${window.MPV ? window.MPV.meCards() : ""}
    <h2 class="sec"><span>Mindy everywhere</span></h2>
    <div class="card">
      <div class="list-item"><span style="font-size:22px">💬</span><div class="grow"><div class="t">WhatsApp</div><div class="s">Connected. Send anything to Mindy and it shows up here.</div></div><a class="btn sm g" href="https://wa.me/${esc(S.cfg.wa_number || "")}" target="_blank" rel="noopener">Open</a></div>
      <div class="list-item"><span style="font-size:22px">📸</span><div class="grow"><div class="t">Instagram</div><div class="s" id="igline">${ig ? "Connected. Share reels to @" + esc(S.cfg.ig_handle) + " and they land in Saved." : "Share reels straight to Mindy. Get a code, then DM it to @" + esc(S.cfg.ig_handle) + "."}</div></div>
        ${ig ? '<span class="pill g">ON</span>' : '<button class="btn sm" data-act="linkcode">Get code</button>'}</div>
      <div class="list-item"><span style="font-size:22px">✈️</span><div class="grow"><div class="t">Telegram</div><div class="s">${S.me.channels.includes("tg") ? "Connected. Free reminders, open questions, file tools." : "Free reminders, ask anything, convert files. Open the bot, then send <b>link CODE</b>."}</div></div>
        ${S.me.channels.includes("tg") ? '<span class="pill g">ON</span>' : `<a class="btn sm" href="https://t.me/${esc(S.cfg.tg_username || "")}" target="_blank" rel="noopener">Open</a>`}</div></div>
    <h2 class="sec"><span>Notifications</span></h2>
    <div class="card">
      <label class="lbl" for="nt" style="margin-top:0">Where should reminders reach you?</label>
      <select class="field" id="nt" data-act-change="notify">${[["both", "This app and WhatsApp"], ["app", "Only this app"], ["whatsapp", "Only WhatsApp"]].map(([k, l]) => `<option value="${k}" ${S.me.notify === k ? "selected" : ""}>${l}</option>`).join("")}</select>
      <div class="row" style="margin-top:12px;gap:8px;flex-wrap:wrap">${pushOK ? `<button class="btn ${S.me.push ? "ghost" : "g"}" data-act="push">${S.me.push ? "Phone notifications on ✓" : "Turn on phone notifications"}</button>${S.me.push ? '<button class="btn ghost" data-act="push-test">Send a test</button>' : ""}`
        : `<p class="small muted" style="margin:0">${iOS && !standalone ? "On iPhone: tap Share, then “Add to Home Screen”, open Mindy from there, and come back here to turn on notifications." : "This browser can't show notifications. Reminders still reach you on WhatsApp."}</p>`}</div></div>
    <h2 class="sec"><span>Friends</span></h2>
    <div class="card"><div class="row"><div class="grow"><b>Your invite link</b><div class="small muted">Anyone who opens it becomes your friend here.</div></div><button class="btn sm" data-act="invite">Share</button></div></div>
    ${!standalone ? `<div class="card"><b>Put Mindy on your home screen</b><p class="small muted" style="margin:6px 0 0">${iOS ? "Tap Share, then “Add to Home Screen”." : "Use your browser menu: “Install app” or “Add to Home screen”."} It opens full screen like any app, and it's free: no app store.</p>${S.installEvt ? '<button class="btn sm g" style="margin-top:10px" data-act="install">Install</button>' : ""}</div>` : ""}
    <h2 class="sec"><span>Your data</span></h2>
    <div class="card"><div class="row" style="gap:8px;flex-wrap:wrap"><button class="btn ghost" data-act="export">Download everything</button><button class="btn ghost" style="color:var(--red)" data-act="delete">Delete my account</button></div>
      <p class="small muted" style="margin:10px 0 0">Mindy only messages you about things you asked for. <a href="https://whatsonyourmind.online/privacy.html">Privacy</a></p></div>`;
}

// ------------------------------------------------------------------ the thought bubble
function openThink(prefill = "") {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  sheet(`<div class="row">${mindy("think", 74)}<div><h3>What's on your mind?</h3><p class="small muted" style="margin:0">Say it how you'd text a friend. Mindy sorts it.</p></div></div>
    <form data-form="think" style="margin-top:14px"><textarea class="field" name="text" placeholder="dinner with Zoya Saturday 8pm" aria-label="What's on your mind">${esc(prefill)}</textarea>
      <div class="hints" style="margin-top:10px;flex-wrap:wrap">${["remind me to pay rent on the 1st every month", "movie night Friday 9pm with friends", "add milk, eggs and chai to shopping list", "Arjun's birthday is 14 Feb", "where was that pasta place?"].map(h => `<button type="button" data-act="fill" data-v="${esc(h)}">${esc(h)}</button>`).join("")}</div>
      <div class="row" style="margin-top:12px;gap:8px">${SR ? '<button type="button" class="btn ghost" data-act="mic" aria-label="Speak">🎙️ Speak</button>' : ""}<button class="btn g grow">Do it</button></div></form>
    <div class="hints" style="margin-top:14px;flex-wrap:wrap">${[["screen", "📸 Help with my phone"], ["scam", "🛡️ Is this a scam?"], ["khata", "📒 Khata"], ["homework", "🧑‍🎓 Homework help"], ["privacy", "🔒 Privacy check-up"]].map(([k, l]) => `<button type="button" data-act="tool" data-v="${k}">${l}</button>`).join("")}</div>
    <div id="thinkout"></div>`);
}

// ------------------------------------------------------------------ games
function gameSheet(game, withIds = []) {
  sheet(`<h3>${game === "lastcard" ? "Last Card" : game === "hand" ? "Hand cricket" : "Play"}</h3>
    <form data-form="game"><div class="seg">${[["hand", "🏏 Hand cricket"], ["lastcard", "🃏 Last Card"]].map(([k, l]) => `<label style="flex:1"><input type="radio" name="game" value="${k}" ${k === (game || "hand") ? "checked" : ""} hidden><span class="chip" style="display:block;text-align:center">${l}</span></label>`).join("")}</div>
    <p class="small muted">Pick friends (hand cricket: one; Last Card: up to three). Pick nobody to play Mindy.</p>
    ${pickFriends(3, withIds)}<button class="btn g block" style="margin-top:14px">Start</button></form>`);
  syncSeg();
}
function syncSeg() { document.querySelectorAll('#overlay .seg label').forEach(l => { const i = l.querySelector("input"); l.querySelector(".chip").classList.toggle("on", i.checked); }); }
function openRoom(kind, id) { S.room = { kind, id }; renderRoom(); }
function closeRoom() { if (S.room && S.room.kind === "party") { send({ type: "party.leave", room: S.room.id }); delete S.parties[S.room.id]; } S.room = null; if (S.yt) { try { S.yt.destroy(); } catch (_) {} S.yt = null; } $("#overlay").innerHTML = ""; if ((location.hash || "#now") === "#plans") route(); }
function renderRoom() {
  if (!S.room) return;
  if (S.room.kind === "game") return renderGame();
  return renderParty();
}
function renderGame() {
  const g = S.games[S.room.id]; if (!g) return;
  const st = g.state, nm = id => id === S.me.id ? "You" : (g.names[String(id)] || "Friend");
  let body;
  if (g.game === "hand") {
    const [a, b] = st.players, bat = st.batting;
    const status = st.over ? (st.winner == null ? "It's a tie!" : st.winner === S.me.id ? "You won! 🏆" : esc(nm(st.winner)) + " won.")
      : st.waiting ? "Thrown. Waiting for " + esc(nm(st.players.find(p => p !== S.me.id))) + "…" : (bat === S.me.id ? "You're batting. Throw!" : "You're bowling. Match their number to get them out.");
    body = `<div class="eyebrow g">Hand cricket · innings ${st.innings}${st.target ? " · target " + st.target : ""}</div>
      <div class="score">${[a, b].map((p, i) => `${i === 1 ? '<div class="muted">vs</div>' : ""}<div><div class="n ${p === bat && !st.over ? "bat" : ""}">${st.score[String(p)]}</div><div class="who">${esc(nm(p))}${p === bat && !st.over ? " 🏏" : ""}</div></div>`).join("")}</div>
      ${st.last ? `<div class="card" style="text-align:center"><div class="small muted">Last ball</div><div class="reveal"><span>🏏 ${st.last.bat}</span><span>🎯 ${st.last.bowl}</span></div>
        <div style="font-family:var(--display);font-weight:800;font-size:26px;margin-top:6px" class="${st.last.out ? "out" : ""}">${st.last.out ? "OUT!" : "+" + st.last.runs}</div></div>` : ""}
      <p style="text-align:center;font-weight:700;margin:16px 0 0">${status}</p>
      ${st.over ? "" : `<div class="throws">${[1, 2, 3, 4, 5, 6].map(n => `<button data-act="throw" data-v="${n}" ${st.waiting ? "disabled" : ""}>${n}</button>`).join("")}</div>`}`;
  } else {
    const mine = st.turn === S.me.id && !st.over;
    const can = c => mine && (c.c === "wild" || c.c === st.colour || c.v === st.top.v);
    body = `<div class="eyebrow g">Last Card · ${st.players.length} players · deck ${st.deck}</div>
      <div class="opps" style="margin-top:14px">${st.players.filter(p => p !== S.me.id).map(p => `<div class="opp ${st.turn === p ? "turn" : ""}">${esc(nm(p))} · ${st.counts[String(p)]} 🂠</div>`).join("")}</div>
      <div class="table"><button class="lc big" style="background:#1A2024;color:var(--cream)" data-act="lc-draw" ${mine ? "" : "disabled"} aria-label="Draw a card"><span>+1</span><small>draw</small></button>
        <div class="lc big ${st.top.c}"><span>${esc(st.top.v === "rev" ? "⇄" : st.top.v === "skip" ? "⊘" : st.top.v === "wild" ? "★" : st.top.v)}</span><small>${esc(st.colour)}</small></div></div>
      <p style="text-align:center;font-weight:700;margin:0">${st.over ? (st.winner === S.me.id ? "You won! 🏆" : esc(nm(st.winner)) + " won.") : mine ? "Your go. Tap a raised card." : "Waiting for " + esc(nm(st.turn)) + "…"}</p>
      ${!st.over && st.hand.length === 2 && mine ? `<label class="row" style="justify-content:center;margin-top:10px;gap:8px;font-weight:700"><input type="checkbox" id="lastcall"> Say “Last card!” with this play</label>` : ""}
      <div class="hand">${st.hand.map(c => `<button class="lc ${c.c} ${can(c) ? "ok" : mine ? "no" : ""}" data-act="lc-play" data-id="${c.id}" data-c="${c.c}" ${can(c) ? "" : "disabled"}><span>${esc(c.v === "rev" ? "⇄" : c.v === "skip" ? "⊘" : c.v === "wild" ? "★" : c.v)}</span><small>${c.c === "wild" ? "wild" : esc(c.v.length > 1 && c.v !== "+2" ? c.v : c.c)}</small></button>`).join("")}</div>
      <div id="wildpick"></div>`;
  }
  $("#overlay").innerHTML = `<div class="room"><div class="inner"><div class="row"><button class="icon-btn" data-act="close-room" aria-label="Close">×</button><div class="grow"></div>
      ${st.over ? `<button class="btn sm g" data-act="rematch">Rematch</button>` : ""}</div>${body}
    <div class="log">${(st.log || []).map(esc).join("<br>")}</div></div></div>`;
}

// ------------------------------------------------------------------ watch parties
function partySheet(withIds = []) {
  sheet(`<h3>Watch party</h3><p class="small muted" style="margin:0 0 10px">YouTube plays in sync for everyone. For other apps, Mindy runs a shared countdown so you all press play together.</p>
    <form data-form="party"><label class="lbl" for="pl">YouTube link, or the show's link in another app</label>
      <input class="field" id="pl" name="url" placeholder="https://youtu.be/…" aria-label="Link">
      <label class="lbl">Watching on</label><select class="field" name="service"><option value="">YouTube</option>${Object.keys(SERVICES).map(s => `<option>${esc(s)}</option>`).join("")}</select>
      <input class="field" name="title" placeholder="What are you watching? (optional)" style="margin-top:8px" aria-label="Title">
      <label class="lbl">Invite</label>${pickFriends(9, withIds)}<button class="btn g block" style="margin-top:14px">Start the party</button></form>`);
}
function loadYT() {
  if (window.YT && window.YT.Player) return Promise.resolve();
  return new Promise(res => {
    const prev = window.onYouTubeIframeAPIReady; window.onYouTubeIframeAPIReady = () => { if (prev) prev(); res(); };
    if (!document.getElementById("ytapi")) { const s = document.createElement("script"); s.id = "ytapi"; s.src = "https://www.youtube.com/iframe_api"; document.head.appendChild(s); }
  });
}
function renderParty() {
  const p = S.parties[S.room.id]; if (!p) return;
  const fresh = !$("#partyroom") || $("#partyroom").dataset.id !== p.room;
  if (fresh) {
    $("#overlay").innerHTML = `<div class="room" id="partyroom" data-id="${esc(p.room)}"><div class="inner">
      <div class="row"><button class="icon-btn" data-act="close-room" aria-label="Leave">×</button><div class="grow"><b class="ellipsis" style="display:block">${esc(p.title)}</b><span class="small muted" id="pmembers"></span></div>
        <button class="btn sm ghost" data-act="party-invite">Invite</button></div>
      <div class="screenbox" style="margin-top:12px">${p.video ? '<div id="yt"></div>' : `<div style="position:absolute;inset:0;display:grid;place-items:center;text-align:center;padding:16px"><div><div class="eyebrow">${esc(p.service || "")}</div><div id="cd" class="countdown">▶</div><div class="small muted" id="cdhint">Everyone opens it, then anyone taps the countdown.</div></div></div>`}<div class="floaters" id="floaters"></div></div>
      ${p.video ? "" : `<div class="row" style="gap:8px;margin-top:12px">${p.link || SERVICES[p.service] ? `<a class="btn grow" href="${esc(p.link || SERVICES[p.service])}" target="_blank" rel="noopener">Open ${esc(p.service || "link")}</a>` : ""}<button class="btn g grow" data-act="countdown">3·2·1 together</button></div>`}
      <div class="reacts">${["😂", "😭", "🔥", "😱", "❤️", "🏏"].map(e => `<button data-act="react" data-v="${e}">${e}</button>`).join("")}</div>
      <div class="card"><div class="pchat" id="pchat"><span class="muted small">Chat with everyone watching.</span></div>
        <form class="row" data-form="pchat" style="gap:8px"><input class="field" name="text" placeholder="Say something" autocomplete="off" aria-label="Chat"><button class="btn sm g">Send</button></form></div></div></div>`;
    if (p.video) loadYT().then(() => {
      S.yt = new YT.Player("yt", { videoId: p.video, playerVars: { playsinline: 1, rel: 0, modestbranding: 1 }, events: {
        onReady: () => applySync(S.parties[p.room]),
        onStateChange: e => {
          if (S.ytQuiet) return;
          if (e.data === YT.PlayerState.PLAYING || e.data === YT.PlayerState.PAUSED)
            send({ type: "party.sync", room: p.room, playing: e.data === YT.PlayerState.PLAYING, t: S.yt.getCurrentTime() });
        } } });
    });
  }
  const pm = $("#pmembers"); if (pm) pm.textContent = p.members.map(m => m.id === S.me.id ? "You" : m.name).join(", ");
}
function applySync(p) {
  if (!S.yt || !S.yt.seekTo || !p) return;
  S.ytQuiet = true;
  const t = p.t + (p.playing && p.at ? (Date.now() - p.at) / 1000 : 0);
  if (Math.abs(S.yt.getCurrentTime() - t) > 1.2) S.yt.seekTo(t, true);
  p.playing ? S.yt.playVideo() : S.yt.pauseVideo();
  clearTimeout(S.ytT); S.ytT = setTimeout(() => { S.ytQuiet = false; }, 900);
}
function floatEmoji(e) {
  const f = $("#floaters"); if (!f) return;
  const s = document.createElement("span"); s.textContent = e; s.style.left = (10 + Math.random() * 80) + "%"; f.appendChild(s); setTimeout(() => s.remove(), 2500);
}
function partyLine(html) { const c = $("#pchat"); if (!c) return; if (c.firstElementChild && c.firstElementChild.classList.contains("muted")) c.innerHTML = ""; c.insertAdjacentHTML("beforeend", `<div>${html}</div>`); c.scrollTop = c.scrollHeight; }

// ------------------------------------------------------------------ live socket
function send(obj) { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(obj)); else toast("Reconnecting…", "Give it a second and try again."); }
function connect() {
  if (!S.token) return;
  const base = API ? API.replace(/^http/, "ws") : location.origin.replace(/^http/, "ws");
  const ws = new WebSocket(base + "/ws?token=" + encodeURIComponent(S.token));
  S.ws = ws;
  ws.onopen = () => { S.wsTries = 0; clearInterval(S.ping); S.ping = setInterval(() => send({ type: "ping" }), 25000); };
  ws.onclose = () => { clearInterval(S.ping); if (S.token && S.ws === ws) setTimeout(connect, Math.min(15000, 1000 * 2 ** S.wsTries++)); };
  ws.onmessage = ev => { let e; try { e = JSON.parse(ev.data); } catch (_) { return; } onEvent(e); };
}
function onEvent(e) {
  const hash = location.hash || "#now";
  switch (e.type) {
    case "auth.failed": return signOutLocal();
    case "hello": S.online = new Set(e.online); return;
    case "presence": case "status": {
      if (e.type === "presence") { e.online ? S.online.add(e.user) : S.online.delete(e.user); }
      const f = S.friends.find(x => x.id === e.user);
      if (f) { if (e.type === "presence") f.online = e.online; else { f.status = e.status === "ghost" ? "away" : e.status; if (e.status === "ghost") f.online = false; } }
      const row = $("#people"); if (row) row.innerHTML = peopleRow();
      return;
    }
    case "friend.update": { const f = S.friends.find(x => x.id === e.user); if (f) f.name = e.name; const row = $("#people"); if (row) row.innerHTML = peopleRow(); return; }
    case "friend.new": S.online.add(e.user); toast(`${e.name} joined you on Mindy 🎉`, "You're friends now."); if (hash === "#now") route(); return;
    case "chat.message": {
      if (S.chatId === e.chat) {
        const t = $("#thread"); if (t) { if (t.querySelector("p.muted")) t.innerHTML = ""; t.insertAdjacentHTML("beforeend", msgHtml(e.message)); scrollThread(); }
        api(`/chats/${e.chat}/messages?after=${e.message.id - 1}`).catch(() => {});
      } else if (e.message.user_id !== S.me.id) {
        S.unread++; setBadge();
        toast((e.message.kind === "mindy" ? "Mindy" : e.message.name || "Friend"), e.message.body.slice(0, 90), { label: "Open", run: () => { location.hash = "chat/" + e.chat; } });
        if (hash === "#chats") route();
      }
      return;
    }
    case "care.taken": toast(`✅ ${e.name} took ${e.text}`, "All good."); if (["#care", "#now", ""].includes(location.hash)) route(); return;
    case "care.missed": toast(`⚠️ ${e.name} hasn't confirmed ${e.text}`, "Maybe give them a call?", { label: "See", run: () => { location.hash = "care"; } }); return;
    case "plan.invite": toast(`${e.from} made a plan`, e.title, { label: "See it", run: () => { location.hash = "plans"; } }); return;
    case "notify": toast(e.title || "Mindy", e.body, e.url && e.url !== "/" ? { label: "Open", run: () => { location.hash = e.url.replace(/^\/?#?/, ""); } } : null, 9000); if (hash === "#now" || hash === "#mind") route(); return;
    case "game.invite": toast(`${e.from} challenged you`, e.game === "hand" ? "🏏 Hand cricket" : "🃏 Last Card", { label: "Play", run: () => openRoom("game", e.room) }); return;
    case "game.state": {
      const first = !S.games[e.room];
      S.games[e.room] = { game: e.game, names: e.names, state: e.state };
      if ((S.room && S.room.kind === "game" && S.room.id === e.room) || (first && e.state.players[0] === S.me.id && S.pendingGame)) { S.pendingGame = false; openRoom("game", e.room); }
      return;
    }
    case "game.error": return toast("Not yet", e.message);
    case "party.invite": toast(`${e.from} started a watch party`, e.title, { label: "Join", run: () => { send({ type: "party.join", room: e.room }); S.pendingParty = e.room; } }); return;
    case "party.state": {
      const prev = S.parties[e.room];
      S.parties[e.room] = Object.assign({}, e, { at: Date.now() });
      if (S.pendingParty === e.room || (!prev && e.host === S.me.id && S.pendingPartyNew)) { S.pendingParty = null; S.pendingPartyNew = false; openRoom("party", e.room); }
      else if (S.room && S.room.id === e.room) renderParty();
      return;
    }
    case "party.sync": {
      const p = S.parties[e.room]; if (!p) return;
      Object.assign(p, { playing: e.playing, t: e.t, at: Date.now() });
      if (S.room && S.room.id === e.room) { applySync(p); partyLine(`<span class="muted">${esc(nameOf(e.by))} ${e.playing ? "pressed play" : "paused"}</span>`); }
      return;
    }
    case "party.countdown": {
      if (!(S.room && S.room.id === e.room)) return;
      let n = 3; const cd = $("#cd"), hint = $("#cdhint");
      const tick = () => { if (!cd) return; cd.style.fontSize = ""; if (n > 0) { cd.textContent = n--; setTimeout(tick, 1000); } else { cd.textContent = "PLAY"; cd.style.fontSize = "72px"; if (hint) hint.textContent = "Press play now!"; if (navigator.vibrate) navigator.vibrate(200); } };
      setTimeout(tick, 1000); if (cd) { cd.textContent = "Ready"; cd.style.fontSize = "72px"; } return;
    }
    case "party.react": if (S.room && S.room.id === e.room) floatEmoji(e.emoji); return;
    case "party.chat": if (S.room && S.room.id === e.room) partyLine(`<b>${esc(e.user === S.me.id ? "You" : e.from)}</b> ${esc(e.text)}`); return;
    case "error": return toast("Hmm.", e.message);
  }
}

// ------------------------------------------------------------------ clicks
const ACT = {
  havecode() { S.login = { step: "code" }; renderLogin(); },
  "back-phone"() { S.login = { step: "phone", phone: S.login.phone }; renderLogin(); },
  think() { openThink(); },
  fill(el) { const t = $("#overlay textarea"); t.value = el.dataset.v; t.focus(); },
  hint(el) { const i = $(".composer input"); i.value = el.dataset.v; i.focus(); },
  mic(el) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition; const r = new SR();
    r.lang = navigator.language || "en-IN"; r.interimResults = true; el.textContent = "🎙️ Listening…";
    r.onresult = ev => { $("#overlay textarea").value = [...ev.results].map(x => x[0].transcript).join(""); };
    r.onend = () => { el.textContent = "🎙️ Speak"; }; r.start();
  },
  "close-sheet"(el, ev) { if (ev.target === el) closeSheet(); },
  async status(el) {
    try { S.me = Object.assign(S.me, await api("/me", { method: "PATCH", body: { status: el.dataset.v } })); document.querySelectorAll('[data-act="status"]').forEach(b => b.classList.toggle("on", b === el)); if (el.dataset.v === "ghost") toast("Ghost mode 👻", "Friends see you as away."); } catch (e) { fail(e); }
  },
  async invite() { try { const r = await api("/invite"); share(`Come on Mindy with me: plans, games and watch parties. ${r.url}`, r.url); } catch (e) { fail(e); } },
  async mood(el) { try { await api("/moods", { body: { mood: Number(el.dataset.v) } }); toast(["Rough one. Be kind to yourself today.", "Noted. Small steps.", "Steady. Fair enough.", "Nice 🙂", "Love that energy 🤩"][el.dataset.v - 1]); route(); } catch (e) { fail(e); } },
  async "rem-done"(el) { try { await api(`/reminders/${el.dataset.id}/done`, { body: {} }); el.classList.add("on"); el.textContent = "✓"; setTimeout(() => el.closest(".list-item").remove(), 400); } catch (e) { fail(e); } },
  async "rem-snooze"(el) { try { const r = await api(`/reminders/${el.dataset.id}/snooze`, { body: { minutes: 60 } }); toast("Snoozed 😴", "Back at " + fmtWhen(r.due_at)); route(); } catch (e) { fail(e); } },
  async rsvp(el) { try { await api(`/plans/${el.dataset.id}/rsvp`, { body: { rsvp: el.dataset.v } }); route(); } catch (e) { fail(e); } },
  mindtab(el) { S.mindTab = el.dataset.v; store.set("mindy_mindtab", S.mindTab); if (location.hash !== "#mind") location.hash = "mind"; else route(); },
  coll(el) { S.savedColl = el.dataset.v; S.savedQ = ""; route(); },
  async "del-item"(el) { try { await api(`/items/${el.dataset.id}`, { method: "DELETE" }); el.closest(".list-item").remove(); } catch (e) { fail(e); } },
  async recipe(el) {
    el.textContent = "Making…";
    try { const r = await api(`/items/${el.dataset.id}/recipe`, { body: {} });
      sheet(`<div class="eyebrow g">Recipe card${r.time ? " · " + esc(r.time) : ""}</div><h3>${esc(r.title)}</h3><b>You need</b><ul>${(r.ingredients || []).map(i => `<li>${esc(i)}</li>`).join("")}</ul><b>Method</b><ol>${(r.steps || []).map(i => `<li style="margin-bottom:6px">${esc(i)}</li>`).join("")}</ol>`);
    } catch (e) { fail(e); } finally { el.textContent = "Recipe card"; }
  },
  async toggle(el) { try { await api(`/list-items/${el.dataset.id}/toggle`, { body: {} }); el.classList.toggle("on"); el.textContent = el.classList.contains("on") ? "✓" : ""; el.nextElementSibling.classList.toggle("strike"); } catch (e) { fail(e); } },
  async "del-stamp"(el) { try { await api(`/stamps/${el.dataset.id}`, { method: "DELETE" }); route(); } catch (e) { fail(e); } },
  async dm(el) { try { const r = await api("/chats", { body: { members: [Number(el.dataset.id)] } }); await refreshChats(); location.hash = "chat/" + r.id; } catch (e) { fail(e); } },
  newchat() {
    if (!S.friends.length) return ACT.invite();
    sheet(`<h3>New chat</h3><form data-form="newchat"><p class="small muted">One friend for a DM, more for a group. Mindy is in every chat.</p>${pickFriends(20)}
      <input class="field" name="name" placeholder="Group name (optional)" style="margin-top:12px" aria-label="Group name"><button class="btn g block" style="margin-top:12px">Start chatting</button></form>`);
  },
  "game-sheet"(el) { gameSheet(el.dataset.game, (el.dataset.with || "").split(",").filter(Boolean)); },
  "party-sheet"(el) { partySheet((el.dataset.with || "").split(",").filter(Boolean)); },
  "open-game"(el) { openRoom("game", el.dataset.id); },
  "open-party"(el) { send({ type: "party.join", room: el.dataset.id }); openRoom("party", el.dataset.id); },
  "close-room"() { closeRoom(); },
  throw(el) { send({ type: "game.move", room: S.room.id, move: { n: Number(el.dataset.v) } }); document.querySelectorAll(".throws button").forEach(b => b.disabled = true); },
  "lc-draw"() { send({ type: "game.move", room: S.room.id, move: { act: "draw" } }); },
  "lc-play"(el) {
    const last = !!($("#lastcall") && $("#lastcall").checked), id = Number(el.dataset.id);
    if (el.dataset.c === "wild") {
      $("#wildpick").innerHTML = `<p style="text-align:center;margin:14px 0 0;font-weight:700">Pick a colour</p><div class="swatches">${["cyan", "pink", "mint", "violet"].map(c => `<button class="lc ${c}" style="width:46px;height:46px" data-act="lc-wild" data-c="${c}" data-id="${id}" data-last="${last}" aria-label="${c}"></button>`).join("")}</div>`;
      return;
    }
    send({ type: "game.move", room: S.room.id, move: { act: "play", card: id, last } });
  },
  "lc-wild"(el) { send({ type: "game.move", room: S.room.id, move: { act: "play", card: Number(el.dataset.id), colour: el.dataset.c, last: el.dataset.last === "true" } }); },
  rematch() { const g = S.games[S.room.id]; const others = g.state.players.filter(p => p !== S.me.id && p !== 0); S.pendingGame = true; send({ type: "game.new", game: g.game, with: others }); },
  react(el) { send({ type: "party.react", room: S.room.id, emoji: el.dataset.v }); },
  countdown() { send({ type: "party.countdown", room: S.room.id }); },
  "party-invite"() { const p = S.parties[S.room.id]; share(`Join my watch party on Mindy: ${p.title}`, location.origin + "/#plans"); },
  async linkcode() { try { const r = await api("/link-code", { body: {} }); $("#igline").innerHTML = `Send <b style="color:var(--cream)">link ${esc(r.code)}</b> to <a class="link" href="https://ig.me/m/${esc(S.cfg.ig_handle)}" target="_blank" rel="noopener">@${esc(S.cfg.ig_handle)}</a> on Instagram within 15 minutes.`; } catch (e) { fail(e); } },
  async push(el) {
    try {
      if (Notification.permission === "denied") return toast("Notifications are blocked", "Allow them for this site in your browser settings, then try again.");
      if ((await Notification.requestPermission()) !== "granted") return;
      const reg = await navigator.serviceWorker.ready;
      const { key } = await api("/push/key");
      const pad = "=".repeat((4 - key.length % 4) % 4), raw = atob((key + pad).replace(/-/g, "+").replace(/_/g, "/"));
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: Uint8Array.from(raw, c => c.charCodeAt(0)) });
      await api("/push/subscribe", { body: { subscription: sub.toJSON() } });
      toast("Phone notifications on ✓", "Mindy pings you only about things you asked for."); route();
    } catch (e) { fail(e); }
  },
  async "push-test"() { try { const r = await api("/push/test", { body: {} }); toast(r.sent ? "Sent. Check your notifications." : "Couldn't reach this device. Turn notifications off and on again."); } catch (e) { fail(e); } },
  async install() { if (S.installEvt) { S.installEvt.prompt(); S.installEvt = null; } },
  async export() {
    try { const r = await fetch(API + "/api/export", { headers: { Authorization: "Bearer " + S.token } }); const b = await r.blob();
      const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "mindy-export.json"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); } catch (e) { fail(e); }
  },
  delete() {
    sheet(`<h3>Delete everything?</h3><p class="muted">Your saves, reminders, lists, chats, friends and stamps are deleted for good, here and on WhatsApp and Instagram.</p>
      <form data-form="delete"><input class="field" name="confirm" placeholder="Type DELETE" aria-label="Type DELETE to confirm"><button class="btn block" style="margin-top:12px;background:var(--red)">Delete my account</button></form>`);
  },
  async logout() { try { await api("/auth/logout", { body: {} }); } catch (_) {} signOutLocal(); }
};
document.addEventListener("click", ev => {
  const tab = ev.target.closest("[data-tab]");
  if (tab) { location.hash = tab.dataset.tab; return; }
  const el = ev.target.closest("[data-act]");
  if (!el || !ACT[el.dataset.act]) return;
  if (el.tagName === "A" && el.getAttribute("href") === "#") ev.preventDefault();
  ACT[el.dataset.act](el, ev);
});
document.addEventListener("change", ev => {
  if (ev.target.matches('#overlay .seg input')) syncSeg();
  if (ev.target.dataset.actChange === "notify") api("/me", { method: "PATCH", body: { notify: ev.target.value } }).then(() => toast("Saved")).catch(fail);
  if (ev.target.name === "with" && ev.target.form && ev.target.form.dataset.form === "game") {
    const game = new FormData(ev.target.form).get("game"), max = game === "hand" ? 1 : 3, boxes = [...ev.target.form.querySelectorAll('[name="with"]:checked')];
    if (boxes.length > max) { ev.target.checked = false; toast(game === "hand" ? "Hand cricket is one-on-one" : "Last Card is up to 4 players"); }
  }
});
window.addEventListener("beforeinstallprompt", e => { e.preventDefault(); S.installEvt = e; });

// ------------------------------------------------------------------ forms
const FORM = {
  async start(f) {
    const phone = f.phone.value.trim();
    const r = await api("/auth/start", { body: { phone } });
    S.login = { step: "code", phone, dev: r.dev_code }; renderLogin();
  },
  async verify(f) {
    const r = await api("/auth/verify", { body: { code: f.code.value.trim(), phone: S.login.phone || undefined } });
    S.token = r.token; store.set("mindy_token", r.token);
    S.me = await api("/me");
    if (!S.me.name || S.me.name === "You") { S.login = { step: "name" }; return renderLogin(); }
    return enter();
  },
  async name(f) {
    S.me = Object.assign(S.me, await api("/me", { method: "PATCH", body: { name: f.name.value.trim() } }));
    return enter();
  },
  async think(f) {
    const text = f.text.value.trim(); if (!text) return;
    const btn = f.querySelector(".btn.g"); btn.textContent = "Thinking…";
    try {
      const r = await api("/think", { body: { text } });
      $("#thinkout").innerHTML = `<div class="sticker" style="margin-top:16px"><div class="eyebrow">Mindy</div><p style="white-space:pre-wrap;font-size:16px">${esc(r.reply)}</p>
        ${(r.links || []).map(([l, u]) => `<a class="btn dark" style="margin:10px 8px 0 0" href="${esc(u)}" target="_blank" rel="noopener">${esc(l)}</a>`).join("")}</div>`;
      f.text.value = "";
      if (r.did.length && ["#now", "#mind", "#plans", ""].includes(location.hash)) route();
    } finally { btn.textContent = "Do it"; }
  },
  async send(f) {
    const body = f.body.value.trim(); if (!body) return; f.body.value = "";
    await api(`/chats/${S.chatId}/messages`, { body: { body } });
  },
  async newchat(f) {
    const members = [...f.querySelectorAll('[name="with"]:checked')].map(i => Number(i.value));
    if (!members.length) return toast("Pick at least one friend");
    const r = await api("/chats", { body: { members, name: f.name.value.trim() } }); closeSheet(); await refreshChats(); location.hash = "chat/" + r.id;
  },
  async plan(f) {
    const people = [...f.querySelectorAll('[name="people"]:checked')].map(i => Number(i.value));
    await api("/plans", { body: { title: f.title.value.trim(), when: f.when.value.trim(), people } }); toast("Plan made 🗓️", people.length ? "Invites sent." : "Add friends to invite them."); route();
  },
  async game(f) {
    const game = new FormData(f).get("game"), w = [...f.querySelectorAll('[name="with"]:checked')].map(i => Number(i.value));
    S.pendingGame = true; send({ type: "game.new", game, with: w }); closeSheet();
  },
  async party(f) {
    const url = f.url.value.trim(), service = f.service.value, w = [...f.querySelectorAll('[name="with"]:checked')].map(i => Number(i.value));
    if (!service && !/youtu/.test(url)) return toast("Paste a YouTube link", "Or pick Netflix, Prime Video or another app under “Watching on”.");
    S.pendingPartyNew = true;
    send({ type: "party.new", url, service: service || undefined, link: service ? url : "", title: f.title.value.trim() || (service ? service + " night" : ""), with: w }); closeSheet();
  },
  async pchat(f) { const text = f.text.value.trim(); if (!text) return; f.text.value = ""; send({ type: "party.chat", room: S.room.id, text }); },
  async reminder(f) { const r = await api("/reminders", { body: { text: f.text.value.trim() } }); toast("Reminder set ⏰", r.text + " · " + fmtWhen(r.due_at)); route(); },
  async search(f) { S.savedQ = f.q.value.trim(); S.savedColl = ""; route(); },
  async save(f) { const t = f.text.value.trim(); if (!t) return; const r = await api("/items", { body: { text: t } }); toast("Saved 🧠", "In " + r.collection); route(); },
  async listadd(f) { await api(`/lists/${encodeURIComponent(f.dataset.list)}/items`, { body: { text: f.text.value.trim() } }); route(); },
  async newlist(f) { await api(`/lists/${encodeURIComponent(f.name.value.trim())}/items`, { body: { text: f.text.value.trim() } }); route(); },
  async occasion(f) { const r = await api("/think", { body: { text: f.text.value.trim() } }); toast(r.did.length ? "Saved 🎂" : "Hmm", r.reply); route(); },
  async stamp(f) { await api("/stamps", { body: { kind: new FormData(f).get("kind"), title: f.title.value.trim(), place: f.place.value.trim() } }); toast("Stamped 🛂"); route(); },
  async profile(f) { S.me = Object.assign(S.me, await api("/me", { method: "PATCH", body: { name: f.name.value.trim(), tz: f.tz.value } })); toast("Saved"); },
  async delete(f) { await api("/delete-account", { body: { confirm: f.confirm.value.trim() } }); closeSheet(); toast("Deleted. Take care 👋"); signOutLocal(); }
};
document.addEventListener("submit", async ev => {
  const f = ev.target; if (!f.dataset.form || !FORM[f.dataset.form]) return;
  ev.preventDefault();
  const b = f.querySelector("button:not([type=button])"); if (b) b.disabled = true;
  try { await FORM[f.dataset.form](f); } catch (e) { fail(e); } finally { if (b && b.isConnected) b.disabled = false; }
});

window.M = { S, api, esc, $, toast, fail, sheet, closeSheet, route, mindy, avatar, fmtWhen, ago, share, ACT, FORM, store, initial, hue };
if (window.MindyPower) window.MindyPower(window.M);
boot();
})();
