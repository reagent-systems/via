"""Made with Via's accounts, likes and boards (site/api/_made.js) and the result of a board's check
(tools/ci/made_check.py), at the owner's word (2026-11-26): "im asking you already to implement it",
after asking why the gallery had no likes and no login to add and manage boards.

The handlers run in Node with a store in memory, a GitHub that answers as the test says, and a
signing key the test makes, so no test reaches GitHub, Vercel or the Blob store. Each scenario is 1
step of a person's or the workflow's, and the driver prints every answer.
"""

# ruff: noqa: E501 - the driver is JavaScript, with its lines as long as site/api/_made.js's.
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
API = SITE / "api"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node runs the site's functions")

sys.path.insert(0, str(ROOT / "tools" / "ci"))
import made_check  # noqa: E402

DRIVER = r"""
globalThis.crypto ??= (await import("node:crypto")).webcrypto;
const { pathToFileURL } = await import("node:url");
const { generateKeyPairSync, createSign } = await import("node:crypto");
const { gzipSync } = await import("node:zlib");
const m = await import(pathToFileURL(process.env.MADE_API + "/_made.js").href);

// A store in memory with the 6 functions of _store.js.
const files = new Map();
const store = {
  get: async (p) => (files.has(p) ? JSON.parse(files.get(p)) : null),
  getText: async (p) => (files.has(p) ? String(files.get(p)) : null),
  getBytes: async (p) => (files.has(p) ? Buffer.from(files.get(p)) : null),
  put: async (p, v) => void files.set(p, JSON.stringify(v)),
  putText: async (p, v) => void files.set(p, v),
  putBytes: async (p, v) => void files.set(p, v),
  del: async (p) => void files.delete(p),
  list: async (prefix) => [...files.keys()].filter((k) => k.startsWith(prefix)).sort(),
};

// GitHub's OIDC key, made here; the test's tokens are signed with it.
const { publicKey, privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "test-key", alg: "RS256", use: "sig" };
const b64 = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
const token = (claims, key = privateKey) => {
  const head = b64({ alg: "RS256", kid: "test-key", typ: "JWT" });
  const body = b64(claims);
  const sign = createSign("RSA-SHA256");
  sign.update(`${head}.${body}`);
  return `${head}.${body}.${sign.sign(key).toString("base64url")}`;
};
const now = new Date("2026-11-26T12:00:00Z");
const s = Math.floor(now.getTime() / 1000);
const good = {
  iss: m.ISSUER, aud: m.AUDIENCE, exp: s + 300, nbf: s - 10, repository: "reagent-systems/via",
  ref: "refs/heads/main", workflow_ref: m.WORKFLOW,
};

// GitHub, as each scenario wants it.
const people = { a: { id: 101, login: "Alice", name: "Alice A", avatar_url: "https://avatars.githubusercontent.com/u/101?v=4" },
                 b: { id: 202, login: "bob", name: "", avatar_url: "https://avatars.githubusercontent.com/u/202?v=4" },
                 o: { id: 1, login: "ThyFriendlyFox", name: "Owner", avatar_url: "" },
                 // A Google account that calls itself the admin's GitHub login, and a Microsoft one.
                 g: { sub: "1098765432109876543", name: "ThyFriendlyFox", picture: "https://lh3.googleusercontent.com/a/x", email: "g@example.com" },
                 ms: { sub: "AAAAAAAAAAAAAAAAAAAAAK-xyz_123", name: "Mia Soft", preferred_username: "mia@example.com" } };
let who = "a";
const repos = { "Alice/lamp": { private: false, default_branch: "trunk", license: { spdx_id: "CERN-OHL-S-2.0" } },
                "Alice/secret": { private: true } };
const net = {
  fetch: async (url, init = {}) => {
    const u = String(url);
    if (u === "https://github.com/login/oauth/access_token") {
      const sent = JSON.parse(init.body);
      return Response.json(sent.code === "good" ? { access_token: "gho_test" } : { error: "bad_verification_code" });
    }
    if (u === "https://api.github.com/user") return Response.json(people[who]);
    // Google and Microsoft take the code as a form, with grant_type, and answer a profile by `sub`.
    for (const [token, profile, prefix] of [
      ["https://oauth2.googleapis.com/token", "https://openidconnect.googleapis.com/v1/userinfo", "ya29"],
      ["https://login.microsoftonline.com/common/oauth2/v2.0/token", "https://graph.microsoft.com/oidc/userinfo", "eyJ0"],
    ]) {
      if (u === token) {
        const sent = new URLSearchParams(init.body);
        const ok = init.headers["content-type"] === "application/x-www-form-urlencoded" && sent.get("grant_type") === "authorization_code"
          && sent.get("code") === "good" && sent.get("redirect_uri") === "https://made.via.computer/api/auth" && sent.get("client_secret");
        return Response.json(ok ? { access_token: `${prefix}_test`, id_token: "x.y.z" } : { error: "invalid_grant" });
      }
      if (u === profile) {
        if (init.headers.authorization !== `Bearer ${prefix}_test`) return new Response("{}", { status: 401 });
        return Response.json(people[who]);
      }
    }
    if (u.startsWith("https://api.github.com/repos/")) {
      // GitHub finds a repository by its name in any case.
      const asked = u.slice("https://api.github.com/repos/".length).toLowerCase();
      const r = Object.entries(repos).find(([name]) => name.toLowerCase() === asked)?.[1];
      return r ? Response.json(r) : new Response("{}", { status: 404 });
    }
    if (u === `${m.ISSUER}/.well-known/jwks`) return Response.json({ keys: [jwk] });
    throw new Error(`no such address in the test: ${u}`);
  },
};
const env = m.environment({
  GITHUB_CLIENT_ID: "cid", GITHUB_CLIENT_SECRET: "csecret",
  GOOGLE_CLIENT_ID: "gid", GOOGLE_CLIENT_SECRET: "gsecret",
  MICROSOFT_CLIENT_ID: "mid", MICROSOFT_CLIENT_SECRET: "msecret",
  MADE_ADMINS: "ThyFriendlyFox",
});
const ctx = { env, store, net, now };
const sessions = {};

const call = async (handler, method, path, { as, body, origin, bearer, cookie, envOver, bytes } = {}) => {
  const headers = { host: "made.via.computer" };
  if (as) headers.cookie = `${m.SESSION}=${sessions[as]}`;
  if (cookie) headers.cookie = cookie;
  if (origin) headers.origin = origin;
  if (bearer) headers.authorization = `Bearer ${bearer}`;
  if (body !== undefined) headers["content-type"] = "application/json";
  const sent = bytes ?? (body === undefined ? undefined : JSON.stringify(body));
  const request = new Request(`https://made.via.computer${path}`, { method, headers, body: sent });
  const response = await (handler === "auth" ? m.auth : m.made)(request, envOver ? { ...ctx, env: envOver } : ctx);
  const text = await response.text();
  let data = null;
  try { data = JSON.parse(text); } catch {}
  return { status: response.status, data, text, location: response.headers.get("location"),
           cookies: response.headers.getSetCookie?.() || [], headers: Object.fromEntries(response.headers) };
};

const signIn = async (person, way = "github") => {
  who = person;
  const start = await call("auth", "GET", `/api/auth?do=login&with=${way}&next=/%23mine`);
  const state = new URL(start.location).searchParams.get("state");
  const stateCookie = start.cookies.find((c) => c.startsWith("made_state=")).split(";")[0];
  const back = await call("auth", "GET", `/api/auth?code=good&state=${state}`, { cookie: stateCookie });
  sessions[person] = back.cookies.find((c) => c.startsWith(`${m.SESSION}=`)).split(";")[0].slice(m.SESSION.length + 1);
  return { start, back };
};

const out = {};
const step = async (name, fn) => { out[name] = await fn(); };

await step("me_out", () => call("auth", "GET", "/api/auth"));
await step("me_off", () => call("auth", "GET", "/api/auth", { envOver: m.environment({}) }));
await step("login_off", () => call("auth", "GET", "/api/auth?do=login", { envOver: m.environment({}) }));
await step("login", () => call("auth", "GET", "/api/auth?do=login&next=//evil.example/x"));
await step("callback_bad_state", () => call("auth", "GET", "/api/auth?code=good&state=nope", { cookie: "made_state=other.Lw" }));
await step("signin_a", () => signIn("a"));
await step("me_a", () => call("auth", "GET", "/api/auth", { as: "a" }));
await step("me_tampered", () => call("auth", "GET", "/api/auth", { cookie: `${m.SESSION}=${sessions.a.replace(/.$/, (c) => (c === "A" ? "B" : "A"))}` }));
await step("user_a", () => store.get("made/users/github-101.json"));
await signIn("b");
await signIn("o");

// Google and Microsoft: where each login sends the person, who they are after, and what they may do.
await step("login_google", () => call("auth", "GET", "/api/auth?do=login&with=google&next=/b/hush"));
await step("login_microsoft", () => call("auth", "GET", "/api/auth?do=login&with=microsoft"));
await step("login_nowhere", () => call("auth", "GET", "/api/auth?do=login&with=myspace"));
await step("login_google_off", () => call("auth", "GET", "/api/auth?do=login&with=google", { envOver: m.environment({ GITHUB_CLIENT_ID: "c", GITHUB_CLIENT_SECRET: "s" }) }));
await step("me_github_only", () => call("auth", "GET", "/api/auth", { envOver: m.environment({ GITHUB_CLIENT_ID: "c", GITHUB_CLIENT_SECRET: "s" }) }));
await step("signin_g", () => signIn("g", "google"));
await step("signin_ms", () => signIn("ms", "microsoft"));
await step("me_g", () => call("auth", "GET", "/api/auth", { as: "g" }));
await step("me_ms", () => call("auth", "GET", "/api/auth", { as: "ms" }));
await step("user_g", () => store.get("made/users/google-1098765432109876543.json"));
await step("like_g", () => call("made", "POST", "/api/made?do=like", { as: "g", body: { board: "ex-lark" } }));
await step("add_g", () => call("made", "POST", "/api/made?do=add", { as: "g", body: { repo: "ThyFriendlyFox/lamp", name: "Lamp" } }));
await step("review_g", () => call("made", "GET", "/api/made?do=review", { as: "g" }));
// A login the person cancels at the provider: back where they were, with no session.
const cancelStart = await call("auth", "GET", "/api/auth?do=login&with=microsoft&next=/b/lark");
const cancelState = new URL(cancelStart.location).searchParams.get("state");
const cancelCookie = cancelStart.cookies.find((c) => c.startsWith("made_state=")).split(";")[0];
await step("cancelled", () => call("auth", "GET", `/api/auth?error=access_denied&state=${cancelState}`, { cookie: cancelCookie }));
// A state cookie of 1 way in does not finish another's.
const crossStart = await call("auth", "GET", "/api/auth?do=login&with=google");
const crossState = new URL(crossStart.location).searchParams.get("state");
await step("cross", () => call("auth", "GET", `/api/auth?code=good&state=${crossState}`, { cookie: `made_state=${crossState}.myspace.Lw` }));

await step("like_out", () => call("made", "POST", "/api/made?do=like", { body: { board: "ex-hush" } }));
await step("like_a", () => call("made", "POST", "/api/made?do=like", { as: "a", body: { board: "ex-hush" } }));
await step("like_b", () => call("made", "POST", "/api/made?do=like", { as: "b", body: { board: "ex-hush" } }));
await step("like_a_again", () => call("made", "POST", "/api/made?do=like", { as: "a", body: { board: "ex-hush" } }));
await step("unlike_b", () => call("made", "POST", "/api/made?do=like", { as: "b", body: { board: "ex-hush", like: false } }));
await step("like_nothing", () => call("made", "POST", "/api/made?do=like", { as: "a", body: { board: "ex-nothing" } }));
await step("like_other_site", () => call("made", "POST", "/api/made?do=like", { as: "a", origin: "https://evil.example", body: { board: "ex-hush" } }));
await step("boards_a", () => call("made", "GET", "/api/made?do=boards", { as: "a" }));

await step("add_not_mine", () => call("made", "POST", "/api/made?do=add", { as: "a", body: { repo: "bob/lamp", name: "Lamp" } }));
await step("add_bad_repo", () => call("made", "POST", "/api/made?do=add", { as: "a", body: { repo: "not a repo", name: "Lamp" } }));
await step("add_bad_folder", () => call("made", "POST", "/api/made?do=add", { as: "a", body: { repo: "Alice/lamp", path: "../etc", name: "Lamp" } }));
await step("add_private", () => call("made", "POST", "/api/made?do=add", { as: "a", body: { repo: "Alice/secret", name: "Secret" } }));
await step("add_missing", () => call("made", "POST", "/api/made?do=add", { as: "a", body: { repo: "Alice/gone", name: "Gone" } }));
await step("add_no_name", () => call("made", "POST", "/api/made?do=add", { as: "a", body: { repo: "Alice/lamp" } }));
await step("add", () => call("made", "POST", "/api/made?do=add", { as: "a",
  body: { repo: "https://github.com/alice/lamp.git", path: "boards/lamp/", name: " Desk lamp ", summary: "A lamp.", category: "Lighting" } }));
const id = out.add.data.board.id;
await step("boards_before", () => call("made", "GET", "/api/made?do=boards"));
await step("mine_a", () => call("made", "GET", "/api/made?do=mine", { as: "a" }));
await step("mine_b", () => call("made", "GET", "/api/made?do=mine", { as: "b" }));
await step("edit_by_b", () => call("made", "POST", "/api/made?do=edit", { as: "b", body: { id, name: "Mine now" } }));
await step("remove_by_b", () => call("made", "POST", "/api/made?do=remove", { as: "b", body: { id } }));
await step("like_unlisted", () => call("made", "POST", "/api/made?do=like", { as: "b", body: { board: id } }));

await step("queue_no_token", () => call("made", "GET", "/api/made?do=queue"));
await step("queue_other_workflow", () => call("made", "GET", "/api/made?do=queue", { bearer: token({ ...good, workflow_ref: "reagent-systems/via/.github/workflows/ci.yml@refs/heads/main" }) }));
await step("queue_other_audience", () => call("made", "GET", "/api/made?do=queue", { bearer: token({ ...good, aud: "elsewhere" }) }));
await step("queue_old", () => call("made", "GET", "/api/made?do=queue", { bearer: token({ ...good, exp: s - 1 }) }));
await step("queue_fork_branch", () => call("made", "GET", "/api/made?do=queue", { bearer: token({ ...good, ref: "refs/heads/feature" }) }));
const { privateKey: otherKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
await step("queue_other_key", () => call("made", "GET", "/api/made?do=queue", { bearer: token(good, otherKey) }));
await step("queue", () => call("made", "GET", "/api/made?do=queue", { bearer: token(good) }));
await step("queue_empty", () => call("made", "GET", "/api/made?do=queue", { bearer: token(good) }));
await step("result_no_token", () => call("made", "POST", "/api/made?do=result", { body: { id, result: { green: true, verdict: "GREEN" } } }));
const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>';
await step("result", () => call("made", "POST", "/api/made?do=result", { bearer: token(good), body: {
  id, run: "https://github.com/reagent-systems/via/actions/runs/123",
  result: { green: true, verdict: "GREEN with 2 warnings", report: "| ERC | pass | 0 |", facts: { parts: 12, layers: 2, area: 1500.25, boards: 1 },
            kicad: ["lamp.kicad_pcb", "power/power.kicad_pcb", "../escape.kicad_pcb", "a/b/c.kicad_pcb", "notes.txt"],
            picture: gzipSync(svg).toString("base64") } } }));
await step("result_twice", () => call("made", "POST", "/api/made?do=result", { bearer: token(good), body: { id, result: { green: true, verdict: "GREEN" } } }));
await step("board_unlisted_out", () => call("made", "GET", `/api/made?do=board&id=${id}`));
await step("board_unlisted_owner", () => call("made", "GET", `/api/made?do=board&id=${id}`, { as: "a" }));
await step("boards_unreviewed", () => call("made", "GET", "/api/made?do=boards"));
await step("review_by_a", () => call("made", "POST", "/api/made?do=review", { as: "a", body: { id, approved: true } }));
await step("review_list", () => call("made", "GET", "/api/made?do=review", { as: "o" }));
await step("review", () => call("made", "POST", "/api/made?do=review", { as: "o", body: { id, approved: true } }));
await step("boards_listed", () => call("made", "GET", "/api/made?do=boards", { as: "b" }));
await step("like_listed", () => call("made", "POST", "/api/made?do=like", { as: "b", body: { board: id } }));
await step("picture", () => call("made", "GET", `/api/made?do=picture&id=${id}`));
await step("board_listed", () => call("made", "GET", `/api/made?do=board&id=${id}`, { as: "b" }));

// A person's profile: what others see, what they see of their own, and their edit of it.
await step("profile_by_b", () => call("made", "GET", "/api/made?do=profile&id=github-101", { as: "b" }));
await step("profile_out", () => call("made", "GET", "/api/made?do=profile&id=github-101"));
await step("profile_own", () => call("made", "GET", "/api/made?do=profile&id=github-101", { as: "a" }));
await step("profile_unknown", () => call("made", "GET", "/api/made?do=profile&id=github-999"));
await step("profile_bad", () => call("made", "GET", "/api/made?do=profile&id=../made/users/github-101"));
await step("profile_edit_out", () => call("made", "POST", "/api/made?do=profile", { body: { name: "Mallory" } }));
await step("profile_edit_other_site", () => call("made", "POST", "/api/made?do=profile", { as: "a", origin: "https://evil.example", body: { name: "Mallory" } }));
await step("profile_edit", () => call("made", "POST", "/api/made?do=profile&id=github-202", { as: "a", body: { name: "  Alice Anders  ", bio: "b".repeat(400) } }));
await step("profile_after_edit", () => call("made", "GET", "/api/made?do=profile&id=github-101"));
await step("profile_bob_after", () => call("made", "GET", "/api/made?do=profile&id=github-202"));

// The Gerbers: the workflow takes an example when no board waits, uploads its zip, and the page
// offers it; a file the workflow did not make, or from no workflow, is refused.
const zip = Buffer.concat([Buffer.from([0x50, 0x4b, 0x03, 0x04]), Buffer.alloc(40)]);
await step("file_none", () => call("made", "GET", "/api/made?do=file&id=ex-hush&kind=gerbers"));
await step("upload_untaken", () => call("made", "POST", "/api/made?do=upload&id=ex-basalt&kind=gerbers", { bearer: token(good), bytes: zip }));
await step("queue_example", () => call("made", "GET", "/api/made?do=queue", { bearer: token(good) }));
const ex = out.queue_example.data.board?.id;
await step("upload_no_token", () => call("made", "POST", `/api/made?do=upload&id=${ex}&kind=gerbers`, { bytes: zip }));
await step("upload_not_zip", () => call("made", "POST", `/api/made?do=upload&id=${ex}&kind=gerbers`, { bearer: token(good), bytes: Buffer.from("<html>not a zip</html>xxxxxxxxxxxxxxxx") }));
await step("upload_bad_kind", () => call("made", "POST", `/api/made?do=upload&id=${ex}&kind=secrets`, { bearer: token(good), bytes: zip }));
await step("upload", () => call("made", "POST", `/api/made?do=upload&id=${ex}&kind=gerbers`, { bearer: token(good), bytes: zip }));
await step("result_example", () => call("made", "POST", "/api/made?do=result", { bearer: token(good), body: { id: ex, run: "https://github.com/reagent-systems/via/actions/runs/9", result: { green: false, verdict: "", report: "" } } }));
await step("board_example", () => call("made", "GET", `/api/made?do=board&id=${ex}`));
await step("file", () => call("made", "GET", `/api/made?do=file&id=${ex}&kind=gerbers`));
await step("queue_next_example", () => call("made", "GET", "/api/made?do=queue", { bearer: token(good) }));
await step("hide", () => call("made", "POST", "/api/made?do=edit", { as: "a", body: { id, hidden: true } }));
await step("boards_hidden", () => call("made", "GET", "/api/made?do=boards"));
await step("show", () => call("made", "POST", "/api/made?do=edit", { as: "a", body: { id, hidden: false } }));
await step("new_folder", () => call("made", "POST", "/api/made?do=edit", { as: "a", body: { id, path: "boards/lamp2" } }));
await step("boards_rechecking", () => call("made", "GET", "/api/made?do=boards"));
await step("queue_again", () => call("made", "GET", "/api/made?do=queue", { bearer: token(good) }));
await step("result_red", () => call("made", "POST", "/api/made?do=result", { bearer: token(good), body: {
  id, run: "https://evil.example/run", result: { green: true, verdict: "RED: DRC failed", report: "x".repeat(30000), facts: null } } }));
await step("mine_red", () => call("made", "GET", "/api/made?do=mine", { as: "a" }));
await step("check_again", () => call("made", "POST", "/api/made?do=check", { as: "a", body: { id } }));
await step("queue_third", () => call("made", "GET", "/api/made?do=queue", { bearer: token(good) }));
await step("result_stopped", () => call("made", "POST", "/api/made?do=result", { bearer: token(good), body: { id, result: null } }));
await step("mine_error", () => call("made", "GET", "/api/made?do=mine", { as: "a" }));
await step("remove", () => call("made", "POST", "/api/made?do=remove", { as: "a", body: { id } }));
await step("left", () => store.list("made/"));
await step("logout", () => call("auth", "POST", "/api/auth?do=logout", { as: "a" }));
out.parse = {
  repos: ["Alice/lamp", "https://github.com/Alice/lamp", "github.com/Alice/lamp/", "Alice/lamp.git", "Alice", "Alice/..", "a b/c", "-x/y"].map((r) => [r, m.repository(r)]),
  folders: ["", ".", "./", "boards/lamp", "boards/../x", "/abs", "a//b", "a/b/"].map((f) => [f, m.folder(f)]),
  branches: ["", "main", "release/1.0", "a..b", "-x", "/x", "a b"].map((b) => [b, m.branch(b)]),
  back: ["/", "/#mine", "//evil", "https://evil", "/\\evil", "/a?b=c"].map((b) => [b, m.back(b)]),
};
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def run() -> dict:
    if NODE is None:
        pytest.skip("node runs the site's functions")
    proc = subprocess.run(
        [NODE, "--input-type=module", "-e", DRIVER],
        capture_output=True,
        text=True,
        env={**os.environ, "MADE_API": str(API)},
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@needs_node
def test_sign_in_is_github_with_a_state_and_a_signed_session(run):
    assert run["me_out"]["data"] == {
        "configured": True,
        "providers": ["google", "microsoft", "github"],
        "user": None,
        "admin": False,
    }
    assert run["me_off"]["data"]["configured"] is False
    assert run["login_off"]["status"] == 503
    login = run["login"]
    assert login["status"] == 302 and login["location"].startswith(
        "https://github.com/login/oauth/authorize?"
    )
    assert (
        "client_id=cid" in login["location"]
        and "redirect_uri=https%3A%2F%2Fmade.via.computer%2Fapi%2Fauth" in login["location"]
    )
    state = next(c for c in login["cookies"] if c.startswith("made_state="))
    assert "HttpOnly" in state and "Secure" in state and "SameSite=Lax" in state and "Path=/api/auth" in state
    assert run["callback_bad_state"]["status"] == 400
    back = run["signin_a"]["back"]
    assert back["status"] == 302 and back["location"] == "/#mine"
    session = next(c for c in back["cookies"] if c.startswith("made_session="))
    assert "HttpOnly" in session and "Secure" in session and "Max-Age=2592000" in session
    me = run["me_a"]["data"]
    assert me["user"]["login"] == "Alice" and me["user"]["id"] == "github-101" and me["admin"] is False
    assert me["user"]["provider"] == "github"
    assert run["me_tampered"]["data"]["user"] is None
    # GitHub's token is used once and never kept.
    assert "gho_test" not in json.dumps(run["user_a"]) and run["user_a"]["login"] == "Alice"
    assert run["logout"]["status"] == 200 and any("Max-Age=0" in c for c in run["logout"]["cookies"])


@needs_node
def test_sign_in_with_google_and_microsoft_by_their_own_endpoints(run):
    """The owner's word (2026-11-27): "login with google and login with microsoft and login with
    github". Each way in sends the person to its own authorize endpoint (its OpenID Connect discovery
    document's) asking for the name and picture only, takes the code back as a form, and is an account
    of its own. A way in with no id and secret is not offered."""
    from urllib.parse import parse_qs, urlparse

    google = urlparse(run["login_google"]["location"])
    assert f"{google.scheme}://{google.netloc}{google.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    asked = parse_qs(google.query)
    assert (
        asked["client_id"] == ["gid"]
        and asked["response_type"] == ["code"]
        and asked["scope"] == ["openid profile"]
    )
    assert asked["redirect_uri"] == ["https://made.via.computer/api/auth"], "1 callback for every way in"
    microsoft = urlparse(run["login_microsoft"]["location"])
    assert f"{microsoft.scheme}://{microsoft.netloc}{microsoft.path}" == (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    )
    asked = parse_qs(microsoft.query)
    assert (
        asked["client_id"] == ["mid"]
        and asked["scope"] == ["openid profile"]
        and asked["response_mode"] == ["query"]
    )
    assert "email" not in run["login_google"]["location"] + run["login_microsoft"]["location"]
    assert run["login_nowhere"]["status"] == 404
    assert run["login_google_off"]["status"] == 503
    assert run["me_github_only"]["data"]["providers"] == ["github"]
    g = run["me_g"]["data"]["user"]
    assert g == {
        "id": "google-1098765432109876543",
        "provider": "google",
        "login": "ThyFriendlyFox",
        "avatar": "https://lh3.googleusercontent.com/a/x",
    }
    assert run["signin_g"]["back"]["location"] == "/#mine"
    ms = run["me_ms"]["data"]["user"]
    assert (
        ms["id"] == "microsoft-AAAAAAAAAAAAAAAAAAAAAK-xyz_123"
        and ms["login"] == "Mia Soft"
        and ms["avatar"] == ""
    )
    # No email is kept, and no provider's token.
    kept = json.dumps(run["user_g"])
    assert "@" not in kept and "ya29" not in kept
    # A Google account named as the admin's GitHub login is no admin; it likes, and it adds no board.
    assert run["me_g"]["data"]["admin"] is False and run["review_g"]["status"] == 403
    assert run["like_g"]["data"] == {"board": "ex-lark", "liked": True, "count": 1}
    assert run["add_g"]["status"] == 403 and "GitHub login" in run["add_g"]["data"]["error"]
    # Cancelled at the provider: back where they were, signed out; a state of no way in is refused.
    cancelled = run["cancelled"]
    assert cancelled["status"] == 302 and cancelled["location"] == "/b/lark"
    assert not any(c.startswith("made_session=") and "Max-Age=0" not in c for c in cancelled["cookies"])
    assert run["cross"]["status"] == 400


@needs_node
def test_a_like_is_1_for_each_person_and_board(run):
    assert run["like_out"]["status"] == 401
    assert run["like_a"]["data"] == {"board": "ex-hush", "liked": True, "count": 1}
    assert run["like_b"]["data"]["count"] == 2
    assert run["like_a_again"]["data"]["count"] == 2, "a second like by the same person is still 1"
    assert run["unlike_b"]["data"] == {"board": "ex-hush", "liked": False, "count": 1}
    assert run["like_nothing"]["status"] == 404
    assert run["like_other_site"]["status"] == 403
    boards = run["boards_a"]["data"]
    assert boards["likes"] == {"ex-hush": 1, "ex-lark": 1} and boards["liked"] == ["ex-hush"]


@needs_node
def test_a_board_is_added_from_the_persons_own_public_repository(run):
    assert (
        run["add_not_mine"]["status"] == 400
        and "your own repositories" in run["add_not_mine"]["data"]["error"]
    )
    assert run["add_bad_repo"]["status"] == 400
    assert run["add_bad_folder"]["status"] == 400
    assert run["add_private"]["status"] == 400 and "private" in run["add_private"]["data"]["error"]
    assert run["add_missing"]["status"] == 400
    assert run["add_no_name"]["status"] == 400
    added = run["add"]
    assert added["status"] == 201
    board = added["data"]["board"]
    assert board["repo"] == "alice/lamp" and board["path"] == "boards/lamp" and board["ref"] == "trunk"
    assert (
        board["name"] == "Desk lamp"
        and board["category"] == "Lighting"
        and board["licence"] == "CERN-OHL-S-2.0"
    )
    assert board["status"] == "waiting" and board["approved"] is False
    assert run["boards_before"]["data"]["boards"] == [], "a board is not listed before its checks"
    assert [b["id"] for b in run["mine_a"]["data"]["boards"]] == [board["id"]]
    assert run["mine_b"]["data"]["boards"] == []
    assert run["edit_by_b"]["status"] == 404 and run["remove_by_b"]["status"] == 404
    assert run["like_unlisted"]["status"] == 404


@needs_node
def test_only_the_check_workflow_on_main_takes_and_judges_a_board(run):
    for refused in (
        "queue_no_token",
        "queue_other_workflow",
        "queue_other_audience",
        "queue_old",
        "queue_fork_branch",
        "queue_other_key",
        "result_no_token",
    ):
        assert run[refused]["status"] == 401, refused
    taken = run["queue"]["data"]["board"]
    assert taken == {
        "id": run["add"]["data"]["board"]["id"],
        "repo": "alice/lamp",
        "ref": "trunk",
        "path": "boards/lamp",
    }
    # A board being checked is not taken twice: with none waiting, the run makes an example's Gerbers.
    after = run["queue_empty"]["data"]["board"]
    assert after["example"] is True and after["id"].startswith("ex-"), after
    assert run["result"]["data"]["status"] == "green"
    assert run["result_twice"]["status"] == 409


@needs_node
def test_a_green_board_is_listed_once_an_admin_has_looked_at_it(run):
    assert run["boards_unreviewed"]["data"]["boards"] == []
    assert run["review_by_a"]["status"] == 403
    assert [b["name"] for b in run["review_list"]["data"]["boards"]] == ["Desk lamp"]
    assert run["review"]["data"]["board"]["approved"] is True
    listed = run["boards_listed"]["data"]["boards"]
    assert len(listed) == 1 and listed[0]["facts"] == {"parts": 12, "layers": 2, "area": 1500.3, "boards": 1}
    assert (
        listed[0]["picture"] is True
        and listed[0]["run"] == "https://github.com/reagent-systems/via/actions/runs/123"
    )
    assert "report" not in listed[0] and "status" not in listed[0], (
        "the page shows a listed board's card, not its report"
    )
    assert run["like_listed"]["data"]["count"] == 1
    picture = run["picture"]
    assert picture["status"] == 200 and picture["text"].startswith("<svg")
    assert picture["headers"]["content-type"] == "image/svg+xml"
    assert (
        "sandbox" in picture["headers"]["content-security-policy"]
        and picture["headers"]["x-content-type-options"] == "nosniff"
    )


@needs_node
def test_a_boards_page_reads_it_by_its_name_and_its_drawing_carries_its_colours(run):
    assert run["board_unlisted_out"]["status"] == 404, "a board not listed yet has no page for others"
    own = run["board_unlisted_owner"]["data"]
    assert own["board"]["status"] == "green" and own["board"]["approved"] is False, "its owner sees it"
    page = run["board_listed"]["data"]
    assert page["board"]["name"] == "Desk lamp" and page["likes"] == 1 and page["liked"] is True, (
        "bob liked it just before"
    )
    assert page["board"]["kicad"] == ["lamp.kicad_pcb", "power/power.kicad_pcb"], (
        "only a board file in its folder"
    )
    assert "report" not in page["board"], "only its owner sees the report"
    svg = run["picture"]["text"]
    assert svg.startswith("<svg") and "<style>" in svg and ".edge{" in svg


@needs_node
def test_a_profile_shows_a_persons_boards_and_likes_and_they_edit_their_own(run):
    """The owner's word (2026-11-27): "there needs to be a profile page". Anyone sees a person's name,
    picture, line, listed boards and likes; the person also sees their boards' states, and edits their
    own name and line, never another's."""
    other = run["profile_by_b"]["data"]
    assert run["profile_out"]["data"] == {**other, "myLiked": []}
    person = other["person"]
    assert person["id"] == "github-101" and person["name"] == "Alice" and person["github"] == "Alice"
    assert person["first"] and person["bio"] == "" and other["own"] is False
    assert [b["name"] for b in other["boards"]] == ["Desk lamp"] and "status" not in other["boards"][0]
    assert other["liked"] == {"examples": ["ex-hush"], "boards": []}
    assert other["counts"] == {"boards": 1, "likes": 1, "received": 1}, "bob liked the lamp"
    # What bob, who is looking, likes: the lamp (he took back his like of Hush).
    assert other["myLiked"] == [other["boards"][0]["id"]]
    own = run["profile_own"]["data"]
    assert (
        own["own"] is True and own["boards"][0]["status"] == "green" and own["boards"][0]["approved"] is True
    )
    assert run["profile_unknown"]["status"] == 404 and run["profile_bad"]["status"] == 404
    assert run["profile_edit_out"]["status"] == 401
    assert run["profile_edit_other_site"]["status"] == 403
    edited = run["profile_edit"]["data"]
    assert edited["person"]["id"] == "github-101", "an edit is always of the person's own profile"
    assert edited["person"]["name"] == "Alice Anders" and len(edited["person"]["bio"]) == 280
    assert run["profile_after_edit"]["data"]["person"]["name"] == "Alice Anders"
    assert run["profile_bob_after"]["data"]["person"]["name"] == "bob", "bob's profile is his own still"
    assert run["profile_bob_after"]["data"]["person"]["github"] == "bob"


