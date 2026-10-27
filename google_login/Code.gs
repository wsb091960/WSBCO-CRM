/**
 * WSBCO private Google sign-in bridge.
 * Deploy as Web app, execute as the user accessing the web app, access Only myself.
 * The visitor's identity is checked before any assertion is signed.
 * Store CRM_GOOGLE_SIGNING_KEY and GOLF_GOOGLE_SIGNING_KEY as private Script Properties;
 * each matching Render service has its own separate key. Never commit key values.
 */
function appConfig_(name) {
  const apps = {
    crm: {
      owner: 'williamsburton@gmail.com',
      audience: 'https://wsbco-crm.onrender.com',
      callback: 'https://wsbco-crm.onrender.com/auth/google/complete',
      keyProperty: 'CRM_GOOGLE_SIGNING_KEY',
      label: 'MEDICARE MADE EASY · WSBCO',
      title: 'CRM',
      returnUrl: 'https://wsbco-crm.onrender.com/'
    },
    golf: {
      owner: 'williamsburton@gmail.com',
      audience: 'https://www.busterball.com',
      callback: 'https://www.busterball.com/auth/google/complete',
      keyProperty: 'GOLF_GOOGLE_SIGNING_KEY',
      label: 'WSBCO GOLF · REEDSPORT',
      title: 'Coach Portal',
      returnUrl: 'https://www.busterball.com/'
    }
  };
  return apps[name] || null;
}

function doGet(e) {
  const appName = String((e && e.parameter && e.parameter.app) || 'crm');
  const app = appConfig_(appName);
  if (!app) return message_('Start from your workspace', 'Open your WSBCO sign-in page and choose Continue with Google.', 'https://wsbco-crm.onrender.com/');
  const email = String(Session.getActiveUser().getEmail() || '').trim().toLowerCase();
  if (email !== app.owner) return message_('Owner access only', 'This Google account does not have access to this WSBCO workspace.', app.returnUrl);
  const nonce = String((e && e.parameter && e.parameter.nonce) || '');
  if (!/^[a-f0-9]{64}$/.test(nonce)) return message_('Start from your workspace', 'Open your WSBCO sign-in page and choose Continue with Google.', app.returnUrl);
  const key = PropertiesService.getScriptProperties().getProperty(app.keyProperty);
  if (!key || key.length < 32) return message_('Sign-in is being prepared', 'Please try again shortly.', app.returnUrl);

  const issued = Math.floor(Date.now() / 1000);
  const claims = {iss:'wsbco-private-google-login', aud:app.audience,
                  email:email, nonce:nonce, iat:issued, exp:issued + 120};
  const encoded = Utilities.base64EncodeWebSafe(JSON.stringify(claims), Utilities.Charset.UTF_8).replace(/=+$/, '');
  const signature = Utilities.base64EncodeWebSafe(Utilities.computeHmacSha256Signature(encoded, key, Utilities.Charset.UTF_8)).replace(/=+$/, '');
  const assertion = encoded + '.' + signature;

  // The signed assertion is sent in an HTTPS POST body, never a URL or referrer.
  const body = '<p class="eyebrow">' + app.label + '</p><h1>Welcome back.</h1>' +
    '<p>Google has confirmed your account. Continue to your private ' + app.title + '.</p>' +
    '<form method="post" action="' + app.callback + '" target="_top">' +
    '<input type="hidden" name="assertion" value="' + assertion + '">' +
    '<button type="submit">Open my ' + app.title + ' &rarr;</button></form>' +
    '<small>This sign-in expires in two minutes and can be used once.</small>';
  return page_(body, app.title);
}

function message_(heading, message, returnUrl) {
  return page_('<p class="eyebrow">WSBCO PRIVATE SIGN-IN</p><h1>' + heading + '</h1><p>' + message + '</p>' +
               '<a href="' + returnUrl + '" target="_top">Return to sign-in</a>', 'Secure sign-in');
}

function page_(body, title) {
  const html = '<!doctype html><html lang="en"><head><base target="_top"><style>' +
    '*{box-sizing:border-box}body{margin:0;background:#edf0e8;color:#173e2e;font:16px/1.65 system-ui,sans-serif;min-height:95vh;display:grid;place-items:center;padding:24px}' +
    'main{background:#fbf9f1;width:min(440px,100%);padding:40px;border-top:3px solid #c8a761;box-shadow:0 20px 60px #173e2e13;border-radius:4px}' +
    '.eyebrow{font-size:9px;letter-spacing:.2em;color:#8b7846}h1{font:normal 44px/1.05 Georgia,serif;margin:22px 0}' +
    'p{color:#66705f;font-size:14px}button{width:100%;margin:20px 0 16px;background:#173e2e;border:0;border-radius:3px;color:white;padding:16px;font:500 14px system-ui;cursor:pointer}' +
    'small{display:block;color:#8a8d7d;font-size:11px}a{color:#173e2e}</style></head><body><main>' + body + '</main></body></html>';
  return HtmlService.createHtmlOutput(html).setTitle('WSBCO · ' + title).addMetaTag('viewport','width=device-width, initial-scale=1');
}
