# Password recovery

## Security model

Bid Intelligence password recovery uses Supabase's one-time recovery
`token_hash` flow. The reset email does **not** send access tokens or refresh
tokens to the application in a URL. When a user follows a valid recovery
link, the application verifies the hash with Supabase and stores the resulting
credentials only in an isolated, server-side Streamlit recovery session.

The recovery session is deliberately separate from the normal application
session:

- it clears any normal application session and organization context;
- it cannot render a dashboard, resolve organization membership, or open bid
  data;
- it can only render the reset-password form; and
- after a successful password update, the application signs the recovery
  session out locally and clears all recovery, normal-session, and tenancy
  state. The user must then sign in normally with the new password.

The callback handler accepts `token_hash` plus `type=recovery`, verifies the
hash through Supabase Auth, and immediately removes both parameters from
Streamlit's visible query state on success and failure. It never logs the
hash, an access token, or a refresh token.

`token_hash` is a one-time verifier rather than a reusable bearer credential,
but it remains sensitive until it is consumed. Reverse proxies, analytics,
support tooling, and browser diagnostics must redact `token_hash` query
parameters. Query cleanup cannot remove the initial callback request from an
upstream access log.

Expired, malformed, invalid, or already-consumed links fail with the same
generic fresh-link guidance. A successful verification consumes the
provider-issued one-time verifier; a replay must not establish another
recovery session.

The previous fragment-token bridge is intentionally unsupported. Do not use a
Supabase template that sends `access_token` or `refresh_token` in a URL
fragment, and do not add a client-side bridge that copies those values into
query parameters.

## Production configuration

The current production application root is:

```text
https://bid-intelligence-vcayfdyp4udxytdyxgzh6u.streamlit.app/
```

For the production project, the following values must be identical, including
the trailing slash:

| Location | Required value |
| --- | --- |
| Streamlit secret `APP_BASE_URL` | `https://bid-intelligence-vcayfdyp4udxytdyxgzh6u.streamlit.app/` |
| Supabase Auth > URL Configuration > Site URL | `https://bid-intelligence-vcayfdyp4udxytdyxgzh6u.streamlit.app/` |
| Supabase Auth > URL Configuration > Redirect URLs | `https://bid-intelligence-vcayfdyp4udxytdyxgzh6u.streamlit.app/` |

`request_password_reset()` passes `APP_BASE_URL` as `redirect_to`. Supabase
therefore expands `{{ .RedirectTo }}` to that approved application root. If
the application setting is missing, Supabase falls back to its configured Site
URL; that fallback is not a substitute for configuring the deployment's own
`APP_BASE_URL` correctly.

The old `bid-intelligence-oj6vc2amxvnspnhriclggg.streamlit.app` hostname is
obsolete. It must not appear in Streamlit secrets, Supabase Site URL or
Redirect URLs, reset-email templates, release instructions, or support
runbooks.

### Supabase Reset Password email template

In Supabase Dashboard > Authentication > Email Templates > **Reset Password**,
use this HTML:

```html
<h2>Reset your password</h2>

<p>We received a request to reset your password.</p>

<p>
  <a href="{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=recovery">
    Reset your password
  </a>
</p>

<p>If you did not request this, you can safely ignore this email.</p>
```

The expected callback is:

```text
https://bid-intelligence-vcayfdyp4udxytdyxgzh6u.streamlit.app/?token_hash=<one-time-hash>&type=recovery
```

Do not use the default `{{ .ConfirmationURL }}` Reset Password link after the
security patch is deployed. Its implicit-flow behavior can deliver reusable
session credentials in the URL fragment, which the secured application
intentionally does not process.

Supabase documents `{{ .TokenHash }}` for custom links and `{{ .RedirectTo }}`
for the redirect passed to `resetPasswordForEmail`; the Redirect URL must be
allowlisted in the project's Auth settings. See the official
[Email Templates](https://supabase.com/docs/guides/auth/auth-email-templates)
and [Redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls)
guides.

## Safe release sequence

1. Confirm the active Streamlit deployment URL, its deployed Git revision, and
   the live `APP_BASE_URL` secret. The application build receiving the template
   change must already support `token_hash` recovery.
2. Record the existing Supabase Reset Password template, Site URL, Redirect
   URL allowlist, and recovery-link lifetime. Do not record secrets.
3. Correct the Streamlit `APP_BASE_URL`, Supabase Site URL, and allowlist to
   the canonical root above, then replace the Reset Password template with the
   template in this document.
4. Before deploying code that removes legacy fragment handling, use an
   authorized disposable user to test one fresh token-hash reset link against
   the currently deployed compatibility build.
5. Wait for the recorded maximum lifetime of existing legacy reset links to
   elapse, or invalidate and reissue them through an approved support process.
6. Commit, review, and deploy the secured source patch through the normal
   release process.
7. Repeat the fresh-link acceptance test after deployment.

Changing the template before compatibility is proven can lock users out of
password recovery. Deploying the secured patch before changing the template
can also lock users out because it intentionally rejects the legacy fragment
flow. The compatibility test in step 4 is the gate between those operations.

## Rollback limits

After the secured patch is deployed, do **not** roll the Reset Password
template back to `{{ .ConfirmationURL }}` alone. That would issue links using
the retired fragment flow and break recovery in the secured application.

If a rollback is required, restore a previously verified application build
that supports the matching template first, verify the restoration in a browser,
then change the template only if necessary. Reissue reset links after any
template or redirect correction; previously issued links may target the wrong
host, be expired, or already be consumed.

## Production acceptance tests

Run these tests only in an authorized release window, using a disposable test
user and never copying a reset URL into tickets, logs, chat, or documentation.

1. From the live login page, request a reset for the disposable account and
   verify the UI returns the generic success message without revealing account
   existence.
2. Inspect the received link without sharing its verifier. It must target the
   canonical Streamlit root and contain `token_hash` plus `type=recovery`; it
   must not contain `access_token`, `refresh_token`, `sb_at`, or `sb_rt`.
3. Open the link once. Confirm the query parameters are cleared, the reset form
   is shown before any dashboard or organization screen, and no ordinary
   authenticated application session is available.
4. Submit a policy-compliant new password and confirm that the application
   returns to sign-in. Sign in normally with the new password.
5. Re-open the same link and confirm that it is rejected with generic
   expired/invalid-link guidance.
6. Request a second link, let it expire according to the configured recovery
   lifetime, and confirm it is rejected with the same generic guidance.
7. Verify ordinary password sign-in, sign-out, and a separate authorized
   two-user/two-organization isolation check after the release.

Email security scanners can prefetch links. If a fresh link is already invalid
when the intended user opens it, treat it as a potential prefetch event, issue
a new link, and investigate the mail-security path without exposing the link
value.

Local tests cover the isolated recovery state, reset form reruns, success and
validation paths, token cleanup, expired sessions, identity mismatch, replay
failure, and provider failures. They do not replace the live acceptance tests
above.
