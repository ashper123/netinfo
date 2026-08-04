# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.5.x   | :white_check_mark: |
| < 1.5   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability within `netinfo`, please do not report it in public issues.

Please send an email to security@netinfo.local or submit a private security advisory through GitHub.

## Privacy & External Network Requests

`netinfo` performs external HTTP GET requests only when:
- Resolving public IP addresses (`api.ipify.org`, `icanhazip.com`, `ifconfig.me`, `ipinfo.io`).
- Resolving ISP/location metadata (`ipinfo.io/json`).
- Resolving MAC vendors online when `--vendors` flag is explicitly supplied (`api.macvendors.com`).

No local network data, MAC addresses, or interface credentials are sent to remote services during default execution.
