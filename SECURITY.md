# Security Policy

grandplan is an offline-first, single-user desktop tool. Its trust model — local-process trust, the
optional shared-secret token for LAN intake, and unencrypted local storage — is described in the
README's [**Security model**](./README.md#security-model) section. Please read it first to understand
what is and isn't in scope.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately via GitHub's
[**Report a vulnerability**](https://github.com/3MagicLabs/Grandplan/security/advisories/new)
(repo **Security → Advisories → Report a vulnerability**). If private reporting is unavailable, email
the maintainer at **imaansoltan@gmail.com** with a description and, ideally, a minimal reproduction.

Expect an acknowledgement within a few days. As a personal project maintained in spare time, please
allow reasonable time for a fix before any public disclosure (coordinated disclosure is appreciated).

## Supported versions

Pre-1.0: only the latest `main` receives security fixes.

## Scope

**In scope:** the core pipeline, the HTTP intake endpoint (`grandplan serve` / `up`), the folder-watch
capture, the Ollama adapter, and vault writes.

**Out of scope:** issues that require an attacker who already has local code execution or filesystem
access equivalent to the user running grandplan — the tool explicitly assumes the local user and
machine are trusted. The HTTP intake has **no authentication on `127.0.0.1` by default** by design; a
routable (LAN) bind requires a token. See the README security model for the rationale.
