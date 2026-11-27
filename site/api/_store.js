// The private Blob store `via-forms` as Made with Via's store: JSON files and text files by path.
// _made.js takes any object with these 8 functions; tests/test_made.py gives it 1 in memory.
import { del, get, list, put } from "@vercel/blob";

const options = (contentType) => ({ access: "private", contentType, addRandomSuffix: false, allowOverwrite: true });

async function getText(pathname) {
  try {
    const found = await get(pathname, { access: "private", useCache: false });
    return found ? await new Response(found.stream).text() : null;
  } catch {
    return null;
  }
}

export const store = {
  getText,
  async get(pathname) {
    const t = await getText(pathname);
    if (t === null) return null;
    try {
      return JSON.parse(t);
    } catch {
      return null;
    }
  },
  put: (pathname, value) => put(pathname, JSON.stringify(value), options("application/json")),
  putText: (pathname, value, type) => put(pathname, value, options(type)),
  putBytes: (pathname, bytes, type) => put(pathname, bytes, options(type)),
  async getBytes(pathname) {
    try {
      const found = await get(pathname, { access: "private", useCache: false });
      return found ? Buffer.from(await new Response(found.stream).arrayBuffer()) : null;
    } catch {
      return null;
    }
  },
  async del(pathname) {
    try {
      await del(pathname);
    } catch {
      // Gone already.
    }
  },
  async list(prefix) {
    const out = [];
    let cursor;
    do {
      const page = await list({ prefix, cursor, limit: 1000 });
      out.push(...page.blobs.map((b) => b.pathname));
      cursor = page.hasMore ? page.cursor : undefined;
    } while (cursor);
    return out;
  },
};
