(() => {
  'use strict';
  const rows = JSON.parse(document.getElementById('outreach-data').textContent);
  const dialog = document.getElementById('outreach-dialog');
  const message = document.getElementById('save-message');
  const button = document.getElementById('save-outreach');
  let selected = null;
  document.querySelectorAll('[data-edit]').forEach(edit => edit.addEventListener('click', () => {
    selected = rows[Number(edit.dataset.edit)];
    document.getElementById('edit-title').textContent = selected.center_name;
    document.getElementById('edit-address').textContent = selected.address;
    for (const [id, field] of [['contact-name','contact_name'], ['contact-phone','contact_phone'], ['outreach-status','status'], ['last-contact','last_contact_date'], ['next-follow-up','next_follow_up'], ['outreach-notes','notes']]) {
      document.getElementById(id).value = selected[field] || '';
    }
    message.textContent = '';
    dialog.showModal();
  }));
  document.getElementById('close-dialog').addEventListener('click', () => dialog.close());
  document.getElementById('outreach-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (!selected || button.disabled) return;
    const { center_id, updated_at, ...payload } = selected;
    for (const [id, field] of [['contact-name','contact_name'], ['contact-phone','contact_phone'], ['outreach-status','status'], ['last-contact','last_contact_date'], ['next-follow-up','next_follow_up'], ['outreach-notes','notes']]) {
      payload[field] = document.getElementById(id).value;
    }
    button.disabled = true;
    message.textContent = 'Saving…';
    try {
      const response = await fetch('/api/senior-outreach/records/' + encodeURIComponent(center_id), {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(response.status === 409 ? 'This record changed in another window. Reload this page before saving again.' : (typeof data.detail === 'string' ? data.detail : 'Unable to save. Please check the fields and try again.'));
      }
      window.location.reload();
    } catch (error) {message.textContent = error.message;button.disabled = false;}
  });
})();
