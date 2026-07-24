(() => {
  const storagePrefix = "carnivalLive.batterSlots:";

  document.querySelectorAll(".batter-list[data-batter-order-key]").forEach((list) => {
    const rows = [...list.querySelectorAll("[data-batter-name]")];
    if (!rows.length) return;

    const rowByName = new Map(
      rows.map((row) => [row.dataset.batterName.trim(), row])
    );
    const currentNames = [...rowByName.keys()];
    const storageKey = storagePrefix + list.dataset.batterOrderKey;
    let previousSlots = [];

    try {
      const saved = JSON.parse(sessionStorage.getItem(storageKey) || "[]");
      if (Array.isArray(saved)) previousSlots = saved.slice(0, 2);
    } catch (error) {}

    const slots = [null, null];
    previousSlots.forEach((name, index) => {
      if (name && rowByName.has(name) && !slots.includes(name)) slots[index] = name;
    });

    currentNames
      .filter((name) => !slots.includes(name))
      .forEach((name) => {
        const vacancy = slots.indexOf(null);
        if (vacancy !== -1) slots[vacancy] = name;
      });

    slots.forEach((name) => {
      if (name && rowByName.has(name)) list.appendChild(rowByName.get(name));
    });

    try {
      sessionStorage.setItem(storageKey, JSON.stringify(slots));
    } catch (error) {}
  });
})();
