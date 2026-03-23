# Single active session — frontend & backend

## Backend environment (FastAPI)

When **all** of the following are set, every protected route validates the session:

| Variable | Purpose |
|----------|---------|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key; backend calls PostgREST (`/rest/v1/active_sessions`) with this key (bypasses RLS) |
| `SUPABASE_JWT_SECRET` | Verify `Authorization: Bearer` JWT (HS256, default `aud`: `authenticated`) |

Optional:

| Variable | Purpose |
|----------|---------|
| `SUPABASE_JWT_AUDIENCE` | Override JWT `aud` claim (default `authenticated`) |

If any of the three required variables is missing, session checks are **disabled** (existing deployments keep working without Supabase).

---

## Frontend steps

Backend validates `Authorization: Bearer <access_token>` + `x-session-token` when these env vars are set on the API:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_JWT_SECRET`

---

## 1) After successful Supabase login

```ts
import { v4 as uuidv4 } from 'uuid';

const sessionToken = uuidv4();
const userId = (await supabase.auth.getUser()).data.user?.id;
if (!userId) return;

// Remove previous session(s) for this user (unique constraint also allows upsert patterns)
const registerRes = await fetch(`${API_URL}/register-session`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${session?.access_token}`,
  },
  body: JSON.stringify({
    session_token: sessionToken,
  }),
});

if (!registerRes.ok) { /* handle */ return; }

localStorage.setItem('session_token', sessionToken);
```

Use the **same** key name your API client will read (`session_token` or your app’s chosen key).

---

## 2) Attach header on every API call

```ts
const token = localStorage.getItem('session_token');
const { data: { session } } = await supabase.auth.getSession();

const res = await fetch(`${API_URL}/compute_v3`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${session?.access_token}`,
    'x-session-token': token ?? '',
  },
  body: JSON.stringify(payload),
});
```

Apply the same headers for all protected routes (`/validate-session`, `/compute_v3`, `/compute_v3_profile`, `/parse_csv`, `/generate_advice`).

---

## 3) Proactive validation on app load / interval / focus

Call `GET /validate-session`:

- once on app start (after restoring auth state),
- every 10–20 seconds with `setInterval`,
- and on `window.focus` / `visibilitychange`.

If it returns 401 `SESSION_INVALID`, run the same forced logout flow.

```ts
async function validateSessionNow() {
  const token = localStorage.getItem('session_token');
  const { data: { session } } = await supabase.auth.getSession();

  const res = await fetch(`${API_URL}/validate-session`, {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${session?.access_token ?? ''}`,
      'x-session-token': token ?? '',
    },
  });

  await handleApiResponse(res); // handles 401 SESSION_INVALID
}

// app init
validateSessionNow();

// periodic
const intervalId = window.setInterval(validateSessionNow, 15000);

// focus/visibility
window.addEventListener('focus', validateSessionNow);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') validateSessionNow();
});
```

---

## 4) Handle forced logout (401 `SESSION_INVALID`)

The API returns **flat** JSON (no `detail` wrapper) when `error_code` is present:

```json
{
  "error_code": "SESSION_INVALID",
  "message": "Session expired. You have been logged out."
}
```

Example handler:

```ts
async function handleApiResponse(res: Response) {
  if (res.status === 401) {
    let body: { error_code?: string } = {};
    try {
      body = await res.json();
    } catch { /* ignore */ }

    if (body.error_code === 'SESSION_INVALID') {
      localStorage.removeItem('session_token');
      await supabase.auth.signOut();
      // toast / alert:
      // "Je bent uitgelogd omdat je account op een ander apparaat is gebruikt."
      window.location.href = '/login';
      return;
    }
  }
  // ... normal handling
}
```

---

## 5) Security notes

- Backend `POST /register-session` does an atomic upsert (`ON CONFLICT (user_id)`), so the last login always wins.
- Session token is a random UUID; the server compares it to the DB row — client storage alone is not enough.
- Never expose `SUPABASE_SERVICE_ROLE_KEY` in the frontend; only the backend uses it.
