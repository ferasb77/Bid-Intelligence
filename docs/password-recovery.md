# Password recovery

Supabase redirects users to the application; the application must authenticate
the callback and collect a new password. Setting Site URL alone does not provide
a password-reset screen.

The app accepts these two recovery callbacks:

- Default Supabase confirmation links: the browser receives
  `#access_token=...&refresh_token=...&type=recovery`. The existing browser bridge
  now retains `type=recovery`, and the server establishes a recovery session.
- Custom email templates: `?token_hash=...&type=recovery`. The server verifies the
  one-time hash with Supabase before showing the password form.

Recovery sessions are kept separate from normal application sessions and do not
resolve organization membership or open bid data. The form runs before the
ordinary authentication and tenancy gates. Password updates use the public/anon
auth client authenticated as the recovery user, never the service-role client.
On success, local recovery credentials are cleared and the user signs in again.
The login page supports both existing magic links and password sign-in.

## Deployment and configuration

Deploy the changed `app.py` and `auth_session.py` to the branch used by Streamlit
Cloud. A local checkout change does not update the hosted app.

Keep Supabase Authentication > URL Configuration > Site URL set to:

`https://bid-intelligence-oj6vc2amxvnspnhriclggg.streamlit.app/`

The default Reset Password email template's `{{ .ConfirmationURL }}` link is
supported. If using a custom template, it must include a verification credential;
a plain link to Site URL cannot authenticate a password reset. An alternative
that avoids relying on the iframe fragment bridge is:

```html
<h2>Reset your password</h2>
<p><a href="{{ .SiteURL }}?token_hash={{ .TokenHash }}&amp;type=recovery">Reset password</a></p>
```

This template assumes the Site URL above ends with `/` and has no query string.
No Supabase settings or email templates were changed by this code patch.

The inherited fragment bridge temporarily carries session tokens in query
parameters; those are removed when processed, but server/proxy logging may have
already recorded the request URL. The token-hash template avoids carrying raw
session tokens in that request and is preferable for server-rendered apps.

## Verify after deployment

1. Send a fresh recovery email from Supabase after deployment.
2. Open it and confirm **Reset your password**, **New password**, and
   **Confirm new password** appear before any dashboard or organization screen.
3. Choose and submit your new password yourself. Supabase applies its configured
   password policy; the app also checks confirmation and a minimum of 8 characters.
4. Confirm the success message and use **Sign in with a password**.
5. Check that ordinary magic-link sign-in still works and an expired link shows
   an error. Do not share callback URLs, which contain authentication credentials.

Local regression tests mock Supabase and exercise both callback types, isolated
recovery state, form reruns, successful updates, validation failures, expired
sessions, identity mismatch, token cleanup, and provider failures. A live password
change is not performed by the tests.

Reference: https://supabase.com/docs/reference/python/auth-resetpasswordforemail
