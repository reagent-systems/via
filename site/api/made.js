// /api/made on made.via.computer: the boards and their likes (?do=boards), a like (?do=like), a
// person's own boards (?do=mine, add, edit, check, remove), an admin's review (?do=review), a board's
// drawing (?do=picture), and the check workflow's queue and results (?do=queue, result). The rules
// are in _made.js.
import { environment, made } from "./_made.js";
import { store } from "./_store.js";

export default {
  fetch: (request) => made(request, { env: environment(process.env), store, net: { fetch }, now: new Date() }),
};
