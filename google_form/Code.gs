/**
 * WSBCO Golf Lesson Inquiry: run setupGolfLeadForm() ONCE in script.google.com.
 * The script creates a Google Form and spreadsheet, then installs a submission trigger.
 * Set Script Properties CRM_GOLF_FORM_KEY, CRM_GOLF_ENDPOINT and GOLF_ALERT_EMAIL.
 * Example endpoint: https://wsbco-crm.onrender.com/golf/inquiries
 */
function setupGolfLeadForm() {
  const props = PropertiesService.getScriptProperties();
  if (props.getProperty('GOLF_FORM_ID')) {
    throw new Error('Form already created. See GOLF_FORM_URL in Script Properties.');
  }
  const form = FormApp.create('Golf Lesson Request | WSBCO Golf Instruction');
  form.setDescription('Interested in improving your golf game? Tell us a little about yourself and we will contact you about lessons, clinics or group programs.');
  form.addTextItem().setTitle('First name').setRequired(true);
  form.addTextItem().setTitle('Last name').setRequired(true);
  form.addTextItem().setTitle('Phone number').setRequired(true);
  form.addTextItem().setTitle('Email address').setRequired(false);
  form.addMultipleChoiceItem().setTitle('Program interest').setChoiceValues([
    'Individual lesson', 'Group lessons', 'Golf clinic', 'PGA Jr. League'
  ]).setRequired(true);
  form.addParagraphTextItem().setTitle('What would you like to improve?').setRequired(false);
  form.addCheckboxItem().setTitle('Permission to contact').setChoiceValues([
    'I agree to be contacted about my golf lesson request'
  ]).setRequired(true);
  form.setConfirmationMessage('Thank you! We will contact you about your golf lesson request.');
  const sheet = SpreadsheetApp.create('WSBCO Golf Lesson Requests');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, sheet.getId());
  ScriptApp.newTrigger('onGolfFormSubmit').forForm(form).onFormSubmit().create();
  props.setProperties({GOLF_FORM_ID: form.getId(), GOLF_FORM_URL: form.getPublishedUrl(),
                       GOLF_RESPONSES_SHEET: sheet.getUrl()});
  Logger.log('FORM URL: ' + form.getPublishedUrl());
  Logger.log('RESPONSES: ' + sheet.getUrl());
}
function onGolfFormSubmit(e) {
  const props = PropertiesService.getScriptProperties();
  const endpoint = props.getProperty('CRM_GOLF_ENDPOINT');
  const secret = props.getProperty('CRM_GOLF_FORM_KEY');
  if (!endpoint || !secret || !endpoint.startsWith('https://')) {
    throw new Error('Set CRM_GOLF_ENDPOINT (HTTPS) and CRM_GOLF_FORM_KEY in Script Properties');
  }
  const answers = {};
  e.response.getItemResponses().forEach(r => {
    answers[r.getItem().getTitle()] = String(r.getResponse() || '').trim();
  });
  if (!answers['Permission to contact']) throw new Error('Contact permission missing');
  const payload = {
    first_name: answers['First name'] || '',
    last_name: answers['Last name'] || '',
    phone: answers['Phone number'] || '',
    email: answers['Email address'] || '',
    program: answers['Program interest'] || 'Individual lesson',
    goal: answers['What would you like to improve?'] || ''
  };
  const result = UrlFetchApp.fetch(endpoint, {
    method: 'post',
    contentType: 'application/json',
    headers: {'X-Golf-Form-Key': secret},
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  if (result.getResponseCode() < 200 || result.getResponseCode() >= 300) {
    throw new Error('CRM submission failed: HTTP ' + result.getResponseCode());
  }
  // A confirmed CRM creation is the trigger; do not send an alert for failed saves.
  const saved = JSON.parse(result.getContentText());
  if (!saved.crm_contact_id) throw new Error('CRM did not confirm a contact ID');
  const recipient = props.getProperty('GOLF_ALERT_EMAIL') || 'williamsburton@gmail.com';
  if (!recipient) {
    console.warn('Lead created, but GOLF_ALERT_EMAIL is not configured.');
    return;
  }
  const name = payload.first_name + ' ' + payload.last_name;
  const subject = 'New Reedsport Golf Course lesson lead: ' + name;
  const body = [
    'A new golf lesson inquiry was saved in WSBCO CRM.',
    '',
    'CRM contact ID: ' + saved.crm_contact_id,
    'Name: ' + name,
    'Phone: ' + payload.phone,
    'Email: ' + (payload.email || 'Not provided'),
    'Program: ' + payload.program,
    'Golf goal: ' + (payload.goal || 'Not provided'),
    '',
    'Open WSBCO CRM to follow up with this golfer.'
  ].join('\\n');
  try {
    MailApp.sendEmail({to: recipient, subject: subject, body: body});
  } catch (err) {
    // The lead has already been saved. Log the email failure for review.
    console.error('CRM lead ' + saved.crm_contact_id + ' saved; email alert failed: ' + err);
  }
}
