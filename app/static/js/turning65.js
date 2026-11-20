(() => {
  'use strict';
  const form = document.getElementById('t65-filters');
  if (!form) return;
  const birthday = document.getElementById('t65-window');
  const dates = document.getElementById('t65-custom-dates');
  if (birthday && dates) birthday.addEventListener('change', () => { dates.hidden = birthday.value !== 'custom'; });
  const plan = document.getElementById('t65-plan');
  const county = document.getElementById('t65-county');
  form.querySelectorAll('[data-reset-plan]').forEach(control => control.addEventListener('change', () => {
    plan.value = '';
    county.value = '';
  }));
})();
