/**
 * WSBCO CRM private Google sign-in bridge.
 * Standalone project, separate from the lesson Form relay.
 * Deploy as Web app, execute as the user accessing the web app, access Only myself.
 * Script property CRM_GOOGLE_SIGNING_KEY must match Render; never commit its value.
 * The visitor's identity is always checked, even when Google restricts deployment access.
 */
function doGet(e) {
  const owner = 'williamsburton@gmail.com';
  const email = Session.getActiveUser().getEmail().toLowerCase();
  if (email !== owner) return message_('Owner access only', 'This account does not have access to the WSBCO workspace.');
  const nonce = String((e && e.parameter && e.parameter.nonce) || '');
  if (!/^[a-f0-9]{64}$/.test(nonce)) return message_('Start from your workspace', 'Open your CRM home page and choose Continue with Google.');
  const key = PropertiesService.getScriptProperties().getProperty('CRM_GOOGLE_SIGNING_KEY');
  if (!key || key.length < 32) return message_('Sign-in is being prepared', 'Please try again shortly.');
  const issued = Math.floor(Date.now() / 1000);
  const claims = {iss:'wsbco-private-google-login', aud:'https://wsbco-crm.onrender.com',
                  email:email, nonce:nonce, iat:issued, exp:issued + 120};
  const encoded = Utilities.base64EncodeWebSafe(JSON.stringify(claims), Utilities.Charset.UTF_8).replace(/=+$/, '');
  const signature = Utilities.base64EncodeWebSafe(Utilities.computeHmacSha256Signature(encoded, key, Utilities.Charset.UTF_8)).replace(/=+$/, '');
  const assertion = encoded + '.' + signature;
  // POST the assertion. It never appears in a URL, referrer or browser history.
  const body = '<p class="eyebrow">MEDICARE MADE EASY · WSBCO</p><h1>Welcome back,<br>William.</h1>' +
    '<p>Google has confirmed your account. Continue to your private workspace.</p>' +
    '<form method="post" action="https://wsbco-crm.onrender.com/auth/google/complete" target="_top">' +
    '<input type="hidden" name="assertion" value="' + assertion + '">' +
    '<button type="submit">Open my workspace &rarr;</button></form>' +
    '<small>This sign-in is private, lasts two minutes and can be used once.</small>';
  return page_(body);
}

function message_(heading, message) {
  return page_('<p class="eyebrow">MEDICARE MADE EASY · WSBCO</p><h1>' + heading + '</h1><p>' + message + '</p>' +
               '<a href="https://wsbco-crm.onrender.com/" target="_top">Return to my workspace</a>');
}

function page_(body) {
  const html = '<!doctype html><html lang="en"><head><base target="_top"><style>' +
    '*{box-sizing:border-box}body{margin:0;background:#edf0e8;color:#173e2e;font:16px/1.65 system-ui,sans-serif;min-height:95vh;display:grid;place-items:center;padding:24px}' +
    'main{background:#fbf9f1;width:min(440px,100%);padding:40px;border-top:3px solid #c8a761;box-shadow:0 20px 60px #173e2e13;border-radius:4px}' +
    '.eyebrow{font-size:9px;letter-spacing:.2em;color:#8b7846}h1{font:normal 44px/1.05 Georgia,serif;margin:22px 0}' +
    'p{color:#66705f;font-size:14px}button{width:100%;margin:20px 0 16px;background:#173e2e;border:0;border-radius:3px;color:white;padding:16px;font:500 14px system-ui;cursor:pointer}' +
    'small{display:block;color:#8a8d7d;font-size:11px}a{color:#173e2e}</style></head><body><main>' + body + '</main></body></html>';
  return HtmlService.createHtmlOutput(html).setTitle('WSBCO · Secure sign-in').addMetaTag('viewport','width=device-width, initial-scale=1');
}
