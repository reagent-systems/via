// Made with Via's accounts, likes and boards (made.via.computer), at the owner's word (2026-11-26):
// "im asking you already to implement it", after "why don't we have a login for people to upload
// their own stuff and manage their own projects" and "why not track likes".
//
// - Sign-in is with Google, Microsoft or GitHub, at the owner's word (2026-11-27: "login with google
//   and login with microsoft and login with github"): each an OAuth app whose id and secret are the
//   project's GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, MICROSOFT_CLIENT_ID and
//   MICROSOFT_CLIENT_SECRET, GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET; a way in with no id and secret
//   is not offered. The provider's token is used once, to read the name and picture, and never kept.
//   A person is 1 account for each way in (`google-<sub>`, `microsoft-<sub>`, `github-<id>`). The
//   session is a cookie signed with a key made from the secrets.
// - Adding a board takes a GitHub login: the board comes from the person's own repository there. An
//   admin is a GitHub login MADE_ADMINS names.
// - A board is added from one of the person's own public GitHub repositories (a link, no upload),
//   checked by Via's gates in GitHub Actions (.github/workflows/made-check.yml), and listed when its
//   gates say GREEN and an admin (MADE_ADMINS) has looked at it: a board's own code runs in its check,
//   so its result is the board's word until someone looks.
// - A like is 1 file for each board and person; the count is the number of files.
// - The check workflow also makes each board's Gerbers, and each example's, in Via's image, for the
//   Order menu of the board's page: JLCPCB and PCBWay take them as 1 zip.
//
// auth.js and made.js give these handlers the Blob store; tests/test_made.py gives them a store of
// its own. Vercel makes no function of a file in api/ whose name starts with "_".
import { createPublicKey, randomBytes, verify as verifySignature, webcrypto } from "node:crypto";
import { gunzipSync } from "node:zlib";

import { EXAMPLES, SOURCES } from "./_examples.js";

const subtle = webcrypto.subtle;
export const ORIGIN = "https://made.via.computer";
export const AUDIENCE = "made.via.computer";
export const WORKFLOW = "reagent-systems/via/.github/workflows/made-check.yml@refs/heads/main";
export const ISSUER = "https://token.actions.githubusercontent.com";
export const SESSION = "made_session";
const STATE = "made_state";
const DAY = 24 * 60 * 60;
export const MOST = { name: 60, summary: 280, licence: 60, report: 20000, verdict: 200, boards: 20, picture: 3_000_000, zip: 4_000_000 };
// The files the check workflow makes for a board, by kind: the Gerbers and drill files JLCPCB and
// PCBWay take, in 1 zip.
export const KINDS = ["gerbers"];
export const CATEGORIES = [
  "Audio",
  "Lighting",
  "Wearables",
  "Dev boards",
  "Motherboards",
  "Alarms",
  "Controllers",
  "Power",
  "Sensors",
  "Radio",
  "Other",
];

// ------------------------------------------------------------------ answers

const json = (body, status = 200, headers = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store", ...headers },
  });
const refuse = (status, error) => json({ error }, status);
const redirect = (location, cookies = []) => {
  const headers = new Headers({ location, "cache-control": "no-store" });
  for (const c of cookies) headers.append("set-cookie", c);
  return new Response(null, { status: 302, headers });
};

const b64url = (bytes) => Buffer.from(bytes).toString("base64url");
const unb64url = (text) => Buffer.from(text, "base64url");

function cookies(request) {
  const out = {};
  for (const part of (request.headers.get("cookie") || "").split(";")) {
    const at = part.indexOf("=");
    if (at > 0) out[part.slice(0, at).trim()] = part.slice(at + 1).trim();
  }
  return out;
}

const cookie = (name, value, maxAge, path = "/") =>
  `${name}=${value}; Path=${path}; Max-Age=${maxAge}; HttpOnly; Secure; SameSite=Lax`;

// A request that changes something comes from a page of the gallery: a browser sends no Lax cookie on
// another site's POST, and an Origin header that names another host is refused too.
function ours(request) {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    const host = new URL(origin).host;
    return host === new URL(request.url).host || host === AUDIENCE;
  } catch {
    return false;
  }
}

