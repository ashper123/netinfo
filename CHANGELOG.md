# Changelog

All notable changes to the Network Information Toolkit (`netinfo`) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.0.0] - 2026-08-04

### Added
- Official v2.0.0 Production Release.
- Synchronized CLI version (`netinfo 2.0.0`) and User-Agent headers (`netinfo/2.0`).
- Fully automated Pytest CI suite with multi-OS matrix (Windows, Linux, macOS).
- Complete Open-Source Repository package (`README.md`, `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `pyproject.toml`).
- All verified high-priority fixes applied (macOS ARP unpadded MAC regex, IPv6 timeout 2s, Windows ipconfig process cache).

---

## [1.5.0] - 2026-08-04

### Added
- `--save <file>` CLI flag to export report snapshot as JSON.
- `--compare <file>` CLI flag to compare live network state against saved snapshots.
- `[ Snapshot Comparison ]` console section displaying scalar changes and added/removed LAN devices.

---

## [1.4.0] - 2026-08-04

### Added
- `[ Wi-Fi Information ]` section reporting SSID, BSSID, Security, Band, Channel, Signal %, RSSI dBm, Link Speed, and PHY standard.
- Cross-platform wireless support (`netsh wlan` on Windows, `nmcli`/`iwconfig` on Linux, `airport -I` on macOS).

---

## [1.3.0] - 2026-08-04

### Added
- `[ DNS Information ]` section reporting primary/secondary system DNS servers and DNS lookup timing via `socket.getaddrinfo()`.

---

## [1.2.0] - 2026-08-04

### Added
- `[ Network Health ]` section measuring Gateway and Internet (8.8.8.8) reachability and round-trip time.

---

## [1.1.0] - 2026-08-04

### Added
- Public IPv6 endpoint probes (`api6.ipify.org`, `ipv6.icanhazip.com`, `v6.ident.me`).
- IPv6 classification (`ipv6_global`, `ipv6_ula`, `ipv6_linklocal`).
- IPv6 Gateway detection (`get_default_gateway_ipv6()`).
- Robust MAC address normalization (`normalize_mac()`) supporting Cisco dot-notation and unpadded octets.
- Parallel ping sweep using `concurrent.futures.ThreadPoolExecutor(max_workers=64)`.
- `[ Active Hosts ]` console section.

---

## [1.0.0] - Initial Release

### Added
- Core single-file Python network information CLI toolkit.
- Public IPv4 + Geo details via `ipinfo.io`.
- Private IPv4 interfaces and CIDR network address calculations.
- Gateway resolution and ARP table device discovery.
- Offline OUI MAC vendor lookup + online lookup (`api.macvendors.com`).
- JSON output (`--json`).
