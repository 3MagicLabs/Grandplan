# Remote-capture transport — self-hosted Headscale + WireGuard (runbook)

> **Decision** (2026-07-03, issue #37): captures from outside the home reach the grandplan intake
> over a **self-hosted overlay network**: [Headscale](https://github.com/juanfont/headscale)
> (open-source coordination server, runs on a home device) + the open-source Tailscale clients,
> with **WireGuard** doing all encryption. No vendor SaaS, no third party sees traffic *or*
> metadata. grandplan itself is transport-agnostic — it only ever sees a request on a private
> address; this document is deployment guidance, not app code.

## Architecture

```
 phone (Tailscale client, ──WireGuard tunnel──▶ laptop (Tailscale client)
   sender shortcut/PWA)         (E2E encrypted,      grandplan up → HTTP intake
        │                        direct P2P when      bound to the tailnet IP,
        │ control plane only     possible)            token-authed
        ▼
 home server (always-on box / Pi)
   Headscale  ← the ONLY internet-reachable endpoint (TLS, authenticated)
   embedded DERP relay ← fallback path when NAT blocks direct P2P (sees ciphertext only)
```

- **Note content** flows phone → laptop inside WireGuard. Headscale never carries it.
- **Headscale** only exchanges public keys / device state (the job Tailscale's SaaS would do).
  Self-hosting it means even *metadata* stays home.
- **DERP**: enable Headscale's embedded DERP server so relay fallback is also self-hosted
  (otherwise clients fall back to Tailscale's public DERP fleet — encrypted, but third-party).

## What must be exposed to the internet (and what must not)

| Endpoint | Exposure | Why it's OK |
|---|---|---|
| Headscale HTTPS (e.g. 443) | port-forward on the router | control plane only; TLS + authenticated; no note content ever |
| Embedded DERP (TCP 443 path / UDP 3478 STUN) | same box | relays ciphertext only |
| **grandplan intake** | **NEVER** | reachable only on tailnet IPs; keep the 127.0.0.1/tailnet bind + token |
| **the vault** | **NEVER** | plain files on the laptop; nothing serves them |

A free dynamic-DNS name (e.g. DuckDNS) pointed at the home IP + Let's Encrypt gives Headscale a
stable TLS endpoint without a static IP.

## Setup steps (once)

1. **Home server** (any always-on Linux box / Raspberry Pi / container host):
   - Install Headscale (binary or Docker). In `config.yaml`: set `server_url` to the DDNS name,
     enable the embedded DERP server, TLS via Let's Encrypt (built-in) or a reverse proxy.
   - Router: forward the chosen HTTPS port (and DERP/STUN ports) to this box. Keep Headscale
     updated — it is the one internet-facing service.
   - `headscale users create <you>` and mint pre-auth keys per device:
     `headscale preauthkeys create --user <you>`.
2. **Laptop (runs grandplan)**: install Tailscale (open-source client), then
   `tailscale up --login-server https://<your-ddns>:<port> --authkey <key>`.
3. **Phone**: Tailscale app → custom server → same login URL + key.
4. **ACL (recommended)**: in Headscale's ACL policy, allow the phone to reach the laptop **only on
   the intake port** (default 8765). The tunnel is trusted-device-only, but least-privilege is free.
5. **grandplan**: run `grandplan up -o <vault> --host <laptop-tailnet-ip> --token …` (a routable
   bind requires the token — enforced by the CLI). `GRANDPLAN_TOKEN` env keeps it off the cmdline.

## Verify

From the phone (or `curl` on any tailnet device):

```
curl -H "Authorization: Bearer $GRANDPLAN_TOKEN" \
     -d '{"content":"test capture over the tailnet"}' \
     http://<laptop-tailnet-ip>:8765/
```

→ expect `201` and the directive queued; then confirm it lands via the agent-intake loop.

## Failure modes & fallbacks

- **Laptop asleep when sending** → the sender queues locally and retries (issue #37 v1); the
  store-and-forward home-receiver variant is the documented v2 (#37 comment thread).
- **Headscale box down** → devices with established sessions keep working P2P for a while; new
  logins wait. The vault and local capture are unaffected (grandplan never depends on the tunnel).
- **Simplest-possible alternative** (kept on record): plain WireGuard phone↔laptop — one silent
  UDP port forward, zero servers, no coordination plane at all. Fewer moving parts, less
  convenient with >2 devices. Either transport satisfies #37; the app cannot tell the difference.

## Invariants (unchanged)

- grandplan makes **no outbound connections**; the intake only receives, token-gated.
- The vault is never served to any network, tailnet included.
- Everything above is user infrastructure; no app code couples to Headscale, Tailscale, or
  WireGuard specifically.
