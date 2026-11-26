// Made with Via (made.via.computer, site/made.py): the orders, the search, the layers' dropdown, the
// filters, each card's pictures and its menu, all on the boards' own facts in each card's data-*.
// Without this script the page shows every board in the repository's order.
(() => {
  const grid = document.querySelector("[data-grid]");
  if (!grid) return;
  const cards = [...grid.querySelectorAll(".thing")];
  const none = document.querySelector("[data-none]");
  const search = document.querySelector("[data-search]");
  const field = search?.querySelector("input");
  const layers = document.querySelector("[data-layers]");
  const panel = document.getElementById("made-panel");
  const filters = document.querySelector(".made-filters");
  const state = { sort: "all", q: "", category: "", layers: "", multi: false };

  const num = (card, key) => Number(card.dataset[key]);
  const press = (selector, on) => {
    for (const b of document.querySelectorAll(selector)) b.setAttribute("aria-pressed", String(on(b)));
  };

  const show = () => {
    const key = state.sort === "all" ? "" : state.sort;
    const order = [...cards].sort((a, b) => (key ? num(b, key) - num(a, key) : 0) || num(a, "order") - num(b, "order"));
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

  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    const inMenu = event.target.closest("details");
    if (!inMenu) closeMenus();
    else if (event.target.closest("summary")) closeMenus(inMenu);
    if (!button) return;
    if (button.dataset.sort) state.sort = button.dataset.sort;
    else if ("category" in button.dataset) state.category = button.dataset.category;
    else if ("multi" in button.dataset) state.multi = !state.multi;
    else if ("reset" in button.dataset) {
      Object.assign(state, { sort: "all", q: "", category: "", layers: "", multi: false });
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
    } else if (button.dataset.copyLink) {
      const done = () => {
        const was = button.textContent;
        button.textContent = "Copied!";
        setTimeout(() => {
          button.textContent = was;
          closeMenus();
        }, 1200);
      };
      navigator.clipboard?.writeText(button.dataset.copyLink).then(done, () => {});
      return;
    } else return;
    if (button.closest("details")) closeMenus();
    show();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenus();
  });

  search?.addEventListener("submit", (event) => event.preventDefault());
  field?.addEventListener("input", () => {
    state.q = field.value.trim().toLowerCase();
    show();
  });
  layers?.addEventListener("change", () => {
    state.layers = layers.value;
    show();
  });

  const asked = new URLSearchParams(location.search).get("q");
  if (asked && field) {
    field.value = asked;
    state.q = asked.trim().toLowerCase();
  }
  show();
})();