@needs_node
def test_the_workflow_makes_each_examples_gerbers_and_the_page_offers_them(run):
    assert run["file_none"]["status"] == 404
    assert run["upload_untaken"]["status"] == 409, "a zip comes only for an example the workflow took"
    taken = run["queue_example"]["data"]["board"]
    first = run["queue_empty"]["data"]["board"]["id"]
    assert taken["example"] is True and taken["id"] != first, "an example taken within 2 hours waits its run"
    ex = taken["id"]
    assert (
        taken["repo"] == "reagent-systems/via"
        and taken["ref"] == "main"
        and taken["path"].startswith("examples/")
        and (ROOT / taken["path"]).is_dir()
    )
    assert run["upload_no_token"]["status"] == 401
    assert run["upload_not_zip"]["status"] == 400
    assert run["upload_bad_kind"]["status"] == 400
    assert run["upload"]["data"]["kind"] == "gerbers"
    assert run["result_example"]["data"] == {"board": ex, "files": ["gerbers"]}
    assert (
        run["board_example"]["data"]["files"] == ["gerbers"] and run["board_example"]["data"]["board"] is None
    )
    got = run["file"]
    assert got["status"] == 200 and got["headers"]["content-type"] == "application/zip"
    assert got["headers"]["content-disposition"] == f'attachment; filename="{ex[3:]}-gerbers.zip"'
    assert run["queue_next_example"]["data"]["board"]["id"] not in (first, ex), (
        "an example with its Gerbers is not taken again"
    )


