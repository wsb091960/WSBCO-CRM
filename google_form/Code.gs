/**
 * @OnlyCurrentDoc
 * Reedsport Golf Course: relay this existing Form to WSBCO CRM.
 * In Project Settings / Script properties set CRM_GOLF_FORM_KEY to match
 * Render's GOLF_FORM_WEBHOOK_KEY. Never put that secret in source control.
 * Run setupGolfLeadForm once to install the submission and recovery triggers.
 */
function setupGolfLeadForm() {
  const props = PropertiesService.getScriptProperties();
  const form = FormApp.getActiveForm();
  if (!form || form.getId() !== '1cx-a4BpzNNYhpGQMA2TNIaL1NKygHST51UiY9RfAAkw') {
    throw new Error('This script must be bound to the Reedsport lesson request form.');
  }
  if (!props.getProperty('CRM_GOLF_FORM_KEY')) throw new Error('Configure CRM_GOLF_FORM_KEY first.');
  props.setProperty('CRM_GOLF_ENDPOINT', 'https://wsbco-crm.onrender.com/golf/inquiries');
  props.setProperty('GOLF_ALERT_EMAIL', 'williamsburton@gmail.com');
  if (!props.getProperty('GOLF_SYNC_START')) props.setProperty('GOLF_SYNC_START', new Date(0).toISOString());
  const triggers = ScriptApp.getProjectTriggers();
  if (!triggers.some(t => t.getHandlerFunction() === 'onGolfFormSubmit')) {
    ScriptApp.newTrigger('onGolfFormSubmit').forForm(form).onFormSubmit().create();
  }
  if (!triggers.some(t => t.getHandlerFunction() === 'syncPendingGolfLeads')) {
    ScriptApp.newTrigger('syncPendingGolfLeads').timeBased().everyMinutes(5).create();
  }
  console.log('Golf CRM connection installed. Form responses remain in the linked response sheet.');
}

function onGolfFormSubmit(e) {
  if (!e || !e.response) throw new Error('Use the installed Form submission trigger.');
  relayGolfResponse_(e.response);
}

function syncPendingGolfLeads() {
  const props = PropertiesService.getScriptProperties();
  const start = props.getProperty('GOLF_SYNC_START');
  if (!start) throw new Error('Run setupGolfLeadForm first.');
  const responses = FormApp.getActiveForm().getResponses(new Date(start));
  let failures = 0;
  responses.forEach(response => {
    try { relayGolfResponse_(response); }
    catch (error) { failures++; console.error('A golf inquiry is pending retry: ' + error.message); }
  });
  if (failures) throw new Error(failures + ' golf inquiry delivery(s) pending; retry scheduled.');
  console.log('Golf inquiries checked; none pending.');
}

function relayGolfResponse_(response) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) throw new Error('Another delivery is running; retry scheduled.');
  try {
    const props = PropertiesService.getScriptProperties();
    const receiptKey = 'CRM_RECEIPT_' + response.getId();
    const receipt = JSON.parse(props.getProperty(receiptKey) || '{}');
    if (receipt.alerted) return;
    const answers = {};
    response.getItemResponses().forEach(item => {
      answers[item.getItem().getTitle()] = String(item.getResponse() || '').trim();
    });
    const nameParts = (answers['Your name'] || '').split(/\s+/);
    const payload = {
      submission_id: 'google-form:' + FormApp.getActiveForm().getId() + ':' + response.getId(),
      first_name: nameParts.shift() || '',
      last_name: nameParts.join(' '),
      phone: answers['Phone number'] || '',
      email: answers['Email address (optional)'] || '',
      program: 'Individual lesson',
      goal: answers['What would you like help with?'] || '',
      experience: answers['Golf experience'] || '',
      preferred_contact: (answers['Preferred way to contact you'] || '').replace(/ \(.*\)$/, '')
    };
    if (!receipt.crm_contact_id) {
      const endpoint = props.getProperty('CRM_GOLF_ENDPOINT');
      const secret = props.getProperty('CRM_GOLF_FORM_KEY');
      if (endpoint !== 'https://wsbco-crm.onrender.com/golf/inquiries' || !secret) {
        throw new Error('CRM endpoint or authentication is not configured.');
      }
      const result = UrlFetchApp.fetch(endpoint, {
        method: 'post', contentType: 'application/json',
        headers: {'X-Golf-Form-Key': secret}, payload: JSON.stringify(payload),
        muteHttpExceptions: true, followRedirects: false
      });
      if (result.getResponseCode() !== 201) throw new Error('CRM save returned HTTP ' + result.getResponseCode());
      const saved = JSON.parse(result.getContentText());
      if (!Number.isInteger(saved.crm_contact_id) || saved.crm_contact_id <= 0) {
        throw new Error('CRM did not confirm a contact ID.');
      }
      receipt.crm_contact_id = saved.crm_contact_id;
      props.setProperty(receiptKey, JSON.stringify(receipt));
    }
    const contactUrl = 'https://wsbco-crm.onrender.com/leads/' + receipt.crm_contact_id;
    const body = [
      'A golf lesson inquiry was saved in WSBCO CRM.', '',
      'Name: ' + (payload.first_name + ' ' + payload.last_name).trim(),
      'Phone: ' + payload.phone,
      'Email: ' + (payload.email || 'Not provided'),
      'Experience: ' + (payload.experience || 'Not provided'),
      'Preferred contact: ' + (payload.preferred_contact || 'Not provided'),
      'Golf goals: ' + (payload.goal || 'Not provided'), '',
      'Open this contact: ' + contactUrl
    ].join('\n');
    MailApp.sendEmail({
      to: props.getProperty('GOLF_ALERT_EMAIL') || 'williamsburton@gmail.com',
      subject: 'New Reedsport Golf Course lesson lead: ' + (payload.first_name + ' ' + payload.last_name).trim(),
      body: body
    });
    receipt.alerted = true;
    props.setProperty(receiptKey, JSON.stringify(receipt));
  } finally { lock.releaseLock(); }
}
