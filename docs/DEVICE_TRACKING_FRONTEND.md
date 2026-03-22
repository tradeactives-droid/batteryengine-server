# Device tracking & multi-device detection

Works together with [session limiting](./SESSION_LIMITING_FRONTEND.md). Device rows are written **only** when:

- Session enforcement is enabled (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`), **and**
- The request passes session validation, **and**
- Header `x-device-id` is present (non-empty).

---

## 1) `device_id` (stable per browser)

On first visit or before login:

```ts
const STORAGE_KEY = 'device_id';
let deviceId = localStorage.getItem(STORAGE_KEY);
if (!deviceId) {
  deviceId = crypto.randomUUID();
  localStorage.setItem(STORAGE_KEY, deviceId);
}
```

Reuse the same value on every request from that browser/profile.

---

## 2) Light fingerprint (non-invasive)

Build a short string from coarse signals, then hash (e.g. SHA-256 hex):

Inputs (example):

- `navigator.userAgent`
- `navigator.language`
- `screen.width` × `screen.height` (and optionally `devicePixelRatio`)
- `Intl.DateTimeFormat().resolvedOptions().timeZone`

```ts
async function buildDeviceFingerprint(): Promise<string> {
  const raw = [
    navigator.userAgent,
    navigator.language,
    `${screen.width}x${screen.height}`,
    Intl.DateTimeFormat().resolvedOptions().timeZone || '',
  ].join('|');
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
```

Store in `localStorage` (e.g. `device_fingerprint`) after first compute, or recompute each session (cheap).

---

## 3) Headers on every API call (with session headers)

Together with `Authorization` and `x-session-token`:

```ts
headers: {
  'Content-Type': 'application/json',
  Authorization: `Bearer ${session.access_token}`,
  'x-session-token': sessionTokenFromStorage,
  'x-device-id': deviceId,
  'x-device-fingerprint': fingerprint,
}
```

`User-Agent` is sent automatically by the browser for `fetch`; the backend reads it from the `user-agent` header.

---

## 4) Backend behavior (summary)

| Data | Source |
|------|--------|
| `user_id` | JWT `sub` (after session check) |
| `device_id` | `x-device-id` |
| `fingerprint` | `x-device-fingerprint` |
| `ip_address` | `x-forwarded-for` (first hop) or `request.client.host` |
| `user_agent` | `user-agent` header |

- **New device:** insert row in `user_devices`.
- **Known device:** update `last_seen_at`, `ip_address`, `fingerprint`, `user_agent`.

**Multi-device rule:** count **distinct** `device_id` for this `user_id` with `last_seen_at` within the last **7** days (override with env `DEVICE_TRACKING_WINDOW_DAYS`).

**Warning:** `device_warning` is `true` when `device_count` **>** `DEVICE_WARNING_THRESHOLD` (default **3**, i.e. warn from **4** distinct devices upward). Set `DEVICE_WARNING_THRESHOLD=2` to warn from **3** devices.

Successful API responses may include (only when tracking ran):

```json
{
  "device_warning": false,
  "device_count": 2
}
```

Optional audit log: when `device_warning` is true, backend may insert `security_events` (`event_type`: `MULTI_DEVICE_USAGE`). Disable with `SECURITY_EVENTS_ENABLED=0`.

---

## 5) Frontend UX (optional)

If `device_warning === true`, you may show a soft notice later; **no action required** for current flows.

---

## 6) Database

Apply migration: `supabase/migrations/20260322120000_user_devices_security_events.sql`
