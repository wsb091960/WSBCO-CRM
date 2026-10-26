const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto');
const source=fs.readFileSync('google_login/Code.gs','utf8');
function render(email,nonce,key='test-key-that-is-at-least-32-characters') {
 const ctx=vm.createContext({console,Date,JSON,String,Session:{getActiveUser:()=>({getEmail:()=>email})},PropertiesService:{getScriptProperties:()=>({getProperty:()=>key})},
  Utilities:{Charset:{UTF_8:'utf8'},base64EncodeWebSafe:v=>Buffer.from(v).toString('base64url'),computeHmacSha256Signature:(value,key)=>crypto.createHmac('sha256',key).update(value).digest()},
  HtmlService:{createHtmlOutput:html=>({html,setTitle(){return this},addMetaTag(){return this}})}});
 vm.runInContext(source,ctx);return ctx.doGet({parameter:{nonce}}).html;
}
test('only the active owner account receives a signed POST assertion',()=>{
 const nonce='a'.repeat(64),key='test-key-that-is-at-least-32-characters';
 const html=render('williamsburton@gmail.com',nonce,key);
 assert.match(html,/method="post"/);assert.match(html,/target="_top"/);
 const token=html.match(/name="assertion" value="([^"]+)"/)[1], [body,signature]=token.split('.');
 assert.equal(signature,crypto.createHmac('sha256',key).update(body).digest('base64url'));
 const claims=JSON.parse(Buffer.from(body,'base64url').toString());
 assert.equal(claims.email,'williamsburton@gmail.com');assert.equal(claims.nonce,nonce);
 assert.equal(claims.aud,'https://wsbco-crm.onrender.com');assert.equal(claims.exp-claims.iat,120);
 assert(!html.includes('?assertion='));
});
test('unknown or unavailable visitor identity never receives an assertion',()=>{
 for(const email of ['', 'other@example.com'])assert(!render(email,'a'.repeat(64)).includes('name="assertion"'));
});
test('missing configuration and malformed nonce fail closed',()=>{
 assert(!render('williamsburton@gmail.com','<script>').includes('name="assertion"'));
 assert(!render('williamsburton@gmail.com','a'.repeat(64),'').includes('name="assertion"'));
});
