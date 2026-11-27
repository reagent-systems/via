// made.via.computer is only the gallery (the owner's word, 2026-11-26), and its root is the gallery's
// page. Vercel serves a file before a rewrite of vercel.json, so `/` would serve index.html there:
// this Routing Middleware runs before the file is looked up, and serves /made at that host's root.
// Each board's page is /b/<name> on any host (the owner's word: "the boards on the made.via.computer
// should have their own pages"): an example's is /made/<name>, written by site/made.py, and a board
// someone added is /made/board, which made.js fills from /api/made by the name in the address. Every
// other page path of the gallery's host goes to via.computer by a redirect of vercel.json. A person's
// profile is /u/<id> (the owner's word: "there needs to be a profile page"), /made/profile, which
// made.js fills from /api/made.
import { next, rewrite } from "@vercel/functions";

import { SOURCES } from "./api/_examples.js";

export const GALLERY = "made.via.computer";
const PAGES = new Set(Object.keys(SOURCES).map((id) => id.replace(/^ex-/, "")));

export const config = { matcher: ["/", "/b/:path*", "/u/:path*"] };
const PERSON = /^(google|microsoft|github)-[A-Za-z0-9_-]{1,100}$/;

export default function middleware(request) {
  const url = new URL(request.url);
  const host = (request.headers.get("host") || url.host).toLowerCase();
  if (url.pathname === "/") return host === GALLERY ? rewrite(new URL("/made", request.url)) : next();
  if (url.pathname.startsWith("/u/")) {
    const who = url.pathname.slice("/u/".length).replace(/\/+$/, "");
    return PERSON.test(who) ? rewrite(new URL("/made/profile", request.url)) : next();
  }
  const name = url.pathname.slice("/b/".length).replace(/\/+$/, "");
  if (PAGES.has(name)) return rewrite(new URL(`/made/${name}`, request.url));
  if (/^[a-z0-9]{6,20}$/.test(name)) return rewrite(new URL("/made/board", request.url));
  return next();
}
