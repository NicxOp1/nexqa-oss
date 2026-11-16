# Security policy

## Reporting a vulnerability

Please don't open a public issue for security problems. Use GitHub's
[private vulnerability reporting](https://github.com/NicxOp1/nexqa-oss/security/advisories/new)
instead. I'll reply within a few days.

## Running NEXQA safely

- **Webhook server.** Keep `VERIFY_SIGNATURES=true` in any deployed environment. Without it,
  anyone who knows the URL can trigger your agents' tools (book appointments, send SMS). Set
  `ADMIN_TOKEN` only if you need the admin endpoints.
- **REST API.** Set `NEXQA_API_KEY` before exposing the API beyond localhost. With no key it
  accepts every request.
- **Caller data.** Tool-call payloads can contain names, phone numbers and dates of birth. NEXQA
  logs them only at `DEBUG` level. Keep `LOG_LEVEL=INFO` or higher in production, and check your
  obligations (for example HIPAA) before you route healthcare calls through it.
- **Keys.** Keep keys in `.env` or your host's secret store. `.env` is in `.gitignore`.
