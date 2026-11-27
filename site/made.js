// Made with Via (made.via.computer, site/made.py): the orders, the search, the layers' dropdown, the
// filters, each card's pictures and its menu, the likes, logging in with GitHub, and a person's own
// boards: adding 1, and hiding, checking again, editing or taking down theirs. The boards' facts are
// in each card's data-*; the likes, the account and the boards people added come from /api/auth and
// /api/made (site/api/_made.js). Without this script the page shows the examples in the repository's
// order; without the API it shows them with no likes and no Log In. Log In opens a dialog with a
// button for each way in the API offers: Google, Microsoft and GitHub. Adding a board asks for GitHub.
//
// A board's page (made.via.computer/b/<name>, [data-thing]) has the same bar, and its own parts: the
// pictures with their arrows and thumbnails, the tabs, the like and share buttons, and the Order
// menu, whose Gerbers show once the check workflow has made them. A board someone added has 1 page,
// which this script fills from /api/made by the name in the address.
//
// A person's profile (made.via.computer/u/<id>, [data-profile]) has the same bar too: this script
// fills it from /api/made?do=profile with their picture, name, line, boards and likes; on their own
// profile they edit their name and line and manage their boards.
(() => {
  // The gallery's grid, or a board page's "More boards"; a profile has grids of its own.
  const grid = document.querySelector("[data-grid]") || document.createElement("div");
  const none = document.querySelector("[data-none]");
  const search = document.querySelector("[data-search]");
  const field = search?.querySelector("input");
  const layers = document.querySelector("[data-layers]");
  const panel = document.getElementById("made-panel");
  const filters = document.querySelector(".made-filters");
  const addDialog = document.getElementById("made-add");
  const addForm = addDialog?.querySelector("[data-add-form]");
  const mineDialog = document.getElementById("made-mine");
  const state = { sort: "likes", q: "", category: "", layers: "", multi: false };
  const thingBox = document.querySelector("[data-thing]");
  const onBoard = Boolean(thingBox);
  const profileBox = document.querySelector("[data-profile]");
  // On a page that is not the gallery, the bar's categories and search lead to the gallery.
  const away = onBoard || Boolean(profileBox);
  const me = { configured: false, providers: [], user: null, admin: false, liked: new Set() };

  const cards = () => [...grid.querySelectorAll(".thing")];
  const num = (card, key) => Number(card.dataset[key]) || 0;
  const press = (selector, on) => {
    for (const b of document.querySelectorAll(selector)) b.setAttribute("aria-pressed", String(on(b)));
  };
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  const show = () => {
    const key = state.sort;
    const order = cards().sort((a, b) => num(b, key) - num(a, key) || num(a, "order") - num(b, "order"));
    let shown = 0;
    for (const card of order) {
      const fits =
        (!state.q || card.dataset.text.includes(state.q)) &&
        (!state.category || card.dataset.category === state.category) &&
        (!state.layers || card.dataset.layers === state.layers) &&
        (!state.multi || num(card, "boards") > 1);
      card.hidden = !fits;
      shown += fits ? 1 : 0;
      grid.append(card);
    }
    if (none) none.hidden = shown > 0;
    press("[data-sort]", (b) => b.dataset.sort === state.sort);
    press("[data-category]", (b) => b.dataset.category === state.category);
    press("[data-multi]", () => state.multi);
    if (layers) layers.value = state.layers;
  };

  const closeMenus = (except) => {
    for (const open of document.querySelectorAll("details.made-drop[open], details.thing-more[open]")) {
      if (open !== except) open.open = false;
    }
  };

  // ---------------------------------------------------------------- the API

  const api = async (path, body) => {
    const response = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: body ? { "content-type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
    });
    let data = {};
    try {
      data = await response.json();
    } catch {}
    if (!response.ok) throw new Error(data.error || "That didn't go through. Could you try again?");
    return data;
  };

  // The Log In dialog: a button for each way in the API offers, each back to `next`. `github` alone is
  // for adding a board, which comes from the person's own repository on GitHub.
  const login = (next = location.pathname + location.search, githubOnly = false) => {
    const dialog = document.getElementById("made-login");
    if (!dialog || !me.configured) return;
    for (const a of dialog.querySelectorAll("[data-with]")) {
      const way = a.dataset.with;
      a.hidden = !me.providers.includes(way) || (githubOnly && way !== "github");
      a.href = `/api/auth?do=login&with=${way}&next=${encodeURIComponent(next)}`;
    }
    for (const open of document.querySelectorAll("dialog[open]")) if (open !== dialog) open.close();
    if (!dialog.open) dialog.showModal();
  };

  // ---------------------------------------------------------------- likes

  const setLikes = (id, count, liked) => {
    for (const card of grid.querySelectorAll(`.thing[data-id="${CSS.escape(id)}"]`)) card.dataset.likes = String(count);
    for (const button of document.querySelectorAll(`[data-like="${CSS.escape(id)}"]`)) {
      button.setAttribute("aria-pressed", String(liked));
      const shown = button.querySelector("[data-count]");
      if (shown) shown.textContent = String(count);
    }
  };

  const like = async (button) => {
    if (!me.configured) return;
    if (!me.user) return login(location.pathname + location.search);
    const id = button.dataset.like;
    if (!id) return;
    const liked = !me.liked.has(id);
    const before = Number(button.querySelector("[data-count]")?.textContent) || 0;
    setLikes(id, Math.max(0, before + (liked ? 1 : -1)), liked);
    try {
      const answer = await api("/api/made?do=like", { board: id, like: liked });
      if (answer.liked) me.liked.add(id);
      else me.liked.delete(id);
      setLikes(id, answer.count, answer.liked);
    } catch {
      setLikes(id, before, !liked);
    }
  };

  // ---------------------------------------------------------------- boards people added

  // The marks of a card the page drew, or of the examples' cards a profile holds in its template.
  const drawn = (selector) =>
    (document.querySelector(selector) || document.querySelector("[data-example-cards]")?.content.querySelector(selector))?.outerHTML;
  const HEART = drawn(".thing-like svg") || "";
  const CHIP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>';
  const KEBAB = drawn(".thing-more summary svg") || "⋮";

  // A GitHub avatar at a size: its address with s= set.
  const sized = (address, size) => {
    try {
      const u = new URL(address);
      u.searchParams.set("s", String(size));
      return u.href;
    } catch {
      return "";
    }
  };

  const sourceUrl = (b) => `https://github.com/${b.repo}/tree/${encodeURIComponent(b.ref)}${b.path === "." ? "" : `/${b.path}`}`;

  const added = (b, order) => {
    const f = b.facts || {};
    const article = document.createElement("article");
    article.className = "thing";
    Object.assign(article.dataset, {
      id: b.id,
      order: String(1000 + order),
      text: [b.name, b.summary, b.category, b.owner.login].join(" ").toLowerCase(),
      category: b.category,
      parts: String(f.parts || 0),
      layers: String(f.layers || 0),
      area: String(f.area || 0),
      boards: String(f.boards || 1),
      likes: "0",
      fresh: String(Date.parse(b.created) || 0),
    });
    const link = `/b/${b.id}`;
    const source = sourceUrl(b);
    const picture = b.picture
      ? `<img src="/api/made?do=picture&amp;id=${esc(b.id)}" alt="" loading="lazy">`
      : `<span class="thing-blank">${CHIP}</span>`;
    article.innerHTML = `
      <div class="thing-pic">
        <a href="${esc(link)}" tabindex="-1" aria-hidden="true">${picture}</a>
        <span class="thing-ok" title="${esc(b.verdict)}"></span>
      </div>
      <div class="thing-head">
        <h2><a href="${esc(link)}">${esc(b.name)}</a></h2>
        <button class="thing-like" type="button" data-like="${esc(b.id)}" aria-pressed="false" aria-label="Like ${esc(b.name)}"><span data-count>0</span>${HEART}</button>
        <details class="thing-more">
          <summary aria-label="More about ${esc(b.name)}">${KEBAB}</summary>
          <ul>
            <li><a href="${esc(link)}">Its page</a></li>
            <li><a href="${esc(source)}">Its files on GitHub</a></li>
            ${b.run ? `<li><a href="${esc(b.run)}">Its check</a></li>` : ""}
            <li><button type="button" data-copy-link="https://made.via.computer/b/${esc(b.id)}">Copy its link</button></li>
          </ul>
        </details>
      </div>
      <div class="thing-by">
        ${b.owner.avatar ? `<img class="thing-face" src="${esc(sized(b.owner.avatar, 80))}" alt="" width="40" height="40">` : `<span class="thing-face" aria-hidden="true">${esc(b.owner.login.slice(0, 2).toUpperCase())}</span>`}
        <a class="thing-maker" href="/u/${esc(b.owner.id)}">${esc(b.owner.login)}</a>
        <span class="thing-state" title="${esc(b.verdict)}"><b>GREEN</b></span>
      </div>`;
    if (b.summary) article.querySelector("h2").title = b.summary;
    return article;
  };

  const load = async () => {
    try {
      const [who, data] = await Promise.all([api("/api/auth"), api("/api/made?do=boards")]);
      Object.assign(me, {
        configured: who.configured,
        providers: who.providers || [],
        user: who.user,
        admin: who.admin,
        liked: new Set(data.liked || []),
      });
      for (const card of cards()) if (num(card, "order") >= 1000) card.remove();
      const here = thingBox?.dataset.thing;
      (data.boards || []).filter((b) => b.id !== here).forEach((b, i) => grid.append(added(b, i)));
      for (const card of cards()) {
        const id = card.dataset.id;
        setLikes(id, (data.likes || {})[id] || 0, me.liked.has(id));
      }
      account();
      show();
      if (onBoard) await board();
      if (profileBox) await profile();
    } catch {
      // No API: the examples stay as the page drew them.
    }
  };

  // ---------------------------------------------------------------- the account

  const account = () => {
    const loginLink = document.querySelector("[data-login]");
    const menu = document.querySelector("[data-me]");
    if (loginLink) loginLink.hidden = !me.configured || Boolean(me.user);
    if (menu) {
      menu.hidden = !me.user;
      const mine = menu.querySelector("[data-my-profile]");
      if (mine && me.user) mine.href = `/u/${encodeURIComponent(me.user.id)}`;
      const avatar = menu.querySelector("[data-avatar]");
      if (me.user && avatar) {
        const src = sized(me.user.avatar, 64);
        if (src) avatar.src = src;
        else avatar.replaceWith(Object.assign(document.createElement("span"), { className: "made-initials", textContent: me.user.login.slice(0, 2).toUpperCase() }));
        avatar.alt = me.user.login;
      }
    }
  };

  const STATES = {
    waiting: "Waiting for its checks",
    checking: "Being checked now",
    red: "Didn't pass its checks",
    error: "Couldn't be checked",
  };
  const stateOf = (b) => {
    if (b.status === "green") return b.hidden ? "Passed, hidden" : b.approved ? "Listed here" : "Passed, waiting for our review";
    return STATES[b.status] || b.status;
  };

  const row = (b, review) => `
    <div class="made-mine-row" data-board="${esc(b.id)}">
      <div>
        <p class="made-mine-name">${esc(b.name)} <small>${esc(b.repo)}${b.path === "." ? "" : `/${esc(b.path)}`} · ${esc(b.ref)}</small></p>
        <p class="made-mine-state" data-status="${esc(b.status)}">${esc(stateOf(b))}${b.verdict && b.status !== "green" ? `: ${esc(b.verdict)}` : ""}${b.run ? ` · <a class="link" href="${esc(b.run)}">its check</a>` : ""}</p>
        ${b.report && b.status !== "green" ? `<details class="made-report"><summary>The gates' report</summary><pre>${esc(b.report)}</pre></details>` : ""}
      </div>
      <div class="made-mine-do">
        ${
          review
            ? `<button type="button" data-approve="${esc(b.id)}">List it</button><button type="button" data-hide="${esc(b.id)}">Hide it</button>`
            : `<button type="button" data-edit="${esc(b.id)}">Edit</button>
               ${b.status === "green" ? `<button type="button" data-${b.hidden ? "show" : "hide"}="${esc(b.id)}">${b.hidden ? "Show" : "Hide"}</button>` : ""}
               ${b.status === "checking" ? "" : `<button type="button" data-recheck="${esc(b.id)}">Check again</button>`}
               <button type="button" class="made-danger" data-remove="${esc(b.id)}">Take down</button>`
        }
      </div>
    </div>`;

  let mineCache = [];
  const openMine = async () => {
    if (!me.user) return login("/#mine");
    const list = mineDialog.querySelector("[data-mine-list]");
    list.innerHTML = "<p class='made-hint'>Loading your boards…</p>";
    if (!mineDialog.open) mineDialog.showModal();
    try {
      const data = await api("/api/made?do=mine");
      mineCache = data.boards;
      list.innerHTML = data.boards.length
        ? data.boards.map((b) => row(b, false)).join("")
        : `<p class="made-hint">You haven't added a board yet. <button type="button" class="made-go" data-open-add>Add your board</button></p>`;
      const review = mineDialog.querySelector("[data-review]");
      review.hidden = !me.admin;
      if (me.admin) {
        const waiting = await api("/api/made?do=review");
        review.querySelector("[data-review-list]").innerHTML = waiting.boards.length
          ? waiting.boards.map((b) => row(b, true)).join("")
          : "<p class='made-hint'>Nothing's waiting for a review.</p>";
      }
    } catch (error) {
      list.innerHTML = `<p class="made-error">${esc(error.message)}</p>`;
    }
  };

  const openAdd = (board) => {
    if (!me.user) return login("/#add-board");
    if (!board && me.user.provider !== "github") return login("/#add-board", true);
    addForm.reset();
    addForm.dataset.edit = board ? board.id : "";
    addDialog.querySelector("[data-add-title]").textContent = board ? `Edit ${board.name}` : "Add your board";
    addDialog.querySelector("[data-add-go]").textContent = board ? "Save it" : "Add it";
    for (const el of addForm.querySelectorAll("[data-source]")) el.hidden = Boolean(board);
    if (board) {
      for (const name of ["name", "summary", "category", "licence"]) addForm.elements[name].value = board[name] || "";
    }
    const error = addForm.querySelector("[data-error]");
    error.hidden = true;
    if (mineDialog.open) mineDialog.close();
    addDialog.showModal();
    addForm.elements[board ? "name" : "repo"].focus();
  };

  addForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = addForm.querySelector("[data-error]");
    const go = addForm.querySelector("[data-add-go]");
    const fields = Object.fromEntries(new FormData(addForm));
    const editing = addForm.dataset.edit;
    go.disabled = true;
    try {
      if (editing) {
        await api("/api/made?do=edit", { id: editing, name: fields.name, summary: fields.summary, category: fields.category, licence: fields.licence });
      } else {
        await api("/api/made?do=add", fields);
      }
      addDialog.close();
      await openMine();
      load();
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
    } finally {
      go.disabled = false;
    }
  });

  const act = async (step, body, confirmText) => {
    if (confirmText && !confirm(confirmText)) return;
    try {
      await api(`/api/made?do=${step}`, body);
      await openMine();
      load();
    } catch (error) {
      alert(error.message);
    }
  };


  // ---------------------------------------------------------------- a board's page

  const stage = () => document.querySelector("[data-stage]");
  const thumbs = () => [...document.querySelectorAll(".made-thumbs button")];

  const pick = (i) => {
    const all = thumbs();
    if (!all.length) return;
    const at = (i + all.length) % all.length;
    all.forEach((b, j) => b.setAttribute("aria-pressed", String(j === at)));
    const img = stage();
    img.src = all[at].dataset.src;
    img.alt = all[at].dataset.alt || "";
    img.removeAttribute("width");
    img.removeAttribute("height");
    const save = document.querySelector("[data-stage-download]");
    if (save) save.href = all[at].dataset.src;
  };

  const step = (by) => {
    const at = thumbs().findIndex((b) => b.getAttribute("aria-pressed") === "true");
    pick(at + by);
  };

  const tab = (button) => {
    for (const t of document.querySelectorAll('[role="tab"]')) {
      const on = t === button;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    }
    button.focus();
  };

  document.addEventListener("keydown", (event) => {
    const current = event.target.closest?.('[role="tab"]');
    if (current && (event.key === "ArrowRight" || event.key === "ArrowLeft")) {
      const all = [...document.querySelectorAll('[role="tab"]')];
      const at = all.indexOf(current) + (event.key === "ArrowRight" ? 1 : -1);
      tab(all[(at + all.length) % all.length]);
    }
    if (onBoard && !event.target.closest?.("input, textarea, select, [role='tab']")) {
      if (event.key === "ArrowRight") step(1);
      if (event.key === "ArrowLeft") step(-1);
    }
  });

  const share = async (button) => {
    const url = button.dataset.share || location.href;
    try {
      if (navigator.share) return await navigator.share({ title: button.dataset.title || document.title, url });
    } catch {
      return;
    }
    navigator.clipboard?.writeText(url).then(() => {
      button.classList.add("made-done");
      button.setAttribute("aria-label", "Link copied");
      setTimeout(() => button.classList.remove("made-done"), 1500);
    }, () => {});
  };

  // The Gerbers show in the Order menu and the Files tab once the check workflow has made them.
  const gerbers = (ready) => {
    for (const el of document.querySelectorAll("[data-gerbers], [data-gerbers-row]")) el.hidden = !ready;
  };

  const RAW = "https://raw.githubusercontent.com/";
  const OSH = "https://oshpark.com/import?url=";
  const OUT_ICON = document.querySelector("[data-osh] svg, .made-order .made-go svg")?.outerHTML || "";

  const fill = (b, files) => {
    const box = document.querySelectorAll("[data-added]");
    for (const el of box) el.hidden = false;
    thingBox.dataset.thing = b.id;
    document.title = `${b.name} · Made with Via`;
    const set = (sel, value) => {
      const el = document.querySelector(sel);
      if (el) el.textContent = value;
    };
    set("[data-name]", b.name);
    set("[data-maker]", b.owner.login);
    set("[data-licence]", b.licence || "No license named");
    set("[data-verdict]", b.verdict || "");
    set("[data-summary]", b.summary || "Its maker didn't write a summary.");
    const avatar = document.querySelector(".made-thing [data-avatar]");
    const face = sized(b.owner.avatar, 80);
    if (avatar && face) avatar.src = face;
    else if (avatar) avatar.replaceWith(Object.assign(document.createElement("span"), { className: "thing-face", textContent: b.owner.login.slice(0, 2).toUpperCase() }));
    for (const el of document.querySelectorAll(".made-rail [data-like]")) el.dataset.like = b.id;
    for (const el of document.querySelectorAll(".made-rail [data-share]")) {
      el.dataset.share = `https://made.via.computer/b/${b.id}`;
      el.dataset.title = b.name;
    }
    const box2 = document.querySelector("[data-stage-box]");
    box2.innerHTML = b.picture
      ? `<img src="/api/made?do=picture&amp;id=${esc(b.id)}" alt="${esc(b.name)}: its drawing" data-stage>`
      : `<span class="thing-blank">${CHIP}</span>`;
    const f = b.facts || {};
    document.querySelector("[data-facts]").innerHTML = [
      ["Boards", f.boards],
      ["Layers", f.layers],
      ["Parts", f.parts],
      ["Area", f.area ? `${f.area.toLocaleString("en-US")} mm²` : ""],
      ["Category", b.category],
    ]
      .filter(([, v]) => v)
      .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`)
      .join("");
    const base = `${b.repo}/${encodeURIComponent(b.ref)}${b.path === "." ? "" : `/${b.path}`}`;
    const kicad = (b.kicad || []).map((k) => ({ name: k.split("/").pop(), raw: `${RAW}${base}/${k}`, view: `https://github.com/${b.repo}/blob/${encodeURIComponent(b.ref)}${b.path === "." ? "" : `/${b.path}`}/${k}` }));
    document.querySelector("[data-osh-list]").innerHTML = kicad.length
      ? kicad.map((k) => `<a class="${kicad.length > 1 ? "made-quiet" : "made-go"}" href="${esc(OSH + encodeURIComponent(k.raw))}" target="_blank" rel="noopener" data-osh>${kicad.length > 1 ? esc(k.name) : "Order at OSH Park"}${OUT_ICON}</a>`).join("")
      : "<small>Its check found no board file.</small>";
    for (const a of document.querySelectorAll("[data-gerbers]")) a.href = `/api/made?do=file&id=${encodeURIComponent(b.id)}&kind=gerbers`;
    const rows = kicad.map((k) => `<tr><td><code>${esc(k.name)}</code></td><td>The board, for KiCad and for OSH Park</td><td class="made-file-do"><a class="made-quiet" href="${esc(k.view)}">View</a><a class="made-quiet" href="${esc(k.raw)}" download>Download</a></td></tr>`);
    if (files.includes("gerbers")) rows.unshift(`<tr><td><code>gerbers.zip</code></td><td>The Gerbers and drill files, made by Via's check, for JLCPCB and PCBWay</td><td class="made-file-do"><a class="made-quiet" href="/api/made?do=file&amp;id=${esc(b.id)}&amp;kind=gerbers" download>Download</a></td></tr>`);
    rows.push(`<tr><td><code>${esc(b.repo)}</code></td><td>Its repository on GitHub</td><td class="made-file-do"><a class="made-quiet" href="${esc(sourceUrl(b))}">View</a></td></tr>`);
    document.querySelector("[data-files]").innerHTML = rows.join("");
    document.querySelector("#tab-files").innerHTML = `Files <span>${rows.length}</span>`;
    document.querySelector("#tab-checks").innerHTML = "Checks";
    set("[data-check-line]", `Via's checks: ${b.verdict || "not run yet"}.`);
    set("[data-report]", b.report || "The report shows here for the board's maker; the check's run is linked from its menu.");
  };

  const board = async () => {
    const id = thingBox.dataset.thing || location.pathname.split("/").filter(Boolean).pop() || "";
    try {
      const data = await api(`/api/made?do=board&id=${encodeURIComponent(id)}`);
      if (data.board) fill(data.board, data.files || []);
      setLikes(id, data.likes || 0, Boolean(data.liked));
      if (data.liked) me.liked.add(id);
      gerbers((data.files || []).includes("gerbers"));
    } catch {
      if ("added" in (document.querySelector("[data-added]")?.dataset || {})) {
        document.querySelector("[data-missing]").hidden = false;
      }
    }
  };


  // ---------------------------------------------------------------- a person's profile

  const profile = async () => {
    const id = decodeURIComponent(location.pathname.split("/").filter(Boolean).pop() || "");
    let data;
    try {
      data = await api(`/api/made?do=profile&id=${encodeURIComponent(id)}`);
    } catch {
      document.querySelector("[data-missing]").hidden = false;
      return;
    }
    const p = data.person;
    document.title = `${p.name} · Made with Via`;
    const set = (sel, value) => {
      const el = document.querySelector(sel);
      if (el) el.textContent = value;
    };
    set("[data-name]", p.name);
    set("[data-bio]", p.bio);
    const joined = Date.parse(p.first);
    set("[data-joined]", joined ? `Joined ${new Date(joined).toLocaleDateString("en-US", { month: "long", year: "numeric" })}` : "");
    const face = document.querySelector("[data-face]");
    const src = sized(p.avatar, 256);
    if (src) {
      face.src = src;
      face.alt = p.name;
      face.hidden = false;
    } else {
      set("[data-initials]", p.name.slice(0, 2).toUpperCase());
      document.querySelector("[data-initials]").hidden = false;
    }
    const gh = document.querySelector("[data-github]");
    if (p.github) {
      gh.href = `https://github.com/${encodeURIComponent(p.github)}`;
      gh.textContent = `@${p.github} on GitHub`;
      gh.hidden = false;
    }
    set("[data-count-boards]", data.counts.boards);
    set("[data-count-likes]", data.counts.likes);
    set("[data-count-received]", data.counts.received);
    document.querySelector("[data-own]").hidden = !data.own;
    profileBox.hidden = false;
    document.querySelector("[data-profile-body]").hidden = false;

    // Their boards: a card for each listed one; on their own profile, each with its state too.
    const mineGrid = document.querySelector("[data-profile-boards]");
    mineGrid.replaceChildren(...data.boards.map((b, i) => {
      const card = added(b, i);
      if (data.own && b.status) {
        const state = card.querySelector(".thing-state");
        state.textContent = stateOf(b);
        state.dataset.status = b.status;
        // The green dot is for a board that passed.
        if (b.status !== "green") card.querySelector(".thing-ok")?.remove();
      }
      return card;
    }));
    // The boards they like: an example's card from the page's template, a board someone added drawn.
    const examples = document.querySelector("[data-example-cards]").content;
    const likedGrid = document.querySelector("[data-profile-likes]");
    likedGrid.replaceChildren(
      ...data.liked.examples.map((i) => examples.querySelector(`.thing[data-id="${CSS.escape(i)}"]`)?.cloneNode(true)).filter(Boolean),
      ...data.liked.boards.map((b, i) => added(b, i)),
    );
    const likedCount = likedGrid.children.length;
    set("[data-tab-boards]", data.boards.length);
    set("[data-tab-likes]", likedCount);
    document.querySelector("[data-empty-boards]").hidden = data.boards.length > 0;
    document.querySelector("[data-empty-likes]").hidden = likedCount > 0;
    me.liked = new Set(data.myLiked || []);
    for (const card of document.querySelectorAll("[data-profile-boards] .thing, [data-profile-likes] .thing")) {
      const cid = card.dataset.id;
      setLikes(cid, data.likes[cid] || 0, me.liked.has(cid));
    }
    // Editing their own name and line.
    const form = document.querySelector("[data-profile-form]");
    if (data.own && form) {
      form.elements.name.value = p.name;
      form.elements.bio.value = p.bio;
    }
  };

  const profileForm = document.querySelector("[data-profile-form]");
  profileForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = profileForm.querySelector("[data-error]");
    try {
      await api("/api/made?do=profile", { name: profileForm.elements.name.value, bio: profileForm.elements.bio.value });
      profileForm.closest("dialog").close();
      await profile();
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
    }
  });

  // ---------------------------------------------------------------- clicks

  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    const inMenu = event.target.closest("details");
    if (!inMenu) closeMenus();
    else if (event.target.closest("summary")) closeMenus(inMenu);
    const cta = event.target.closest(".made-cta");
    if (cta && me.configured) {
      event.preventDefault();
      return openAdd();
    }
    if (!button) return;
    const d = button.dataset;
    if (away && ("category" in d || "multi" in d) && button.closest(".made-bar, .made-panel")) {
      const to = new URLSearchParams();
      if (d.category) to.set("category", d.category);
      if ("multi" in d) to.set("multi", "1");
      location.href = `/${to.size ? `?${to}` : ""}`;
      return;
    }
    if (d.step) return step(Number(d.step));
    if (button.closest(".made-thumbs")) return pick([...button.parentElement.children].indexOf(button));
    if (button.getAttribute("role") === "tab") return tab(button);
    if ("share" in d) return share(button);
    if (d.sort) state.sort = d.sort;
    else if ("category" in d) state.category = d.category;
    else if ("multi" in d) state.multi = !state.multi;
    else if ("reset" in d) {
      Object.assign(state, { sort: "likes", q: "", category: "", layers: "", multi: false });
      if (field) field.value = "";
    } else if (button === filters) {
      const open = panel.hidden;
      panel.hidden = !open;
      filters.setAttribute("aria-expanded", String(open));
      return;
    } else if (button.closest(".thing-dots")) {
      const dots = [...button.parentElement.children];
      const pictures = button.closest(".thing-pic").querySelectorAll("img");
      dots.forEach((dot, i) => {
        dot.setAttribute("aria-pressed", String(dot === button));
        pictures[i].hidden = dot !== button;
      });
      return;
    } else if (d.copyLink) {
      const done = () => {
        const was = button.textContent;
        button.textContent = "Copied!";
        setTimeout(() => {
          button.textContent = was;
          closeMenus();
        }, 1200);
      };
      navigator.clipboard?.writeText(d.copyLink).then(done, () => {});
      return;
    } else if ("like" in d) return like(button);
    else if ("login" in d) return login();
    else if ("editProfile" in d) return document.getElementById("made-profile-edit")?.showModal();
    else if ("openMine" in d) {
      closeMenus();
      return openMine();
    } else if ("openAdd" in d) {
      closeMenus();
      return openAdd();
    } else if ("logout" in d) {
      return api("/api/auth?do=logout", {}).finally(() => location.reload());
    } else if ("close" in d) return button.closest("dialog").close();
    else if (d.edit) return openAdd(mineCache.find((b) => b.id === d.edit));
    else if (d.hide) return act("edit", { id: d.hide, hidden: true });
    else if (d.show) return act("edit", { id: d.show, hidden: false });
    else if (d.recheck) return act("check", { id: d.recheck });
    else if (d.approve) return act("review", { id: d.approve, approved: true });
    else if (d.remove) return act("remove", { id: d.remove }, "Take this board down? Its likes go with it.");
    else return;
    if (button.closest("details")) closeMenus();
    show();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenus();
  });

  search?.addEventListener("submit", (event) => {
    event.preventDefault();
    if (away && field.value.trim()) location.href = `/?q=${encodeURIComponent(field.value.trim())}`;
  });
  field?.addEventListener("input", () => {
    if (away) return;
    state.q = field.value.trim().toLowerCase();
    show();
  });
  layers?.addEventListener("change", () => {
    state.layers = layers.value;
    show();
  });

  const params = new URLSearchParams(location.search);
  const asked = params.get("q");
  if (asked && field && !away) {
    field.value = asked;
    state.q = asked.trim().toLowerCase();
  }
  if (!away) {
    state.category = params.get("category") || "";
    state.multi = params.get("multi") === "1";
  }
  show();
  load().then(() => {
    if (location.hash === "#mine" && me.user) openMine();
    if (location.hash === "#add-board" && me.user) openAdd();
  });
})();
