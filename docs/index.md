# netinfo Documentation

Welcome to the official documentation for **`netinfo`** (Network Information Toolkit).

`netinfo` is a zero-dependency, cross-platform CLI tool and Python module that reports comprehensive network state across Windows, Linux, and macOS.

## Quick Features

- **Public IPv4 & IPv6**: Dual-stack IP resolution, ISP organization, location, timezone.
- **Local Network**: Interfaces, IPv4/IPv6 classification (`Global`, `ULA`, `Link-local`), default gateways.
- **LAN Device Discovery**: Active ARP neighbor parsing + 64-worker parallel ping sweep.
- **Network Health**: Real-time Gateway and Internet (8.8.8.8) RTT latency & reachability.
- **DNS Diagnostics**: Primary/secondary system DNS server extraction and lookup benchmark.
- **Wi-Fi Analytics**: SSID, BSSID, Security, Band (2.4/5/6 GHz), Channel, Signal %, RSSI (dBm), Link Speed.
- **Snapshot Diffing**: Export snapshots (`--save`) and compare state changes over time (`--compare`).

## Quick Installation

=== "PyPI"

    ```bash
    pip install netinfo
    netinfo
    ```

=== "Standalone Script"

    ```bash
    curl -O https://raw.githubusercontent.com/ashper123/netinfo/main/netinfo.py
    python3 netinfo.py
    ```

=== "Docker"

    ```bash
    docker run --rm --net=host ghcr.io/ashper123/netinfo:latest
    ```
