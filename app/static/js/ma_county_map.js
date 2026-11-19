// Progressive enhancement: map links, filters and comparisons work without JS.
(() => {
  const boxes = [...document.querySelectorAll('#ma-compare-form input[type="checkbox"]')];
  const count = document.getElementById('ma-selected-count');
  const form = document.getElementById('ma-compare-form');
  if (!form) return;
  function refresh() {
    const selected = boxes.filter(box => box.checked);
    if (count) count.textContent = `${selected.length} selected`;
    boxes.forEach(box => {
      box.disabled = !box.checked && selected.length >= 3;
      box.closest('.ma-plan-card').classList.toggle('is-checked', box.checked);
    });
  }
  boxes.forEach(box => box.addEventListener('change', refresh));
  form.addEventListener('submit', event => {
    if (!boxes.some(box => box.checked)) {
      event.preventDefault();
      if (count) count.textContent = 'Select at least one plan to compare.';
    }
  });
  refresh();
})();
