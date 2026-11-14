/* Mindy, the tech friend: the screens for saves-that-become-real, family care, khata, scam shield,
   screenshot help, homework help, privacy check-up, simple mode and Google sign-in.
   Loaded before app.js; app.js hands over its helpers through window.MindyPower(M). */
(() => {
"use strict";
const ACTIONS = {
  recipe: [["shop", "🛒 Shopping list"], ["cook", "🍳 Cook Sunday"], ["go", "👯 With friends"]],
  place: [["go", "👯 Go with friends"], ["remind", "📍 This weekend"], ["done", "✅ Been"]],
  travel: [["go", "✈️ Plan trip"], ["remind", "⏰ Remind me"], ["done", "✅ Been"]],
  event: [["go", "🎟️ With friends"], ["remind", "⏰ Remind me"], ["done", "✅ Went"]],
  workout: [["train", "💪 Every Monday"], ["remind", "⏰ Tomorrow"], ["done", "✅ Did it"]],
  study: [["revise", "📚 Revise"], ["quiz", "🧠 Quiz me"], ["done", "✅ Learnt"]],
  product: [["price", "🏷️ Check in a week"], ["done", "✅ Bought"]],
  idea: [["remind", "⏰ Sunday"], ["done", "✅ Did it"]],
  fun: [["go", "👯 With friends"], ["done", "✅ Did it"]],
  other: [["remind", "⏰ Remind me"], ["done", "✅ Did it"]]
};
let M;

function fileToDataURL(file, max = 1600) {
  return new Promise((res, rej) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement("canvas"); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
      res(c.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = rej; img.src = url;
  });
}
const speak = t => { try { const u = new SpeechSynthesisUtterance(t); u.lang = navigator.language || "en-IN"; speechSynthesis.cancel(); speechSynthesis.speak(u); } catch (_) {} };

const V = {
  // ---------------------------------------------------------------- cards on Now
  nowCards(H) {
    const { esc, mindy } = M;
    let out = "";
    if (H.care && H.care.length) {
      out += `<h2 class="sec"><span>Family care</span><button onclick="location.hash='care'">OPEN →</button></h2>` + H.care.map(c => `<div class="card">
        <b>${esc(c.member.name)}</b>${c.doses.slice(0, 4).map(d => `<div class="list-item"><span style="font-size:20px">${{ taken: "✅", missed: "⚠️", waiting: "⏳", upcoming: "💊" }[d.state]}</span>
          <div class="grow"><div class="t">${esc(d.text)}</div><div class="s">${esc(M.fmtWhen(d.due_at))} · ${esc(d.state)}</div></div>
          ${c.member.name === "You" && d.state === "waiting" || c.member.name === "You" && d.state === "missed" ? `<button class="btn sm g" data-act="took" data-id="${d.id}">I took it</button>` : ""}</div>`).join("")}</div>`).join("");
    }
    const s = H.score || {};
    out += `<div class="sticker" style="margin-top:18px"><div class="eyebrow">Saves → real life</div>
      <h3>${s.done_week || 0} done this week ${s.streak ? `· 🔥 ${s.streak}` : ""}</h3>
      <p>You saved ${s.saved_week || 0} things this week. ${s.saved_week ? "Pick one and make it happen." : "Share reels to Mindy on Instagram or WhatsApp and they land here, ready to do."}</p>
      ${(H.todo || []).map(i => `<div style="margin-top:12px;padding-top:10px;border-top:1px dashed #0002"><b style="color:#000">${esc(i.title || i.text.slice(0, 60))}</b>${V.itemActions(i, true)}</div>`).join("")}</div>`;
    if (H.matches && H.matches.length) {
      out += `<h2 class="sec"><span>Do it together</span></h2>` + H.matches.map(m => `<div class="card"><div class="row">${M.avatar(m.friend, "sm")}
        <div class="grow"><b>You and ${esc(m.friend.name || "a friend")}</b><div class="small muted">${esc(m.why)}: ${esc(m.item.title || "")}</div></div>
        <button class="btn sm g" data-act="match-go" data-id="${m.item.id}" data-friend="${m.friend.id}">Plan it</button></div></div>`).join("");
    }
    out += `<div class="row" style="gap:8px;margin-top:14px;flex-wrap:wrap">${[["tool", "screen", "📸 Phone help"], ["tool", "scam", "🛡️ Scam check"], ["go-hash", "khata", "📒 Khata"], ["go-hash", "care", "👨‍👩‍👧 Family"]]
      .map(([a, v, l]) => `<button class="chip" data-act="${a}" data-v="${v}">${l}</button>`).join("")}</div>`;
    return out;
  },
  itemActions(i, dark) {
    if (i.done_at) return `<div class="small" style="margin-top:6px">✅ Done</div>`;
    const acts = ACTIONS[i.rkind || "other"] || ACTIONS.other;
    return `<div class="row" style="gap:6px;flex-wrap:wrap;margin-top:8px">${acts.map(([a, l]) => `<button class="btn sm ${dark ? "dark" : "ghost"}" data-act="item-do" data-id="${i.id}" data-v="${a}">${l}</button>`).join("")}</div>`;
  },
  meCards() {
    const { S, esc } = M;
    return `<h2 class="sec"><span>Make Mindy yours</span></h2><div class="card">
      <label class="row" style="justify-content:space-between"><span><b>Simple mode</b><br><span class="small muted">Big buttons and voice. Great for parents.</span></span>
        <input type="checkbox" data-act-change="simple" ${S.me.simple ? "checked" : ""} style="width:24px;height:24px"></label>
      <label class="row" style="justify-content:space-between;margin-top:14px"><span><b>Friend matches</b><br><span class="small muted">When you and a friend save similar places or dishes, suggest doing it together.</span></span>
        <input type="checkbox" data-act-change="share_matches" ${S.me.share_matches ? "checked" : ""} style="width:24px;height:24px"></label>
      <form class="inline-form" data-form="upi" style="margin:14px 0 0"><input class="field" name="upi" value="${esc(S.me.upi || "")}" placeholder="your UPI ID (name@okaxis)" aria-label="Your UPI ID"><button class="btn sm">Save</button></form>
      <div class="small muted">Used for tap-to-pay links in your khata reminders.</div>
      <div class="row" style="gap:8px;margin-top:14px;flex-wrap:wrap"><a class="btn sm ghost" href="#care">👨‍👩‍👧 Family care</a><a class="btn sm ghost" href="#khata">📒 Khata</a><button class="btn sm ghost" data-act="tool" data-v="privacy">🔒 Privacy check-up</button></div></div>`;
  },

  // ---------------------------------------------------------------- family care
  async care(v) {
    const { esc, api, mindy } = M;
    v.innerHTML = `<div class="empty">${mindy("love", 90)}</div>`;
    const F = await api("/family");
    v.innerHTML = `<header class="row"><a class="icon-btn" href="#now" aria-label="Back">←</a><div class="grow"><div class="eyebrow">Look after each other</div><h1 class="big" style="font-size:40px">Family</h1></div></header>
      ${F.members.length ? "" : `<div class="sticker" style="margin-top:16px"><div class="eyebrow">Start here</div><h3>Link with Mum, Dad or anyone you look after.</h3>
        <p>They don't need the app: they just send one WhatsApp message. Then you can set gentle reminders (medicine, water, walks), they tap “I took it”, and you're told if they miss one.</p></div>`}
      <div class="card"><div class="row"><div class="grow"><b>Add family</b><div class="small muted">Get a code and send it to them.</div></div><button class="btn sm g" data-act="fam-code">Get code</button></div><div id="famcode"></div>
        <form class="inline-form" data-form="famjoin" style="margin:12px 0 0"><input class="field" name="code" inputmode="numeric" placeholder="Got a code? Type it" aria-label="Family code"><button class="btn sm">Join</button></form></div>
      ${F.members.length ? `<form class="card" data-form="care"><b>New care reminder</b>
        <select class="field" name="member" style="margin-top:10px" aria-label="For">${F.members.map(m => `<option value="${m.id}">${esc(m.name || "Family")}</option>`).join("")}</select>
        <input class="field" name="text" placeholder="BP tablet · drink water · evening walk" style="margin-top:8px" required aria-label="What">
        <input class="field" name="when" placeholder="every day 9am" style="margin-top:8px" required aria-label="When">
        <p class="small muted" style="margin:8px 0 0">Their time zone is used. Mindy never gives medical advice; it only reminds and tells you.</p>
        <button class="btn g block" style="margin-top:10px">Set it</button></form>` : ""}
      ${F.today.map(c => `<h2 class="sec"><span>${esc(c.member.name)}</span></h2><div class="card">${c.doses.map(d => `<div class="list-item">
        <span style="font-size:22px">${{ taken: "✅", missed: "⚠️", waiting: "⏳", upcoming: "💊" }[d.state]}</span>
        <div class="grow"><div class="t">${esc(d.text)}</div><div class="s">${esc(M.fmtWhen(d.due_at))} · ${esc(d.state)}${d.repeat ? " · " + esc(d.repeat) : ""}</div></div>
        ${c.member.name === "You" && (d.state === "waiting" || d.state === "missed") ? `<button class="btn sm g" data-act="took" data-id="${d.id}">I took it</button>` : ""}
        ${d.reminder && c.member.name !== "You" ? `<button class="icon-btn" data-act="care-del" data-id="${d.reminder}" aria-label="Stop">×</button>` : ""}</div>`).join("")}</div>`).join("")}`;
  },

  // ---------------------------------------------------------------- khata
  async khata(v) {
    const { esc, api, mindy } = M;
    const K = await api("/khata");
    v.innerHTML = `<header class="row"><a class="icon-btn" href="#now" aria-label="Back">←</a><div class="grow"><div class="eyebrow">Who owes what</div><h1 class="big" style="font-size:40px">Khata</h1></div></header>
      <div class="sticker" style="margin-top:16px"><div class="eyebrow">Net</div><h3>${K.net >= 0 ? "You get" : "You pay"} ₹${Math.abs(K.net).toLocaleString("en-IN")}</h3>
        <p>Type it like you'd say it. Works on WhatsApp too.</p></div>
      <form class="inline-form" data-form="khata"><input class="field" name="text" placeholder="Ramesh owes me 500 · paid Sunil 300" required aria-label="New entry"><button class="btn g">Add</button></form>
      ${!K.upi ? `<p class="small muted">Add your UPI ID in <a class="link" href="#me">Me</a> and reminders include a tap-to-pay link.</p>` : ""}
      <div class="card">${K.people.length ? K.people.map(p => `<div class="list-item">${M.avatar({ id: p.person.length, name: p.person }, "sm")}
        <div class="grow"><div class="t">${esc(p.person)}</div><div class="s" style="color:${p.balance > 0 ? "var(--green)" : "var(--red)"}">${p.balance > 0 ? `owes you ₹${p.balance.toLocaleString("en-IN")}` : `you owe ₹${(-p.balance).toLocaleString("en-IN")}`}</div></div>
        ${p.balance > 0 ? `<button class="btn sm" data-act="khata-remind" data-v="${esc(p.person)}">Remind</button>` : ""}</div>`).join("")
        : `<div class="empty">${mindy("happy", 90)}<p>All settled. Nobody owes anybody.</p></div>`}</div>
      ${K.recent.length ? `<h2 class="sec"><span>History</span></h2><div class="card">${K.recent.map(r => `<div class="list-item"><div class="grow"><div class="t">${esc(r.note || r.person)}</div><div class="s">${esc(M.ago(r.created_at))}</div></div><span class="pill">${r.delta > 0 ? "+" : ""}${r.delta}</span></div>`).join("")}</div>` : ""}`;
  },

  // ---------------------------------------------------------------- simple mode (for parents)
  async simple(v) {
    const { esc, api, mindy, S } = M;
    let H = {}; try { H = await api("/home"); } catch (_) {}
    const mine = (H.care || []).find(c => c.member.name === "You");
    const open = mine ? mine.doses.filter(d => d.state === "waiting" || d.state === "missed") : [];
    const big = "display:flex;align-items:center;gap:16px;width:100%;padding:22px;border-radius:26px;font-size:24px;font-weight:800;margin-bottom:14px;text-align:left";
    v.innerHTML = `<header class="top"><div><div class="eyebrow g">${esc(new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }))}</div>
      <h1 class="big" style="font-size:52px">Hello <i>${esc((S.me.name || "").split(" ")[0])}</i></h1></div><a href="#me" aria-label="Settings">${M.avatar(S.me, "ring")}</a></header>
      <div style="margin-top:20px">
      ${open.map(d => `<button style="${big};background:var(--green);color:#000" data-act="took" data-id="${d.id}">💊<span>I took ${esc(d.text)}</span></button>`).join("")}
      <button style="${big};background:var(--cream);color:#000" data-act="tool" data-v="screen">📸<span>Help me with my phone</span></button>
      <button style="${big};background:var(--cream);color:#000" data-act="tool" data-v="scam">🛡️<span>Is this a scam?</span></button>
      <button style="${big};background:var(--cream);color:#000" data-act="tool" data-v="ride">🚕<span>Book a ride</span></button>
      <a style="${big};background:#1A2024;color:var(--cream);text-decoration:none" href="#care">👨‍👩‍👧<span>My family</span></a>
      <button style="${big};background:#1A2024;color:var(--cream)" data-act="think">💬<span>Tell Mindy anything</span></button></div>
      <p class="small muted" style="text-align:center">Turn off Simple mode in <a class="link" href="#me">settings</a>.</p>`;
  },

  // ---------------------------------------------------------------- tool sheets
  tool(kind) {
    const { sheet, esc, mindy } = M;
    const upload = (label) => `<label class="btn g block" style="margin-top:12px;cursor:pointer">${label}<input type="file" name="shot" accept="image/*" hidden></label>`;
    const T = {
      screen: `<div class="row">${mindy("think", 64)}<div><h3>Help with my phone</h3><p class="small muted" style="margin:0">Take a screenshot of the app you're stuck in, and ask.</p></div></div>
        <form data-form="screen" style="margin-top:12px"><input type="hidden" name="mode" value="help"><input class="field" name="question" placeholder="Where do I type the address?" aria-label="Your question">${upload("📸 Choose screenshot")}</form><div id="toolout"></div>`,
      privacy: `<div class="row">${mindy("cool", 64)}<div><h3>Privacy check-up</h3><p class="small muted" style="margin:0">Find out which apps use your mic, camera and location.</p></div></div>
        <ol class="small" style="line-height:1.7;color:var(--soft)"><li><b>iPhone:</b> Settings → Privacy &amp; Security → App Privacy Report (turn it on if asked).</li>
        <li><b>Android:</b> Settings → Security &amp; privacy → Privacy → Privacy dashboard.</li><li>Take a screenshot and add it here.</li></ol>
        <form data-form="screen"><input type="hidden" name="mode" value="privacy"><input type="hidden" name="question" value="">${upload("📸 Choose screenshot")}</form><div id="toolout"></div>`,
      scam: `<div class="row">${mindy("wow", 64)}<div><h3>Is this a scam?</h3><p class="small muted" style="margin:0">Paste the message, link or phone number.</p></div></div>
        <form data-form="check" style="margin-top:12px"><textarea class="field" name="text" placeholder="Dear customer, your account will be blocked…" required aria-label="Message"></textarea><button class="btn g block" style="margin-top:10px">Check it</button></form><div id="toolout"></div>`,
      homework: `<div class="row">${mindy("proud", 64)}<div><h3>Homework help</h3><p class="small muted" style="margin:0">Mindy explains the method, then you finish it. That's how it sticks.</p></div></div>
        <form data-form="homework" style="margin-top:12px"><textarea class="field" name="text" placeholder="Solve 2x + 5 = 17" aria-label="Question"></textarea>${upload("📸 Or add a photo of the question")}<button class="btn block" style="margin-top:10px">Help me</button></form><div id="toolout"></div>`,
      ride: `<div class="row">${mindy("happy", 64)}<div><h3>Book a ride</h3><p class="small muted" style="margin:0">Where to? Mindy opens Uber with it filled in.</p></div></div>
        <form data-form="ride" style="margin-top:12px"><input class="field" name="dest" placeholder="Phoenix Mall, Lower Parel" required aria-label="Where to"><button class="btn g block" style="margin-top:10px">Get my ride</button></form><div id="toolout"></div>`,
      khata: null
    };
    if (kind === "khata") { M.closeSheet(); location.hash = "khata"; return; }
    sheet(T[kind] || T.screen);
  },

  google(el) {
    const id = M.S.cfg.google_client_id; if (!id) return;
    const s = document.createElement("script"); s.src = "https://accounts.google.com/gsi/client"; s.async = true;
    s.onload = () => {
      google.accounts.id.initialize({ client_id: id, callback: async r => {
        try {
          const out = await M.api("/auth/google", { body: { credential: r.credential, tz: Intl.DateTimeFormat().resolvedOptions().timeZone } });
          M.store.set("mindy_token", out.token); location.reload();
        } catch (e) { M.fail(e); }
      } });
      google.accounts.id.renderButton(el, { theme: "filled_black", size: "large", shape: "pill", text: "continue_with" });
    };
    document.head.appendChild(s);
  }
};
window.MPV = V;

window.MindyPower = (m) => {
  M = m;
  const { ACT, FORM, api, toast, fail, esc, route, S } = M;
  const out = html => { const o = document.getElementById("toolout"); if (o) o.innerHTML = html; };
  Object.assign(ACT, {
    tool(el) { V.tool(el.dataset.v); },
    "go-hash"(el) { location.hash = el.dataset.v; },
    async "item-do"(el) {
      const a = el.dataset.v, id = el.dataset.id;
      if (a === "go") {
        if (!S.friends.length) { try { S.friends = await api("/friends"); } catch (_) {} }
        M.sheet(`<h3>Who's coming?</h3><form data-form="itemgo" data-id="${id}"><div class="chips" style="flex-wrap:wrap;margin:8px 0 0;padding:0">${S.friends.map(f => `<label class="chip"><input type="checkbox" name="with" value="${f.id}" style="margin-right:6px">${esc(f.name || "Friend")}</label>`).join("") || '<p class="small muted">No friends yet. It\'ll be a solo plan.</p>'}</div>
          <input class="field" name="when" placeholder="Saturday 1pm" style="margin-top:12px" aria-label="When"><button class="btn g block" style="margin-top:12px">Make the plan</button></form>`);
        return;
      }
      try {
        const r = await api(`/items/${id}/do`, { body: { action: a } });
        if (r.quiz && r.quiz.questions && r.quiz.questions.length) return V.quiz(r.quiz);
        toast("Done ✨", r.reply.replace(/\*/g, "")); route();
      } catch (e) { fail(e); }
    },
    async "match-go"(el) { try { const r = await api(`/items/${el.dataset.id}/do`, { body: { action: "go", people: [Number(el.dataset.friend)] } }); toast("Plan made 👯", r.reply.replace(/\*/g, "")); route(); } catch (e) { fail(e); } },
    async took(el) { try { await api(`/care/${el.dataset.id}/took`, { body: {} }); toast("Thank you ✅", "Your family can see it."); speak("Thank you. Noted."); route(); } catch (e) { fail(e); } },
    async "care-del"(el) { try { await api(`/care/${el.dataset.id}`, { method: "DELETE" }); route(); } catch (e) { fail(e); } },
    async "fam-code"() {
      try { const r = await api("/family/code", { body: {} });
        document.getElementById("famcode").innerHTML = `<div class="did" style="flex-direction:column;align-items:flex-start"><div>Code: <b style="font-size:22px;letter-spacing:.2em">${esc(r.code)}</b> (7 days)</div>
          <div class="small muted">They can send <b>family ${esc(r.code)}</b> to Mindy on WhatsApp, or type it in the app.</div>
          <a class="btn sm g" href="https://wa.me/?text=${encodeURIComponent(`Let's link on Mindy so I can send you gentle reminders 💚 Tap this and press send: ${r.whatsapp}`)}" target="_blank" rel="noopener">Send it on WhatsApp</a></div>`;
      } catch (e) { fail(e); }
    },
    async "khata-remind"(el) {
      try { const r = await api("/khata/remind", { body: { person: el.dataset.v } }); window.open(r.whatsapp, "_blank", "noopener"); } catch (e) { fail(e); }
    },
    async "report-it"(el) { try { await api("/report", { body: { text: el.dataset.v } }); toast("Reported 🙏", "Everyone on Mindy will be warned."); } catch (e) { fail(e); } }
  });
  Object.assign(FORM, {
    async itemgo(f) {
      const people = [...f.querySelectorAll('[name="with"]:checked')].map(i => Number(i.value));
      const r = await api(`/items/${f.dataset.id}/do`, { body: { action: "go", people, when: f.when.value.trim() || undefined } });
      M.closeSheet(); toast("Plan made 👯", r.reply.replace(/\*/g, "")); route();
    },
    async famjoin(f) { await api("/family/join", { body: { code: f.code.value.trim() } }); toast("Linked 👨‍👩‍👧"); route(); },
    async care(f) {
      const r = await api("/care", { body: { member: Number(f.member.value), text: f.text.value.trim(), when: f.when.value.trim() } });
      toast("Set 💊", `${r.text} · ${M.fmtWhen(r.due_at)}${r.repeat ? " · " + r.repeat : ""}`); route();
    },
    async khata(f) { const r = await api("/khata", { body: { text: f.text.value.trim() } }); toast("Noted 📒", r.line); route(); },
    async upi(f) { S.me = Object.assign(S.me, await api("/me", { method: "PATCH", body: { upi: f.upi.value.trim() } })); toast("Saved 💸"); },
    async check(f) {
      const r = await api("/check", { body: { text: f.text.value.trim() } });
      out(`<div class="sticker" style="margin-top:14px;background:${r.verdict === "scam" ? "#FFB8B8" : r.verdict === "careful" ? "#FFE29A" : "var(--cream)"}"><p style="white-space:pre-wrap;font-size:16px">${esc((r.reply || "").replace(/\*/g, ""))}</p>
        ${r.verdict !== "ok" ? `<button class="btn dark" style="margin-top:10px" data-act="report-it" data-v="${esc(f.text.value.trim())}">Report it to protect others</button>` : ""}</div>`);
      if (S.me.simple) speak((r.reply || "").replace(/\*/g, "").split("\n")[0]);
    },
    async ride(f) {
      const r = await api("/doit", { body: { text: "book an uber to " + f.dest.value.trim() } });
      out(`<div class="sticker" style="margin-top:14px"><p>${esc(r.reply.replace(/\*/g, ""))}</p>${r.links.map(([l, u]) => `<a class="btn dark" style="margin:10px 8px 0 0" href="${esc(u)}" target="_blank" rel="noopener">${esc(l)}</a>`).join("")}</div>`);
    },
    async homework(f) {
      const file = f.querySelector('input[type=file]').files[0];
      const image = file ? await fileToDataURL(file, 1400) : undefined;
      out(`<div class="empty">${M.mindy("think", 70)}<p>Thinking…</p></div>`);
      const r = await api("/homework", { body: { text: f.text.value.trim(), image } });
      out(`<div class="sticker" style="margin-top:14px"><div class="eyebrow">Mindy, your study buddy</div><p style="white-space:pre-wrap">${esc(r.answer)}</p></div>`);
    },
    async screen(f) {
      const file = f.querySelector('input[type=file]').files[0];
      if (!file) return toast("Add a screenshot first");
      out(`<div class="empty">${M.mindy("think", 70)}<p>Looking at your screen…</p></div>`);
      const r = await api("/screen-help", { body: { image: await fileToDataURL(file), question: f.question.value.trim(), mode: f.mode.value } });
      out(`${r.image ? `<img src="${r.image}" alt="Your screenshot with a circle where to tap" style="width:100%;border-radius:18px;margin-top:14px">` : ""}
        <div class="sticker" style="margin-top:14px"><div class="eyebrow">Next step</div><h3 style="font-size:26px">${esc(r.step)}</h3>
        <p class="small">Do this, then add the next screenshot.</p></div>`);
      speak(r.step);
    }
  });
  // auto-submit screenshot forms when a file is picked
  document.addEventListener("change", ev => {
    const i = ev.target;
    if (i.matches('form[data-form="screen"] input[type=file]')) i.form.requestSubmit();
    if (i.dataset && (i.dataset.actChange === "simple" || i.dataset.actChange === "share_matches")) {
      api("/me", { method: "PATCH", body: { [i.dataset.actChange]: i.checked } }).then(me => { Object.assign(S.me, me); toast("Saved"); }).catch(fail);
    }
  });
};

V.quiz = (q) => {
  const { esc } = M;
  M.sheet(`<h3>${esc(q.title || "Quiz")}</h3>${q.questions.map((x, n) => `<div class="card"><b>${n + 1}. ${esc(x.q)}</b>
    ${x.options.map((o, i) => `<button class="did" style="width:100%" onclick="this.style.background='${i === x.answer ? "#0E3B2A" : "#3B0E0E"}';this.parentElement.querySelector('.why').hidden=false">${esc(o)}</button>`).join("")}
    <p class="why small muted" hidden>${esc(x.why || "")}</p></div>`).join("")}`);
};
})();
