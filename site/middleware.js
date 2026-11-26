// made.via.computer is only the gallery (the owner's word, 2026-11-26), and its root is the gallery's
// page. Vercel serves a file before a rewrite of vercel.json, so `/` would serve index.html there:
// this Routing Middleware runs before the file is looked up, and serves /made at that host's root.
// Every other page path of that host goes to via.computer by a redirect of vercel.json.
import { next, rewrite } from "@vercel/functions";

export const GALLERY = "made.via.computer";

export const config = { matcher: "/" };

export default function middleware(request) {
  const host = (request.headers.get("host") || new URL(request.url).host).toLowerCase();
  return host === GALLERY ? rewrite(new URL("/made", request.url)) : next();
}
