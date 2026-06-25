# Publish checklist — going public

Steps to run **when making `3MagicLabs/Grandplan` public**. These are GitHub features that are free
only on public repos (or paid GitHub Advanced Security on private), so they can't be enabled while the
repo is private — they were deferred here from the v0.1 public-readiness work. Flip visibility first,
then enable the rest.

> **HARD RULE:** changing visibility to public requires an explicit maintainer decision. Nothing here
> flips visibility automatically.

## 1. Make the repo public
Settings → General → Danger Zone → Change visibility → **Public**
(or `gh repo edit 3MagicLabs/Grandplan --visibility public --accept-visibility-change-consequences`).

## 2. Branch protection on `main` (free once public) — issue #20
Require a PR + 1 code-owner review (CODEOWNERS already routes to the maintainer) + the `gate` CI check;
block force-push/deletion; admins may bypass so the maintainer can still merge.

```bash
gh api -X PUT repos/3MagicLabs/Grandplan/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["gate"] },
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 1, "dismiss_stale_reviews": true, "require_code_owner_reviews": true },
  "restrictions": null,
  "required_conversation_resolution": true,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

## 3. Secret scanning + push protection (free on public) — issue #23
```bash
gh api -X PATCH repos/3MagicLabs/Grandplan --input - <<'JSON'
{ "security_and_analysis": { "secret_scanning": { "status": "enabled" }, "secret_scanning_push_protection": { "status": "enabled" } } }
JSON
```

## 4. CodeQL code scanning (free on public) — issue #23
Settings → Security → Code scanning → **Set up → Default** (or add `.github/workflows/codeql.yml`).
Don't add the workflow while private — it errors without Advanced Security.

## 5. Private vulnerability reporting (makes the SECURITY.md advisory link live)
```bash
gh api -X PUT repos/3MagicLabs/Grandplan/private-vulnerability-reporting
```

## Already enabled while private (no action needed)
- Dependabot **alerts** + automated security fixes — enabled 2026-06-25.
- Dependabot **version updates** — `.github/dependabot.yml`.
- About description + topics — set 2026-06-25.
- CODEOWNERS, SECURITY.md, CODE_OF_CONDUCT.md, issue/PR templates, expanded CONTRIBUTING.
