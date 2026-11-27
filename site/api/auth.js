// /api/auth on made.via.computer: sign in with GitHub (?do=login), GitHub's way back (?code=...),
// log out (POST ?do=logout), and who is signed in (no parameter). The rules are in _made.js.
import { auth, environment } from "./_made.js";
import { store } from "./_store.js";

export default {
  fetch: (request) => auth(request, { env: environment(process.env), store, net: { fetch }, now: new Date() }),
};
