(() => {
  const key = "carnivalLive.displayMode";
  const allowed = new Set(["brief", "standard", "detailed"]);
  const picker = document.getElementById("display-mode");
  if (!picker) return;

  const apply = (mode) => {
    const selected = allowed.has(mode) ? mode : "standard";
    document.documentElement.dataset.displayMode = selected;
    picker.value = selected;
    try { localStorage.setItem(key, selected); } catch (error) {}
  };

  apply(document.documentElement.dataset.displayMode);
  picker.addEventListener("change", () => apply(picker.value));
})();
