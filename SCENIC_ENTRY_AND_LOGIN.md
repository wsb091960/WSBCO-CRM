# Scenic entry page and owner sign-in

Replace the old two-number dashboard with a full-screen coastal golf graphic, Medicare Made Easy typography, and an owner sign-in card. The public page never reads contacts or displays CRM counts. After sign-in, the card offers Contacts, the 10-call list, Follow-ups and Territory Map.

## Artwork
- Built-in image generation; optimized WebP at `app/static/images/coastal-golf-entry.webp` (about 315 KiB).
- Prompt: premium photorealistic Oregon coastal golf scenery, emerald fairway, coastal evergreens, ocean, warm morning light, dark green golf bag and silver irons, forest green/gold palette, quiet space for accessible HTML branding and login card, no people or embedded text.
- Original generated PNG remains outside the repository. The heading and real controls are HTML.

## Authentication
- Owner: William's existing Google account. Only that exact verified email may sign in.
- Separate Google Apps Script project: `1wGRvqE8HOBjrarxKOQc1KQsCu6c9r6rDITHtToVg666uViPvvhynpm8x`.
- `google_login/Code.gs` is deployed as a Web app, **Execute as: User accessing the web app; Who has access: Only myself**. It checks the active Google identity again before signing anything. This separate project does not change Form relay permissions.
- Private Script Property `CRM_GOOGLE_SIGNING_KEY` matches Render's environment variable with the same name. It is separate from the Form webhook key. Never commit a key value.
- Render also uses `CRM_GOOGLE_LOGIN_URL` (the verified deployment /exec URL), `CRM_OWNER_EMAIL` and `CRM_PUBLIC_URL`.
- CRM login creates a random five-minute challenge bound to an HttpOnly, Secure cookie. Google returns a two-minute HMAC assertion by HTTPS POST; assertions never appear in URLs, referrers or application logs. Issuer, audience, owner email, signature, lifetime and browser challenge are validated; each challenge can be used once.
- Successful login creates a random 12-hour session. Only a SHA-256 hash of its token is stored in the persistent SQLite database. The cookie is HttpOnly/Secure/SameSite=Lax. Sign-out deletes the server session and the cookie. Authenticated mutations require the CRM Origin header or browser-enforced same-origin Fetch Metadata; a missing/null Origin alone is never accepted.
- Default-deny middleware protects every contact page, API, import, map and report route, including direct links and API docs. Login configuration missing or invalid fails closed.
- The public root/login page, static assets and health check remain public. Existing website intake keeps its origin checks and CORS preflight; golf intake keeps its webhook key. Twilio callbacks must pass signature verification. No contact details are exposed by these exceptions.
- New auth tables are additive; Lead and golf tables are preserved. Public pages and protected responses use no-store, nosniff, no-referrer and anti-framing headers.

## Verification
72 Python checks passed, covering access control, forged/expired/replayed assertions and sessions, cookie attributes, CSRF, safe return paths, rate limiting, public Form intake and website preflight, plus existing manual calling, map links, intake idempotency and backups. Six Node checks passed for owner identity, assertion signing/POST transport and the existing Form relay.

Deployment, actual Google sign-in, sign-out and the rendered desktop/mobile presentation must be verified before marking this release complete.