@needs_node
def test_a_person_hides_checks_again_and_takes_down_their_board(run):
    assert run["hide"]["data"]["board"]["hidden"] is True and run["boards_hidden"]["data"]["boards"] == []
    assert run["show"]["data"]["board"]["hidden"] is False
    moved = run["new_folder"]["data"]["board"]
    assert moved["path"] == "boards/lamp2" and moved["status"] == "waiting" and moved["approved"] is False
    assert run["boards_rechecking"]["data"]["boards"] == [], "a new folder is a new board to check"
    assert run["queue_again"]["data"]["board"]["path"] == "boards/lamp2"
    red = run["mine_red"]["data"]["boards"][0]
    assert red["status"] == "red", "green: true with a RED verdict is red"
    assert red["run"] == "", "a run address that is not this repository's is dropped"
    assert len(red["report"]) == 20000
    assert run["check_again"]["data"]["board"]["status"] == "waiting"
    assert run["queue_third"]["data"]["board"] is not None
    assert run["mine_error"]["data"]["boards"][0]["status"] == "error"
    assert run["remove"]["data"] == {"removed": run["add"]["data"]["board"]["id"]}
    left = run["left"]
    assert not [
        p
        for p in left
        if p.startswith(
            ("made/boards/", "made/pictures/", f"made/likes/{run['add']['data']['board']['id']}/")
        )
    ]
    assert "made/likes/ex-hush/github-101" in left


