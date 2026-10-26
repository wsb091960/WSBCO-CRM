const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('google_form/Code.gs', 'utf8');
function setup() {
  const props = new Map([['CRM_GOLF_ENDPOINT', 'https://wsbco-crm.onrender.com/golf/inquiries'], ['CRM_GOLF_FORM_KEY', 'test-key']]);
  const requests = [], emails = [];
  let failSave = false, failEmail = false;
  const context = vm.createContext({console, Number, JSON, Date,
    PropertiesService: {getScriptProperties: () => ({getProperty: k => props.get(k), setProperty: (k,v) => props.set(k,v)})},
    LockService: {getScriptLock: () => ({tryLock: () => true, releaseLock: () => {}})},
    FormApp: {getActiveForm: () => ({getId: () => 'form-1'})},
    UrlFetchApp: {fetch: (url, opts) => {requests.push(JSON.parse(opts.payload)); return {getResponseCode: () => failSave ? 503 : 201, getContentText: () => JSON.stringify({crm_contact_id: 42})};}},
    MailApp: {sendEmail: email => {if(failEmail) throw Error('email unavailable'); emails.push(email);}}
  });
  vm.runInContext(source, context);
  const answers = {'Your name': 'Test Multi Name', 'Phone number': '2025550147', 'Email address (optional)': '', 'What would you like help with?': 'Balance', 'Golf experience': 'New to golf', 'Preferred way to contact you': 'Phone call'};
  const response = {getId: () => 'response-1', getItemResponses: () => Object.entries(answers).map(([title,value]) => ({getItem: () => ({getTitle: () => title}), getResponse: () => value}))};
  return {context, response, requests, emails, failSave: v=>{failSave=v;}, failEmail:v=>{failEmail=v;}};
}
test('maps the published form, includes response ID, and alerts after confirmed CRM save only once', () => {
  const s = setup(); s.context.relayGolfResponse_(s.response); s.context.relayGolfResponse_(s.response);
  assert.equal(s.requests.length,1); assert.equal(s.emails.length,1);
  assert.equal(s.requests[0].first_name,'Test'); assert.equal(s.requests[0].last_name,'Multi Name');
  assert.equal(s.requests[0].goal,'Balance'); assert.equal(s.requests[0].submission_id,'google-form:form-1:response-1');
  assert.match(s.emails[0].body, /\nName: Test Multi Name\n/);
  assert.match(s.emails[0].body, /\/leads\/42/);
});
test('failed CRM save retains the response for retry and sends no success email', () => {
  const s = setup(); s.failSave(true); assert.throws(()=>s.context.relayGolfResponse_(s.response), /HTTP 503/);
  assert.equal(s.emails.length,0); s.failSave(false); s.context.relayGolfResponse_(s.response);
  assert.equal(s.requests.length,2); assert.equal(s.emails.length,1);
});
test('email retry reuses saved CRM receipt without creating another lead', () => {
  const s = setup(); s.failEmail(true); assert.throws(()=>s.context.relayGolfResponse_(s.response), /email unavailable/);
  s.failEmail(false); s.context.relayGolfResponse_(s.response);
  assert.equal(s.requests.length,1); assert.equal(s.emails.length,1);
});
