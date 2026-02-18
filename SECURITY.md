# Security Policy

## Supported Scope
This repository is intended for self-hosted Bangumi automation workflows.

Security-sensitive areas include:
- credential handling (`.env`, API tokens, chat tokens)
- downloader / media server integration
- network-exposed services (qBittorrent, Jellyfin, app API)
- CI/CD and release artifacts

## Reporting a Vulnerability
Please report vulnerabilities privately via GitHub Security Advisories:
- **Security** tab → **Report a vulnerability**

If that is unavailable, open a private issue/contact path and include:
- affected file(s) / endpoint(s)
- impact and attack scenario
- minimal reproduction steps
- suggested mitigation (if available)

Please do **not** post exploitable details in public issues.

## Response Policy
We will:
1. acknowledge receipt,
2. triage severity,
3. provide remediation ETA,
4. publish a fix and disclosure note after patching.

## Secure Development Notes
- Never commit real secrets (`.env`, tokens, passwords, API keys).
- Keep runtime state out of git (`data/`, caches, local DBs, logs).
- Prefer env-based credentials and least-privilege tokens.
- Validate URL/host inputs for network fetch paths.
- Re-run secret and static security scans before public pushes.

## Deployment Hardening (Recommended)
- Restrict service exposure (LAN/VPN/reverse proxy + auth).
- Avoid default credentials; rotate credentials periodically.
- Keep host and dependencies updated.
- Enable backups and verify restore path.