@needs_node
def test_a_repository_a_folder_a_branch_and_a_way_back_are_read_strictly(run):
    assert dict(run["parse"]["repos"]) == {
        "Alice/lamp": "Alice/lamp",
        "https://github.com/Alice/lamp": "Alice/lamp",
        "github.com/Alice/lamp/": "Alice/lamp",
        "Alice/lamp.git": "Alice/lamp",
        "Alice": None,
        "Alice/..": None,
        "a b/c": None,
        "-x/y": None,
    }
    assert dict(run["parse"]["folders"]) == {
        "": ".",
        ".": ".",
        "./": ".",
        "boards/lamp": "boards/lamp",
        "boards/../x": None,
        "/abs": None,
        "a//b": None,
        "a/b/": "a/b",
    }
    assert dict(run["parse"]["branches"]) == {
        "": "",
        "main": "main",
        "release/1.0": "release/1.0",
        "a..b": None,
        "-x": None,
        "/x": None,
        "a b": None,
    }
    assert dict(run["parse"]["back"]) == {
        "/": "/",
        "/#mine": "/#mine",
        "//evil": "/",
        "https://evil": "/",
        "/\\evil": "/",
        "/a?b=c": "/a?b=c",
    }


def test_the_examples_a_like_may_name_are_what_made_py_writes():
    run = subprocess.run(
        [sys.executable, str(SITE / "made.py"), "--check"], capture_output=True, text=True, check=False
    )
    assert run.returncode == 0, run.stderr
    text = (API / "_examples.js").read_text(encoding="utf-8")
    page = (SITE / "made.html").read_text(encoding="utf-8")
    import re

    ids = re.findall(r'"(ex-[a-z0-9-]+)"', re.search(r"export const EXAMPLES = \[(.*?)\];", text).group(1))
    assert ids and ids == re.findall(r'data-like="(ex-[a-z0-9-]+)"', page)
    # Each has its page, and its folder for the Gerbers is the example's newest version.
    for slug in (i[3:] for i in ids):
        assert (SITE / "made" / f"{slug}.html").is_file(), slug
    for path in re.findall(r'"path": "([^"]+)"', text):
        assert (ROOT / path).is_dir() and path.startswith("examples/"), path


