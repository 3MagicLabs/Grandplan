# Security model

grandplan is a **single-user, local-trust** tool — the capture surfaces assume the local machine and
user are trusted.

- **HTTP intake binds `127.0.0.1` by default** — there is no authentication on localhost (intentional
  for the desktop model). Every request body is capped at **1 MiB** and rejected *before* it is read if
  it is oversized, malformed, or (when a token is set) unauthorized.
- **LAN exposure requires a shared secret** — provide `GRANDPLAN_TOKEN` (preferred) or `--token`; the
  server refuses to start on a non-localhost host without one. Sent as `Authorization: Bearer <token>`.
- Captured originals are stored **unencrypted** as JSONL under `~/.grandplan/` (or `GRANDPLAN_HOME`).

Full detail: `README.md` (Security model). A STRIDE audit was completed before release.

## Reporting a vulnerability
**Do not open a public issue.** Use GitHub's private **Report a vulnerability**
(repo → Security → Advisories), or email the maintainer. See `SECURITY.md`.
