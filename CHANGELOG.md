# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Project planning spine: `SPEC.md` (requirements), `RESEARCH.md` (prior art / techniques / feasibility).
- Repository hygiene: README, LICENSE (MIT), `.gitignore`, `.gitattributes`, CONTRIBUTING, ADRs.
- CI mirroring the borromeo quality gate; Dockerfile for a reproducible core test environment.
- borromeo governance (`borromeo.toml`) — deterministic build/hygiene/format/lint/typecheck/test/security gate.

### Notes
- Greenfield: no application source yet. Phase 0 (gated core, lossless-first TDD) is next.