// A path on this site to go back to after sign-in: never another host.
export const back = (next) => (typeof next === "string" && /^\/(?![/\\])[A-Za-z0-9/_.#?=&-]*$/.test(next) ? next : "/");

// ------------------------------------------------------------------ the ways in

// Each way in, from its own documents: GitHub's OAuth app endpoints, and Google's and Microsoft's
// OpenID Connect discovery documents (accounts.google.com/.well-known/openid-configuration and
// login.microsoftonline.com/common/v2.0/.well-known/openid-configuration, read 2026-11-27). Only
// the name and picture are asked for: no email. Microsoft's `common` takes personal and work or
// school accounts; its picture needs a token Via does not keep, so a Microsoft account shows its
// initials.
export const PROVIDERS = {
  google: {
    name: "Google",
    authorize: "https://accounts.google.com/o/oauth2/v2/auth",
    token: "https://oauth2.googleapis.com/token",
    profile: "https://openidconnect.googleapis.com/v1/userinfo",
    scope: "openid profile",
    form: true,
    person: (p) => ({ id: String(p.sub || ""), login: String(p.name || p.given_name || "Someone"), avatar: String(p.picture || "") }),
  },
  microsoft: {
    name: "Microsoft",
    authorize: "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    token: "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    profile: "https://graph.microsoft.com/oidc/userinfo",
    scope: "openid profile",
    form: true,
    person: (p) => ({ id: String(p.sub || ""), login: String(p.name || p.given_name || "Someone"), avatar: "" }),
  },
  github: {
    name: "GitHub",
    authorize: "https://github.com/login/oauth/authorize",
    token: "https://github.com/login/oauth/access_token",
    profile: "https://api.github.com/user",
    scope: "",
    form: false,
    person: (p) => ({ id: String(p.id ?? ""), login: String(p.login || ""), avatar: String(p.avatar_url || "") }),
  },
};

// ------------------------------------------------------------------ sessions

async function key(env) {
  const raw = await subtle.importKey("raw", new TextEncoder().encode(env.secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const derived = await subtle.sign("HMAC", raw, new TextEncoder().encode("made.via.computer session"));
  return subtle.importKey("raw", derived, { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

export async function seal(user, env, now) {
  const body = b64url(JSON.stringify({ ...user, exp: Math.floor(now.getTime() / 1000) + 30 * DAY }));
  const mac = await subtle.sign("HMAC", await key(env), new TextEncoder().encode(body));
  return `${body}.${b64url(new Uint8Array(mac))}`;
}

export async function opened(request, env, now) {
  if (!env.secret) return null;
  const value = cookies(request)[SESSION];
  if (!value || !value.includes(".")) return null;
  const [body, mac] = value.split(".");
  let good = false;
  try {
    good = await subtle.verify("HMAC", await key(env), unb64url(mac), new TextEncoder().encode(body));
  } catch {
    return null;
  }
  if (!good) return null;
  try {
    const user = JSON.parse(unb64url(body).toString("utf8"));
    if (typeof user.exp !== "number" || user.exp * 1000 <= now.getTime()) return null;
    if (!(user.provider in PROVIDERS) || !String(user.id).startsWith(`${user.provider}-`)) return null;
    return { id: String(user.id), provider: user.provider, login: String(user.login), avatar: String(user.avatar || "") };
  } catch {
    return null;
  }
}

// An admin is a GitHub login MADE_ADMINS names: a Google or Microsoft name is anyone's to pick.
const isAdmin = (user, env) =>
  Boolean(user) && user.provider === "github" && env.admins.some((a) => a.toLowerCase() === user.login.toLowerCase());

// ------------------------------------------------------------------ sign-in (api/auth.js)

export async function auth(request, ctx) {
  const { env, store, net, now } = ctx;
  const url = new URL(request.url);
  const step = url.searchParams.get("do") || (url.searchParams.has("state") ? "callback" : "me");
  const offered = Object.keys(PROVIDERS).filter((p) => env.providers[p]);
  if (step === "me") {
    const user = await opened(request, env, now);
    return json({ configured: offered.length > 0, providers: offered, user, admin: isAdmin(user, env) });
  }
  if (step === "logout") {
    if (request.method !== "POST") return refuse(405, "Logging out takes a POST.");
    if (!ours(request)) return refuse(403, "That came from another site.");
    return json({ ok: true }, 200, { "set-cookie": cookie(SESSION, "", 0) });
  }
  if (step === "login") {
    const provider = url.searchParams.get("with") || "github";
    const app = env.providers[provider];
    if (!(provider in PROVIDERS)) return refuse(404, "There's no such way to log in.");
    if (!app) return refuse(503, `Logging in with ${PROVIDERS[provider].name} isn't switched on yet.`);
    const way = PROVIDERS[provider];
    const state = b64url(randomBytes(18));
    const next = back(url.searchParams.get("next"));
    const to = new URL(way.authorize);
    to.searchParams.set("client_id", app.id);
    to.searchParams.set("redirect_uri", `${ORIGIN}/api/auth`);
    to.searchParams.set("state", state);
    if (way.scope) {
      to.searchParams.set("response_type", "code");
      to.searchParams.set("scope", way.scope);
    }
    if (provider === "github") to.searchParams.set("allow_signup", "true");
    if (provider === "microsoft") to.searchParams.set("response_mode", "query");
    if (provider === "google") to.searchParams.set("prompt", "select_account");
    return redirect(to.href, [cookie(STATE, `${state}.${provider}.${b64url(next)}`, 600, "/api/auth")]);
  }
  if (step !== "callback") return refuse(404, "There's nothing here.");
  const [state, provider, nextPacked] = (cookies(request)[STATE] || "").split(".");
  const clear = cookie(STATE, "", 0, "/api/auth");
  const said = (status, words) =>
    new Response(words, { status, headers: { "set-cookie": clear, "content-type": "text/plain; charset=utf-8" } });
  if (!state || state !== url.searchParams.get("state") || !(provider in PROVIDERS) || !env.providers[provider]) {
    return said(400, "That sign-in link is old or came from somewhere else. Could you try again?");
  }
  const next = back(nextPacked ? unb64url(nextPacked).toString("utf8") : "/");
  // The person said no, or closed the provider's page: back where they were, not signed in.
  if (url.searchParams.has("error") || !url.searchParams.get("code")) return redirect(next, [clear]);
  const way = PROVIDERS[provider];
  const app = env.providers[provider];
  let person;
  try {
    const fields = {
      client_id: app.id,
      client_secret: app.secret,
      code: url.searchParams.get("code"),
      redirect_uri: `${ORIGIN}/api/auth`,
    };
    const exchanged = await net.fetch(way.token, {
      method: "POST",
      headers: way.form
        ? { accept: "application/json", "content-type": "application/x-www-form-urlencoded" }
        : { accept: "application/json", "content-type": "application/json" },
      body: way.form ? new URLSearchParams({ ...fields, grant_type: "authorization_code" }).toString() : JSON.stringify(fields),
    });
    const { access_token: token } = await exchanged.json();
    if (!token) throw new Error("no token");
    const answer = await net.fetch(way.profile, {
      headers: { authorization: `Bearer ${token}`, accept: "application/json", "user-agent": "made.via.computer" },
    });
    if (!answer.ok) throw new Error(`${way.name} said ${answer.status}`);
    person = way.person(await answer.json());
    if (!/^[A-Za-z0-9_-]{1,100}$/.test(person.id) || !person.login) throw new Error("no person");
  } catch {
    return said(502, `${way.name} didn't let us sign you in. Could you try again?`);
  }
  const user = { id: `${provider}-${person.id}`, provider, login: person.login.slice(0, 80), avatar: person.avatar };
  const known = (await store.get(`made/users/${user.id}.json`)) || { first: now.toISOString() };
  await store.put(`made/users/${user.id}.json`, { ...known, ...user, last: now.toISOString() });
  return redirect(next, [clear, cookie(SESSION, await seal(user, env, now), 30 * DAY)]);
}

// A board's drawing (site/examples.py's draw_board) takes its colours from site.css on the site's
// pages; served by itself it carries these, the explorer's own, with the parts' names hidden.
export const DRAWING_STYLE = `<style>
.edge{fill:oklch(0.22 0.025 250);stroke:oklch(0.85 0.1 90);stroke-width:.25}
.pour{fill:oklch(0.7 0.14 150);fill-opacity:.14;stroke:none}
.pour[data-layer="F.Cu"]{fill:oklch(0.66 0.19 27)}.pour[data-layer="B.Cu"]{fill:oklch(0.68 0.13 250)}
.tracks path{fill:none;stroke-linecap:round;stroke-linejoin:round}
[data-layer="F.Cu"] path{stroke:oklch(0.66 0.19 27)}[data-layer="In1.Cu"] path{stroke:oklch(0.7 0.14 150)}
[data-layer="In2.Cu"] path{stroke:oklch(0.8 0.14 85);stroke-opacity:.85}[data-layer="B.Cu"] path{stroke:oklch(0.68 0.13 250);stroke-opacity:.85}
.vias circle{fill:oklch(0.82 0.08 85);stroke:oklch(0.17 0.02 250);stroke-width:.06}
.part .p,.part .th{fill:oklch(0.83 0.12 85)}.part[data-side="back"] .p{fill:oklch(0.72 0.09 250)}
.part .hole{fill:oklch(0.12 0.01 250)}.refs{display:none}
</style>`;

export const styled = (svg) => svg.replace(/^(\s*<svg\b[^>]*>)/, `$1${DRAWING_STYLE}`);

// ------------------------------------------------------------------ boards (api/made.js)

const text = (value, most) => (typeof value === "string" ? value.trim().slice(0, most) : "");
const REPO = /^([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))\/([A-Za-z0-9._-]{1,100})$/;
const FOLDER = /^(?:\.|[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*)$/;
const REF = /^[A-Za-z0-9._/-]{1,100}$/;

// A repository as a person writes it: owner/name, or its address on GitHub.
export function repository(value) {
  let v = text(value, 300).replace(/\.git$/, "").replace(/\/+$/, "");
  const at = v.match(/^(?:https?:\/\/)?(?:www\.)?github\.com\/(.+)$/i);
  if (at) v = at[1];
  const m = v.match(REPO);
  if (!m || m[2] === "." || m[2] === "..") return null;
  return `${m[1]}/${m[2]}`;
}

export function folder(value) {
  const v = text(value, 200).replace(/^\.\//, "").replace(/\/+$/, "") || ".";
  if (!FOLDER.test(v) || v.split("/").some((part) => part === "..")) return null;
  return v;
}

export function branch(value) {
  const v = text(value, 100);
  if (!v) return "";
  if (!REF.test(v) || v.includes("..") || v.startsWith("/") || v.startsWith("-")) return null;
  return v;
}

const boardPath = (ownerId, id) => `made/boards/${ownerId}/${id}.json`;

async function allBoards(store) {
  const paths = (await store.list("made/boards/")).filter((p) => p.endsWith(".json"));
  const boards = await Promise.all(paths.map((p) => store.get(p)));
  return boards.filter(Boolean);
}

async function findBoard(store, id) {
  if (typeof id !== "string" || !/^[a-z0-9]{6,20}$/.test(id)) return null;
  const path = (await store.list("made/boards/")).find((p) => p.endsWith(`/${id}.json`));
  return path ? store.get(path) : null;
}

const listed = (b) => b.status === "green" && b.approved && !b.hidden;

// What the page shows of a board; its owner and an admin also see its report and state.
function shown(b, full) {
  const out = {
    id: b.id,
    name: b.name,
    summary: b.summary,
    category: b.category,
    licence: b.licence,
    repo: b.repo,
    ref: b.ref,
    path: b.path,
    owner: b.owner,
    created: b.created,
    facts: b.facts || null,
    verdict: b.verdict || "",
    picture: Boolean(b.picture),
    run: b.run || "",
    kicad: b.kicad || [],
  };
  if (full) Object.assign(out, { status: b.status, approved: b.approved, hidden: b.hidden, report: b.report || "", checked: b.checked || "" });
  return out;
}

async function likes(store) {
  const counts = {};
  const by = {};
  for (const p of await store.list("made/likes/")) {
    const [, , board, user] = p.split("/");
    if (!board || !user) continue;
    counts[board] = (counts[board] || 0) + 1;
    (by[user] ||= []).push(board);
  }
  return { counts, by };
}

async function filesOf(store, id) {
  const names = await store.list(`made/files/${id}/`);
  return KINDS.filter((kind) => names.includes(`made/files/${id}/${kind}.zip`));
}

const isExample = (id) => EXAMPLES.includes(id);

async function source(net, repo, ref) {
  // Whether the repository is public and its default branch and licence; GitHub's limit for a caller
  // with no token is soft here: the check finds a missing repository too.
  try {
    const answer = await net.fetch(`https://api.github.com/repos/${repo}`, {
      headers: { accept: "application/vnd.github+json", "user-agent": "made.via.computer" },
    });
    if (answer.status === 404) return { error: "We couldn't find that repository on GitHub. Is it public?" };
    if (!answer.ok) return { ref: ref || "main", licence: "" };
    const info = await answer.json();
    if (info.private) return { error: "That repository is private. Via's checks can only read a public one." };
    return { ref: ref || info.default_branch || "main", licence: info.license?.spdx_id && info.license.spdx_id !== "NOASSERTION" ? info.license.spdx_id : "" };
  } catch {
    return { ref: ref || "main", licence: "" };
  }
}

async function body(request) {
  try {
    const data = await request.json();
    return data && typeof data === "object" ? data : {};
  } catch {
    return {};
  }
}

export async function made(request, ctx) {
  const { env, store, net, now } = ctx;
  const url = new URL(request.url);
  const step = url.searchParams.get("do") || "boards";

  if (step === "queue" || step === "result" || step === "upload") return checks(request, ctx, step);

  if (step === "picture") {
    const id = url.searchParams.get("id") || "";
    if (!/^[a-z0-9]{6,20}$/.test(id)) return refuse(404, "There's no picture here.");
    const svg = await store.getText(`made/pictures/${id}.svg`);
    if (!svg) return refuse(404, "There's no picture here.");
    // A board's drawing comes from its own file: it is shown, never run.
    return new Response(styled(svg), {
      headers: {
        "content-type": "image/svg+xml",
        "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
        "x-content-type-options": "nosniff",
        "cache-control": "public, max-age=300",
      },
    });
  }

  const user = await opened(request, env, now);

  if (step === "board" || step === "file") {
    const id = url.searchParams.get("id") || "";
    let board = null;
    if (!isExample(id)) {
      board = await findBoard(store, id);
      const mine = board && user && (board.owner.id === user.id || isAdmin(user, env));
      if (!board || !(listed(board) || mine)) return refuse(404, "We couldn't find that board.");
    }
    if (step === "file") {
      const kind = url.searchParams.get("kind") || "";
      if (!KINDS.includes(kind)) return refuse(404, "There's no such file.");
      const bytes = await store.getBytes(`made/files/${id}/${kind}.zip`);
      if (!bytes) return refuse(404, "Those files aren't made yet.");
      const name = (board ? board.name : SOURCES[id].name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "board";
      return new Response(bytes, {
        headers: {
          "content-type": "application/zip",
          "content-disposition": `attachment; filename="${name}-${kind}.zip"`,
          "x-content-type-options": "nosniff",
          "cache-control": "public, max-age=300",
        },
      });
    }
    const { counts, by } = await likes(store);
    const mine = Boolean(board && user && (board.owner.id === user.id || isAdmin(user, env)));
    return json({
      id,
      board: board ? shown(board, mine) : null,
      likes: counts[id] || 0,
      liked: Boolean(user && (by[user.id] || []).includes(id)),
      files: await filesOf(store, id),
    });
  }

  if (step === "boards") {
    const [boards, liked] = await Promise.all([allBoards(store), likes(store)]);
    return json({
      boards: boards.filter(listed).map((b) => shown(b, false)),
      likes: liked.counts,
      liked: user ? liked.by[user.id] || [] : [],
    });
  }

  if (request.method !== "POST" && step !== "mine" && step !== "review") return refuse(405, "That takes a POST.");
  if (request.method === "POST" && !ours(request)) return refuse(403, "That came from another site.");
  if (!user) return refuse(401, "You'll need to log in first.");
  const admin = isAdmin(user, env);
  const data = request.method === "POST" ? await body(request) : {};

  if (step === "like") {
    const id = text(data.board, 40);
    const exists = EXAMPLES.includes(id) || (await findBoard(store, id).then((b) => b && listed(b)));
    if (!exists) return refuse(404, "We couldn't find that board.");
    const path = `made/likes/${id}/${user.id}`;
    if (data.like === false) await store.del(path);
    else await store.put(path, { at: now.toISOString() });
    const count = (await store.list(`made/likes/${id}/`)).length;
    return json({ board: id, liked: data.like !== false, count });
  }

  if (step === "mine") {
    const paths = (await store.list(`made/boards/${user.id}/`)).filter((p) => p.endsWith(".json"));
    const mine = (await Promise.all(paths.map((p) => store.get(p)))).filter(Boolean);
    mine.sort((a, b) => (a.created < b.created ? 1 : -1));
    return json({ boards: mine.map((b) => shown(b, true)) });
  }

  if (step === "review") {
    if (!admin) return refuse(403, "Only the gallery's admins can review boards.");
    if (request.method === "GET") {
      const boards = await allBoards(store);
      return json({ boards: boards.filter((b) => b.status === "green" && !b.approved).map((b) => shown(b, true)) });
    }
    const board = await findBoard(store, text(data.id, 20));
    if (!board) return refuse(404, "We couldn't find that board.");
    board.approved = data.approved === true;
    board.reviewed = { by: user.login, at: now.toISOString() };
    await store.put(boardPath(board.owner.id, board.id), board);
    return json({ board: shown(board, true) });
  }

  if (step === "add") {
    if (user.provider !== "github") {
      return refuse(403, "Adding a board takes a GitHub login, since your board comes from your own repository there.");
    }
    const repo = repository(data.repo);
    if (!repo) return refuse(400, "That doesn't look like a GitHub repository. It's owner/name, or its address.");
    if (repo.split("/")[0].toLowerCase() !== user.login.toLowerCase()) {
      return refuse(400, `For now you can add boards from your own repositories, the ones under ${user.login}/.`);
    }
    const path = folder(data.path);
    if (!path) return refuse(400, "That folder doesn't look right. It's a path inside the repository, like boards/my-board.");
    const ref = branch(data.ref);
    if (ref === null) return refuse(400, "That branch name doesn't look right.");
    const name = text(data.name, MOST.name);
    if (!name) return refuse(400, "Your board needs a name.");
    const mine = await store.list(`made/boards/${user.id}/`);
    if (mine.length >= MOST.boards) return refuse(400, `You've got ${MOST.boards} boards here, which is our limit for now.`);
    const found = await source(net, repo, ref);
    if (found.error) return refuse(400, found.error);
    const id = randomBytes(8).toString("hex").slice(0, 12);
    const board = {
      id,
      owner: { id: user.id, provider: user.provider, login: user.login, avatar: user.avatar },
      repo,
      ref: found.ref,
      path,
      name,
      summary: text(data.summary, MOST.summary),
      category: CATEGORIES.includes(data.category) ? data.category : "Other",
      licence: text(data.licence, MOST.licence) || found.licence,
      created: now.toISOString(),
      updated: now.toISOString(),
      status: "waiting",
      approved: false,
      hidden: false,
    };
    await store.put(boardPath(user.id, id), board);
    return json({ board: shown(board, true) }, 201);
  }

  // The rest change 1 of the person's own boards; an admin may hide or remove any.
  const board = await findBoard(store, text(data.id, 20));
  if (!board || (board.owner.id !== user.id && !(admin && (step === "remove" || step === "edit")))) {
    return refuse(404, "We couldn't find that board among yours.");
  }
  const at = boardPath(board.owner.id, board.id);

  if (step === "remove") {
    await store.del(at);
    await store.del(`made/pictures/${board.id}.svg`);
    for (const p of await store.list(`made/files/${board.id}/`)) await store.del(p);
    for (const p of await store.list(`made/likes/${board.id}/`)) await store.del(p);
    return json({ removed: board.id });
  }

  if (step === "check") {
    if (board.status === "checking") return refuse(409, "It's being checked right now.");
    Object.assign(board, { status: "waiting", approved: false, updated: now.toISOString() });
    await store.put(at, board);
    return json({ board: shown(board, true) });
  }

  if (step === "edit") {
    if ("name" in data) {
      const name = text(data.name, MOST.name);
      if (!name) return refuse(400, "Your board needs a name.");
      board.name = name;
    }
    if ("summary" in data) board.summary = text(data.summary, MOST.summary);
    if ("category" in data) board.category = CATEGORIES.includes(data.category) ? data.category : "Other";
    if ("licence" in data) board.licence = text(data.licence, MOST.licence);
    if ("hidden" in data) board.hidden = data.hidden === true;
    // A new folder or branch is a new board to check.
    if (("path" in data || "ref" in data) && board.owner.id === user.id) {
      const path = "path" in data ? folder(data.path) : board.path;
      const ref = "ref" in data ? branch(data.ref) : board.ref;
      if (!path) return refuse(400, "That folder doesn't look right.");
      if (ref === null) return refuse(400, "That branch name doesn't look right.");
      if (path !== board.path || (ref && ref !== board.ref)) {
        Object.assign(board, { path, ref: ref || board.ref, status: "waiting", approved: false });
      }
    }
    board.updated = now.toISOString();
    await store.put(at, board);
    return json({ board: shown(board, true) });
  }

  return refuse(404, "There's nothing here.");
}

// ------------------------------------------------------------------ the checks' workflow

// The workflow's job proves itself with GitHub's OIDC token: signed by GitHub's key, for this
// audience, from made-check.yml on main of reagent-systems/via. The job that runs a board's own code
// cannot ask for one (its permissions are {}).
export async function fromWorkflow(request, net, now) {
  const header = request.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : "";
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const head = JSON.parse(unb64url(parts[0]).toString("utf8"));
    const claims = JSON.parse(unb64url(parts[1]).toString("utf8"));
    if (head.alg !== "RS256") return null;
    const keys = await (await net.fetch(`${ISSUER}/.well-known/jwks`)).json();
    const jwk = (keys.keys || []).find((k) => k.kid === head.kid);
    if (!jwk) return null;
    const good = verifySignature("RSA-SHA256", Buffer.from(`${parts[0]}.${parts[1]}`), createPublicKey({ key: jwk, format: "jwk" }), unb64url(parts[2]));
    const s = now.getTime() / 1000;
    if (!good || claims.iss !== ISSUER || claims.aud !== AUDIENCE) return null;
    if (!(claims.exp > s) || (claims.nbf && claims.nbf > s + 60)) return null;
    if (claims.repository !== "reagent-systems/via" || claims.ref !== "refs/heads/main" || claims.workflow_ref !== WORKFLOW) return null;
    return claims;
  } catch {
    return null;
  }
}

const RUN = /^https:\/\/github\.com\/reagent-systems\/via\/actions\/runs\/\d+(?:\/attempts\/\d+)?$/;

async function checks(request, ctx, step) {
  const { store, net, now } = ctx;
  const url = new URL(request.url);
  const claims = await fromWorkflow(request, net, now);
  if (!claims) return refuse(401, "Only Via's check workflow can do that.");
  // A board or an example left taken for 2 hours lost its run: it waits again.
  const stale = now.getTime() - 2 * 60 * 60 * 1000;
  if (step === "queue") {
    const boards = await allBoards(store);
    const next = boards
      .filter((b) => b.status === "waiting" || (b.status === "checking" && Date.parse(b.taken || 0) < stale))
      .sort((a, b) => (a.updated < b.updated ? -1 : 1))[0];
    if (next) {
      Object.assign(next, { status: "checking", taken: now.toISOString() });
      await store.put(boardPath(next.owner.id, next.id), next);
      return json({ board: { id: next.id, repo: next.repo, ref: next.ref, path: next.path } });
    }
    for (const id of EXAMPLES) {
      const meta = (await store.get(`made/files/${id}/meta.json`)) || {};
      const made = meta.version === SOURCES[id].version && (await filesOf(store, id)).length === KINDS.length;
      if (made || (meta.taken && Date.parse(meta.taken) >= stale)) continue;
      await store.put(`made/files/${id}/meta.json`, { ...meta, taken: now.toISOString() });
      return json({ board: { id, repo: "reagent-systems/via", ref: "main", path: SOURCES[id].path, example: true } });
    }
    return json({ board: null });
  }
  if (step === "upload") {
    const id = url.searchParams.get("id") || "";
    const kind = url.searchParams.get("kind") || "";
    if (!KINDS.includes(kind)) return refuse(400, "There's no such kind of file.");
    const meta = isExample(id) ? await store.get(`made/files/${id}/meta.json`) : null;
    const board = isExample(id) ? null : await findBoard(store, id);
    if (!(meta?.taken || board?.status === "checking")) return refuse(409, "That board isn't being checked.");
    const bytes = Buffer.from(await request.arrayBuffer());
    if (bytes.length > MOST.zip) return refuse(413, "That zip is bigger than the site keeps.");
    if (bytes.length < 22 || bytes.readUInt32LE(0) !== 0x04034b50) return refuse(400, "That isn't a zip.");
    await store.putBytes(`made/files/${id}/${kind}.zip`, bytes, "application/zip");
    return json({ id, kind, size: bytes.length });
  }
  const data = await body(request);
  if (isExample(text(data.id, 40))) {
    const id = text(data.id, 40);
    const meta = (await store.get(`made/files/${id}/meta.json`)) || {};
    if (!meta.taken) return refuse(409, "That example isn't being checked.");
    const files = await filesOf(store, id);
    await store.put(`made/files/${id}/meta.json`, {
      version: files.length === KINDS.length ? SOURCES[id].version : meta.version || "",
      verdict: text(data.result?.verdict, MOST.verdict),
      run: RUN.test(data.run || "") ? data.run : "",
      checked: now.toISOString(),
      taken: null,
    });
    return json({ board: id, files });
  }
  const board = await findBoard(store, text(data.id, 20));
  if (!board || board.status !== "checking") return refuse(409, "That board isn't being checked.");
  const result = data.result && typeof data.result === "object" ? data.result : null;
  const verdict = text(result?.verdict, MOST.verdict);
  Object.assign(board, {
    status: !result ? "error" : result.green === true && /^GREEN\b/.test(verdict) ? "green" : verdict ? "red" : "error",
    verdict: verdict || (result ? "" : "The check stopped before it could judge the board."),
    report: text(result?.report, MOST.report),
    run: RUN.test(data.run || "") ? data.run : "",
    checked: now.toISOString(),
    approved: false,
  });
  const f = result?.facts;
  board.facts =
    f && typeof f === "object"
      ? {
          parts: Math.max(0, Math.min(1e6, Number(f.parts) | 0)),
          layers: Math.max(0, Math.min(64, Number(f.layers) | 0)),
          area: Math.max(0, Math.min(1e7, Math.round(Number(f.area) * 10) / 10 || 0)),
          boards: Math.max(0, Math.min(100, Number(f.boards) | 0)),
        }
      : null;
  // Each board file's path in the project's folder, for OSH Park's link on the board's page.
  board.kicad = Array.isArray(result?.kicad)
    ? result.kicad.filter((k) => typeof k === "string" && /^[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)?\.kicad_pcb$/.test(k) && !k.includes("..")).slice(0, 20)
    : [];
  board.picture = false;
  if (typeof result?.picture === "string" && result.picture.length < 1_400_000) {
    try {
      const svg = gunzipSync(Buffer.from(result.picture, "base64"), { maxOutputLength: MOST.picture }).toString("utf8");
      if (/^\s*<svg[\s>]/.test(svg)) {
        await store.putText(`made/pictures/${board.id}.svg`, svg, "image/svg+xml");
        board.picture = true;
      }
    } catch {
      board.picture = false;
    }
  }
  await store.put(boardPath(board.owner.id, board.id), board);
  return json({ board: board.id, status: board.status });
}

// The ways in that have an id and a secret, and the session's key, made from every secret: a way in
// added or taken away signs everyone out once.
export function environment(vars) {
  const providers = {};
  for (const name of Object.keys(PROVIDERS)) {
    const id = vars[`${name.toUpperCase()}_CLIENT_ID`] || "";
    const secret = vars[`${name.toUpperCase()}_CLIENT_SECRET`] || "";
    if (id && secret) providers[name] = { id, secret };
  }
  return {
    providers,
    secret: Object.keys(providers).map((name) => providers[name].secret).join("\n"),
    admins: (vars.MADE_ADMINS || "ThyFriendlyFox").split(",").map((a) => a.trim()).filter(Boolean),
  };
}