GREEN = """# Gates

GREEN with 1 warning on 2026-11-26: board

| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors |
| DRC | pass | 0 errors |
| SIM | skip | no decks |
| EXPORT | pass | 9 files |
"""


def test_a_check_is_green_only_as_board_gates_judges_a_report():
    assert made_check.judged(GREEN, 0) == (True, "GREEN with 1 warning")
    assert made_check.judged(GREEN, 1)[0] is False, "a GREEN report with a failing exit code is not green"
    assert made_check.judged(GREEN.replace("| DRC | pass", "| DRC | skip"), 0) == (
        False,
        "RED: DRC was skipped, so it judged nothing",
    )
    assert made_check.judged(GREEN.replace("| EXPORT | pass | 9 files |\n", ""), 0)[0] is False
    assert made_check.judged(GREEN.replace("GREEN with 1 warning", "RED"), 1) == (False, "RED")
    assert made_check.judged("", 0) == (False, "The gates wrote no verdict.")


def test_a_check_draws_the_board_and_prints_1_line_of_json(tmp_path, capsys):
    board = tmp_path / "board"
    shutil.copytree(ROOT / "tests" / "boards" / "pass-first-design", board)
    report = tmp_path / "report.md"
    report.write_text(GREEN, encoding="utf-8")
    assert made_check.main(["made_check.py", str(board), str(report), "0"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["green"] is True and out["verdict"] == "GREEN with 1 warning"
    assert out["facts"]["boards"] == 1 and out["facts"]["parts"] > 0 and out["facts"]["layers"] >= 2
    import base64
    import gzip

    assert gzip.decompress(base64.b64decode(out["picture"])).startswith(b"<svg")
    assert out["kicad"] == ["divider.kicad_pcb"]
    # The Gerbers the gates' EXPORT wrote go into 1 zip; a symlink among them is left out.
    gerbers = board / "build" / "fab" / "gerbers"
    gerbers.mkdir(parents=True)
    (gerbers / "divider-F_Cu.gbr").write_text("G04 front*\n", encoding="utf-8")
    (gerbers / "divider-PTH.drl").write_text("M48\n", encoding="utf-8")
    (gerbers / "stolen.txt").symlink_to(ROOT / "README.md")
    files = tmp_path / "files"
    assert made_check.main(["made_check.py", "--bundle", str(files), str(board), str(report), "0"]) == 0
    capsys.readouterr()
    import zipfile

    with zipfile.ZipFile(files / "gerbers.zip") as z:
        assert sorted(z.namelist()) == ["divider-F_Cu.gbr", "divider-PTH.drl"]
    (gerbers / "stolen.txt").unlink()
    # A board's symlink out of its folder, and a report that is a symlink, are not read.
    (board / "elsewhere.kicad_pcb").symlink_to(
        ROOT / "examples" / "anc-speaker" / "v0.1" / "anc-speaker.kicad_pcb"
    )
    report.unlink()
    report.symlink_to(tmp_path / "board" / "divider.kicad_pcb")
    assert made_check.main(["made_check.py", str(board), str(report), "0"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["facts"]["boards"] == 1 and again["report"] == "" and again["green"] is False
