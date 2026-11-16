(() => {
  const key = "carnivalLive.displayMode";
  const allowed = new Set(["brief", "standard", "detailed"]);
  const picker = document.getElementById("display-mode");
  if (!picker) return;
  const trigger = document.getElementById("display-mode-trigger");
  const dialog = document.getElementById("display-mode-dialog");
  const choices = dialog?.querySelectorAll("[data-mode]") ?? [];

  const apply = (mode) => {
    const selected = allowed.has(mode) ? mode : "standard";
    document.documentElement.dataset.displayMode = selected;
    picker.value = selected;
    if (trigger) {
      const label = picker.selectedOptions[0].textContent;
      trigger.textContent = label;
      trigger.setAttribute("aria-label", `Display mode: ${label}`);
    }
    choices.forEach(choice => choice.setAttribute("aria-pressed", String(choice.dataset.mode === selected)));
    try { localStorage.setItem(key, selected); } catch (error) {}
  };

  apply(document.documentElement.dataset.displayMode);
  picker.addEventListener("change", () => apply(picker.value));
  if (trigger && typeof dialog?.showModal === "function") {
    trigger.addEventListener("click", () => {
      dialog.showModal();
      dialog.querySelector('[aria-pressed="true"]')?.focus();
    });
    choices.forEach(choice => choice.addEventListener("click", () => {
      apply(choice.dataset.mode);
      dialog.close();
    }));
    dialog.addEventListener("close", () => trigger.focus());
    picker.hidden = true;
    trigger.hidden = false;
  }
})();
