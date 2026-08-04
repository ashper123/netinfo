#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netinfo.py — Network Information Toolkit
========================================

Reports everything about the network you are currently connected to:

  * Public IPv4 address (+ ISP / geo details via ipinfo.io)
  * Private (LAN) IPv4 address per network interface
  * Subnet mask / CIDR prefix
  * Network address and broadcast address
  * Default gateway
  * Devices currently visible on the LAN (IP, MAC, vendor, hostname)
  * Number of live hosts found vs. usable host count for the subnet

Compatible with Windows, Linux and macOS. Python 3.8+ required.

Optional third-party module (recommended, not required):
    pip install netifaces

Usage:
    python3 netinfo.py                 # pretty console report
    python3 netinfo.py --json          # machine-readable JSON
    python3 netinfo.py --sweep         # ping-sweep the subnet first (slower)
    python3 netinfo.py --vendors       # online OUI vendor lookup (api.macvendors.com)
    python3 netinfo.py --no-dns        # skip reverse-DNS hostname lookups

Run it only against networks you own or are authorized to test.
--sweep sends ICMP echo requests inside your local subnet only.
"""

import argparse
import ipaddress
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.error import URLError
from urllib.request import Request, urlopen

# ----------------------------------------------------------------------------
# ANSI Styling Helper (Zero Dependencies)
# ----------------------------------------------------------------------------
class Colors:
    """Zero-dependency ANSI styling helper with automatic TTY and NO_COLOR detection."""
    def __init__(self, enabled=True):
        self.enabled = enabled

    @property
    def BOLD(self): return "\033[1m" if self.enabled else ""
    @property
    def DIM(self): return "\033[2m" if self.enabled else ""
    @property
    def RESET(self): return "\033[0m" if self.enabled else ""
    @property
    def GREEN(self): return "\033[32m" if self.enabled else ""
    @property
    def RED(self): return "\033[31m" if self.enabled else ""
    @property
    def YELLOW(self): return "\033[33m" if self.enabled else ""
    @property
    def BLUE(self): return "\033[34m" if self.enabled else ""
    @property
    def MAGENTA(self): return "\033[35m" if self.enabled else ""
    @property
    def CYAN(self): return "\033[36m" if self.enabled else ""
    @property
    def GRAY(self): return "\033[90m" if self.enabled else ""


def _init_colors(args):
    """Determine if ANSI colors should be enabled."""
    if getattr(args, "no_color", False):
        return Colors(enabled=False)
    if os.environ.get("NO_COLOR"):
        return Colors(enabled=False)
    if not sys.stdout.isatty():
        return Colors(enabled=False)

    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

    return Colors(enabled=True)

# ----------------------------------------------------------------------------
# Platform detection
# ----------------------------------------------------------------------------
IS_WINDOWS = platform.system() == "Windows"
IS_MAC     = platform.system() == "Darwin"
IS_LINUX   = platform.system() == "Linux"

PING_MAX_WORKERS = 64   # concurrent ping workers for ping_sweep_parallel()
HEALTH_INTERNET_TARGET = "8.8.8.8"  # internet probe target for health check
DNS_TEST_TARGET = "google.com"      # DNS lookup target for DNS information

PUBLIC_IP_ENDPOINTS = [
    "https://api.ipify.org",
    "https://icanhazip.com",
    "https://ifconfig.me/ip",
    "https://ipinfo.io/ip",
]
IPINFO_URL = "https://ipinfo.io/json"

# IPv6-only echo services — these resolve only over IPv6; they will raise
# socket.gaierror on purely IPv4-connected hosts (caught and skipped).
PUBLIC_IPV6_ENDPOINTS = [
    "https://api6.ipify.org",
    "https://ipv6.icanhazip.com",
    "https://v6.ident.me",
]

# Small offline OUI -> vendor map (first 3 octets). Add your own as needed.
COMMON_OUI = {
    "00:1B:44": "Dell",          "3C:07:54": "HP",
    "F8:32:E4": "ASUSTek",       "A4:77:33": "Samsung",
    "CC:08:E0": "Apple",         "F0:18:98": "TP-Link",
    "50:C7:BF": "TP-Link",       "00:1E:52": "Huawei",
    "00:0C:29": "VMware",        "00:50:56": "VMware",
    "02:42:00": "Docker",        "C8:3A:35": "Raspberry Pi",
    "B8:27:EB": "Raspberry Pi",  "DC:A6:32": "Raspberry Pi",
    "00:1A:11": "Google",        "3C:5A:B4": "Google",
    "F4:F5:D8": "Google",        "08:00:27": "Oracle VirtualBox",
    "00:1C:42": "Parallels",     "AC:84:C6": "Amazon",
    "FC:65:DE": "Amazon",        "00:25:9C": "Cisco",
    "00:1A:A1": "Intel",         "3C:A6:F6": "Intel",
}


# ----------------------------------------------------------------------------
# Low-level helpers
# ----------------------------------------------------------------------------
def http_get(url, timeout=5):
    """Fetch a URL and return its body as text."""
    req = Request(url, headers={"User-Agent": "netinfo/2.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace").strip()


def run_cmd(cmd, timeout=10):
    """Run a command and return stdout ('' on failure)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            errors="replace", check=False,
        )
        return proc.stdout
    except Exception:
        return ""


_WINDOWS_IPCONFIG_CACHE = None


def _get_windows_ipconfig():
    """
    Fetch 'ipconfig /all' output, caching the string for the duration of a report run.
    Reset at the start of collect_report().
    """
    global _WINDOWS_IPCONFIG_CACHE
    if _WINDOWS_IPCONFIG_CACHE is None:
        _WINDOWS_IPCONFIG_CACHE = run_cmd(["ipconfig", "/all"])
    return _WINDOWS_IPCONFIG_CACHE


def normalize_mac(mac):
    """Normalize any MAC format to uppercase colon form (AA:BB:CC:DD:EE:FF).

    Accepted input formats (all case-insensitive):
        Colon-separated    : aa:bb:cc:dd:ee:ff
        Dash-separated     : aa-bb-cc-dd-ee-ff
        Mixed separators   : AA-bb:CC-dd:EE-ff
        Cisco dotted       : aabb.ccdd.eeff      (4-char groups, dot separator)
        No delimiter       : aabbccddeeff        (12 consecutive hex chars)
        Unpadded octets    : 8:0:27:12:34:56     (BSD/macOS arp output)

    Returns None for any input that cannot be mapped to a valid 6-octet MAC.
    Never raises an exception.
    """
    if not mac:
        return None
    mac = mac.strip()

    # ------------------------------------------------------------------
    # Path A — Cisco dot-notation: exactly three 4-char groups with dots
    # e.g. aabb.ccdd.eeff
    # Must be checked before the generic separator path because dots are
    # also used as separators in some non-standard colon/dash variants.
    # ------------------------------------------------------------------
    dot_parts = mac.split(".")
    if len(dot_parts) == 3:
        # All three parts must be exactly 4 hex characters
        if all(len(p) == 4 and all(c in "0123456789abcdefABCDEF" for c in p)
               for p in dot_parts):
            hex_str = "".join(dot_parts)
            return ":".join(hex_str[i:i+2] for i in range(0, 12, 2)).upper()
        return None   # Dot-separated but wrong format — reject cleanly
    elif len(dot_parts) == 6:
        # Six dot-separated octets (aa.bb.cc.dd.ee.ff) — not a real MAC
        # format on any platform; reject explicitly so Path C cannot accept it.
        return None

    # ------------------------------------------------------------------
    # Path B — No delimiter: exactly 12 consecutive hex characters
    # e.g. aabbccddeeff
    # ------------------------------------------------------------------
    if len(mac) == 12 and all(c in "0123456789abcdefABCDEF" for c in mac):
        return ":".join(mac[i:i+2] for i in range(0, 12, 2)).upper()

    # ------------------------------------------------------------------
    # Path C — Colon / dash / mixed separated (including unpadded octets)
    # Normalise all separators to ':' then split.
    # e.g. aa:bb:cc:dd:ee:ff  /  aa-bb-cc-dd-ee-ff  /  8:0:27:12:34:56
    # ------------------------------------------------------------------
    normalised = mac.replace("-", ":").replace(".", ":")
    parts = [p for p in normalised.split(":") if p]  # drop empty tokens

    if len(parts) != 6:
        return None   # Wrong octet count — reject

    padded = []
    for p in parts:
        if len(p) > 2 or not p:           # more than 2 hex chars → invalid
            return None
        if not all(c in "0123456789abcdefABCDEF" for c in p):
            return None                   # non-hex character → reject
        padded.append(p.zfill(2))         # '8' → '08', '0' → '00'

    return ":".join(padded).upper()


def _classify_ipv6_addresses(raw_addrs):
    """
    Classify a list of raw IPv6 address strings into three buckets.

    raw_addrs may contain scope-id suffixes (e.g. 'fe80::1%eth0').  The
    scope-id is preserved in the link-local list (required for routing) but
    stripped before feeding to ipaddress for classification.

    Returns:
        (global_list, ula_list, linklocal_list) — each a list of strings.

    Classification rules (RFC 4291 / RFC 4193):
        Global unicast  : 2000::/3   (first nibble 2 or 3)
        ULA             : fc00::/7   (first byte fc or fd)
        Link-local      : fe80::/10

    Silently skips loopback (::1), multicast (ff00::/8), unspecified (::),
    and any malformed entry.
    """
    global_list, ula_list, linklocal_list = [], [], []

    # Pre-built network objects for membership tests
    _NET_GLOBAL    = ipaddress.ip_network("2000::/3")
    _NET_ULA       = ipaddress.ip_network("fc00::/7")
    _NET_LINKLOCAL = ipaddress.ip_network("fe80::/10")

    for raw in raw_addrs:
        if not raw:
            continue
        raw = raw.strip()
        # Separate the scope-id suffix (e.g. '%eth0', '%Wi-Fi') before parsing
        scope = ""
        if "%" in raw:
            addr_part, scope = raw.split("%", 1)
            scope = "%" + scope
        else:
            addr_part = raw
        try:
            addr = ipaddress.ip_address(addr_part)
        except ValueError:
            continue   # malformed — skip silently
        if addr.version != 6:
            continue
        # Skip loopback, multicast, unspecified
        if addr.is_loopback or addr.is_multicast or addr.is_unspecified:
            continue
        if addr in _NET_LINKLOCAL:
            linklocal_list.append(addr_part + scope)  # keep scope for link-local
        elif addr in _NET_ULA:
            ula_list.append(addr_part)
        elif addr in _NET_GLOBAL:
            global_list.append(addr_part)
        # anything else (e.g. deprecated site-local fc00::/8 subsets) is ignored

    return global_list, ula_list, linklocal_list


# ----------------------------------------------------------------------------
# 1. Public IP
# ----------------------------------------------------------------------------
def get_public_ipv4():
    """Try several public-IP services until one answers with a valid IPv4."""
    for url in PUBLIC_IP_ENDPOINTS:
        try:
            ip = ipaddress.ip_address(http_get(url))
            if ip.version == 4:
                return str(ip)
        except (URLError, ValueError, OSError):
            continue
    return None


def get_public_ipv6():
    """
    Try several IPv6-only echo services until one returns a valid IPv6 address.

    Returns the address as a string, or None when:
      * The host has no IPv6 connectivity (socket.gaierror / OSError).
      * All services are unreachable or return unexpected data.

    The endpoints are IPv6-only DNS names; on IPv4-only machines every
    attempt raises socket.gaierror, which is a subclass of OSError and
    therefore caught without any special handling.
    """
    for url in PUBLIC_IPV6_ENDPOINTS:
        try:
            ip = ipaddress.ip_address(http_get(url, timeout=2))
            if ip.version == 6:
                return str(ip)
        except (URLError, ValueError, OSError):
            continue
    return None


def get_public_ip_details(ip):
    """Fetch ISP / geo details for a public IP from ipinfo.io."""
    try:
        data = json.loads(http_get(f"{IPINFO_URL}?ip={ip}"))
        return {
            "ip":       data.get("ip"),
            "hostname": data.get("hostname"),
            "city":     data.get("city"),
            "region":   data.get("region"),
            "country":  data.get("country"),
            "org":      data.get("org"),          # ISP
            "timezone": data.get("timezone"),
        }
    except Exception:
        return {"ip": ip}


def get_primary_private_ip():
    """
    Classic UDP trick: connecting a UDP socket never sends packets, but the
    kernel fills in the source address of the *default route* interface.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


# ----------------------------------------------------------------------------
# 2. Private IPs per interface (netifaces first, OS parsers as fallback)
# ----------------------------------------------------------------------------
def _get_interfaces_netifaces():
    try:
        import netifaces
    except ImportError:
        return None

    result = []
    for name in netifaces.interfaces():
        if name == "lo":
            continue
        addrs = netifaces.ifaddresses(name)
        if netifaces.AF_INET not in addrs:
            continue
        for a in addrs[netifaces.AF_INET]:
            if "addr" not in a:
                continue
            entry = {
                "name":      name,
                "ip":        a.get("addr"),
                "prefix":    None,
                "broadcast": a.get("broadcast"),
            }
            netmask = a.get("netmask")
            if netmask:
                entry["prefix"] = ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen

            # --- IPv6 classification (additive, does not touch IPv4 keys) ---
            raw_v6 = [
                a6.get("addr", "")
                for a6 in addrs.get(netifaces.AF_INET6, [])
                if a6.get("addr")
            ]
            g, u, ll = _classify_ipv6_addresses(raw_v6)
            entry["ipv6_global"]    = g
            entry["ipv6_ula"]       = u
            entry["ipv6_linklocal"] = ll

            result.append(entry)
    return result or None


def _parse_linux_ip_addr(output):
    """
    Parse `ip -4 addr show` output for IPv4 info, then merge IPv6 data
    from a separate `ip -6 addr show` call into the same interface dicts.

    The two commands are kept separate so that the IPv4 path is unchanged
    and IPv6 never interferes with IPv4 parsing.
    """
    interfaces, current = [], None
    for line in output.splitlines():
        m_iface = re.match(r"^\d+:\s+(\S+):", line)
        if m_iface:
            current = {"name": m_iface.group(1), "ip": None,
                       "prefix": None, "broadcast": None}
            interfaces.append(current)
            continue
        if current is None:
            continue
        m_inet = re.match(r"\s+inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", line)
        if m_inet and current["ip"] is None:
            current["ip"] = m_inet.group(1)
            current["prefix"] = int(m_inet.group(2))
        m_brd = re.search(r"brd\s+(\d+\.\d+\.\d+\.\d+)", line)
        if m_brd:
            current["broadcast"] = m_brd.group(1)
    result = [i for i in interfaces if i["ip"]]

    # --- Merge IPv6 addresses by interface name (additive) ---
    # Build a name->entry map for fast lookup.
    iface_map = {i["name"]: i for i in result}
    # Initialise IPv6 buckets on all interfaces.
    for i in result:
        i["ipv6_global"]    = []
        i["ipv6_ula"]       = []
        i["ipv6_linklocal"] = []

    # Parse `ip -6 addr show` — runs once, result merged by name.
    out6 = run_cmd(["ip", "-6", "addr", "show"])
    current_name = None
    raw_v6_by_name = {}   # name -> [addr_string, ...]
    for line in out6.splitlines():
        m_iface = re.match(r"^\d+:\s+(\S+):", line)
        if m_iface:
            current_name = m_iface.group(1)
            continue
        if current_name is None:
            continue
        # inet6 2001:db8::1/64 scope global  (or link, host, ...)
        m6 = re.match(r"\s+inet6\s+([0-9a-fA-F:]+(?:%\S+)?)/(\d+)", line)
        if m6:
            raw_v6_by_name.setdefault(current_name, []).append(m6.group(1))

    for name, addrs in raw_v6_by_name.items():
        if name not in iface_map:
            continue   # interface has no IPv4 — skip
        g, u, ll = _classify_ipv6_addresses(addrs)
        iface_map[name]["ipv6_global"]    = g
        iface_map[name]["ipv6_ula"]       = u
        iface_map[name]["ipv6_linklocal"] = ll

    return result


def _parse_mac_ifconfig(output):
    """
    Parse `ifconfig -a` output (macOS, or Linux without `ip`).

    IPv4 parsing is unchanged.  IPv6 addresses are collected from `inet6`
    lines within the same block and classified via _classify_ipv6_addresses.

    macOS link-local addresses appear as 'fe80::1%en0'; the scope-id
    (%en0) is preserved in the link-local list because the kernel requires
    it for routing.
    """
    interfaces, current = [], None
    raw_v6_by_iface = {}   # name -> [raw_addr, ...]

    for line in output.splitlines():
        if line and not line[0] in ("\t", " "):
            current = {"name": line.split(":")[0], "ip": None,
                       "prefix": None, "broadcast": None}
            interfaces.append(current)
            continue
        if current is None:
            continue
        # --- IPv4 (unchanged) ---
        m_inet = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)\s+netmask\s+0x([0-9a-fA-F]+)", line)
        if m_inet:
            current["ip"] = m_inet.group(1)
            current["prefix"] = bin(int(m_inet.group(2), 16)).count("1")
        m_brd = re.search(r"broadcast\s+(\d+\.\d+\.\d+\.\d+)", line)
        if m_brd:
            current["broadcast"] = m_brd.group(1)
        # --- IPv6 (additive) ---
        # Example lines:
        #   inet6 fe80::1%en0 prefixlen 64 scopeid 0xa
        #   inet6 2001:db8::1 prefixlen 64
        m6 = re.search(r"inet6\s+([0-9a-fA-F:]+(?:%\S+)?)", line)
        if m6:
            raw_v6_by_iface.setdefault(current["name"], []).append(m6.group(1))

    result = [i for i in interfaces if i["ip"]]

    # Classify and attach IPv6 buckets to each interface that has an IPv4 addr.
    result_names = {i["name"] for i in result}
    for i in result:
        addrs = raw_v6_by_iface.get(i["name"], [])
        g, u, ll = _classify_ipv6_addresses(addrs)
        i["ipv6_global"]    = g
        i["ipv6_ula"]       = u
        i["ipv6_linklocal"] = ll

    return result


def _parse_windows_ipconfig(output):
    """
    Parse `ipconfig /all` output (Windows).

    IPv4 parsing is unchanged.  IPv6 addresses are collected from
    'IPv6 Address' lines within the same adapter block.  Windows may
    append a suffix like '(Preferred)' or '(Deprecated)' to addresses;
    these are stripped before classification.

    Multiple IPv6 addresses on a single adapter are supported.
    """
    interfaces, current = [], None
    raw_v6_by_name = {}   # adapter name -> [raw_addr, ...]

    for raw in output.splitlines():
        line = raw.strip()
        m_adapter = re.match(r"^([A-Za-z0-9 _\-\.]+) adapter (\S.*):$", line)
        if m_adapter:
            current = {"name": m_adapter.group(2).strip(), "ip": None,
                       "prefix": None, "broadcast": None, "gateway": None}
            interfaces.append(current)
            continue
        if current is None:
            continue
        # --- IPv4 (unchanged) ---
        m_ip = re.match(r"IPv4 Address[^:]*:\s*(\d+\.\d+\.\d+\.\d+)", line)
        if m_ip:
            current["ip"] = m_ip.group(1)
        m_mask = re.match(r"Subnet Mask[^:]*:\s*(\d+\.\d+\.\d+\.\d+)", line)
        if m_mask:
            current["prefix"] = ipaddress.IPv4Network(f"0.0.0.0/{m_mask.group(1)}").prefixlen
        m_gw = re.match(r"Default Gateway[^:]*:\s*(\d+\.\d+\.\d+\.\d+)", line)
        if m_gw:
            current["gateway"] = m_gw.group(1)
        # --- IPv6 (additive) ---
        # Windows line: '   IPv6 Address. . . . . . . . . . . : 2001:db8::1(Preferred)'
        # Also catches temporary and link-local variants.
        m_v6 = re.match(
            r"(?:IPv6 Address|Temporary IPv6 Address|Link-local IPv6 Address)[^:]*:\s*"
            r"([0-9a-fA-F:]+(?:%\S+)?)",
            line, re.IGNORECASE
        )
        if m_v6:
            # Strip trailing annotation like '(Preferred)' or '(Deprecated)'
            addr_raw = re.sub(r"\(.*?\)", "", m_v6.group(1)).strip()
            raw_v6_by_name.setdefault(current["name"], []).append(addr_raw)

    result = [i for i in interfaces if i["ip"]]

    for i in result:
        addrs = raw_v6_by_name.get(i["name"], [])
        g, u, ll = _classify_ipv6_addresses(addrs)
        i["ipv6_global"]    = g
        i["ipv6_ula"]       = u
        i["ipv6_linklocal"] = ll

    return result


def get_interfaces():
    """
    Return a list of interface dicts with at least name + IPv4.

    Each dict now also contains ipv6_global, ipv6_ula, and ipv6_linklocal
    (lists of strings, empty when no addresses of that category exist).

    Windows uses 'ipconfig /all' instead of 'ipconfig' so that the full
    IPv6 address block is available to the parser.
    """
    data = _get_interfaces_netifaces()
    if data is not None:
        return data
    if IS_WINDOWS:
        return _parse_windows_ipconfig(_get_windows_ipconfig())
    if IS_MAC:
        return _parse_mac_ifconfig(run_cmd(["ifconfig", "-a"]))
    out = run_cmd(["ip", "-4", "addr", "show"])
    if out:
        return _parse_linux_ip_addr(out)
    return _parse_mac_ifconfig(run_cmd(["ifconfig", "-a"]))


# ----------------------------------------------------------------------------
# 3. Default gateway
# ----------------------------------------------------------------------------
def get_default_gateway(interfaces):
    """Resolve the default gateway (netifaces → OS tools → assumption)."""
    try:
        import netifaces
        return netifaces.gateways().get("default", {}).get(netifaces.AF_INET, (None,))[0]
    except Exception:
        pass

    if IS_LINUX:
        m = re.search(r"^default\s+via\s+(\S+)", run_cmd(["ip", "route", "show"]), re.M)
        if m:
            return m.group(1)
    if IS_MAC:
        m = re.search(r"^default\s+(\S+)", run_cmd(["netstat", "-rn", "-f", "inet"]), re.M)
        if m:
            return m.group(1)
    if IS_WINDOWS:
        for i in interfaces:
            if i.get("gateway"):
                return i["gateway"]

    # Last resort: assume the first usable address in the primary network.
    for i in interfaces:
        if i.get("prefix"):
            net = ipaddress.ip_network(f"{i['ip']}/{i['prefix']}", strict=False)
            return str(next(net.hosts()))  # typically .1
    return None


def get_default_gateway_ipv6(interfaces):
    """
    Detect the default IPv6 gateway independently of the IPv4 gateway.

    Strategy (same precedence order as the IPv4 function):
      1. netifaces  — gateways()["default"][AF_INET6]  (most accurate)
      2. Linux      — `ip -6 route show`  → `default via <addr>`
      3. macOS      — `netstat -rn -f inet6`  → `default` line
      4. Windows    — scan ipconfig /all output already parsed into
                      interfaces; look for a link-local or global IPv6
                      address on the Default Gateway line

    Returns the gateway as a string (scope-id preserved when present),
    or None if no IPv6 default route is found or all probes fail.

    The existing get_default_gateway() function is NOT modified.
    """
    # --- 1. netifaces (cross-platform, most reliable) ---------------------
    try:
        import netifaces
        gws = netifaces.gateways().get("default", {})
        v6_entry = gws.get(netifaces.AF_INET6)
        if v6_entry:
            return v6_entry[0]   # (gateway_addr, interface_name, is_default)
    except Exception:
        pass

    # --- 2. Linux: ip -6 route show ---------------------------------------
    if IS_LINUX:
        try:
            out = run_cmd(["ip", "-6", "route", "show"])
            # Line format:  default via fe80::1 dev eth0 proto ra ...
            m = re.search(
                r"^default\s+via\s+([0-9a-fA-F:]+(?:%\S+)?)",
                out, re.MULTILINE
            )
            if m:
                return m.group(1)
        except Exception:
            pass

    # --- 3. macOS: netstat -rn -f inet6 -----------------------------------
    if IS_MAC:
        try:
            out = run_cmd(["netstat", "-rn", "-f", "inet6"])
            # Line format:  default   fe80::1%en0   UGcg  en0
            # The gateway may be a link-local with scope-id (%en0).
            m = re.search(
                r"^default\s+([0-9a-fA-F:]+(?:%\S+)?)\s+",
                out, re.MULTILINE
            )
            if m:
                return m.group(1)
        except Exception:
            pass

    # --- 4. Windows: parse ipconfig /all already-collected data -----------
    # The Windows IPv6 gateway is on the 'Default Gateway' line and looks
    # like a link-local (fe80::...) or a global (2xxx::...) address.
    # The IPv4 get_default_gateway() already picks up the dotted-decimal
    # entry from that same line; here we look for the colon-containing one.
    if IS_WINDOWS:
        try:
            out = _get_windows_ipconfig()
            # Windows may list both IPv4 and IPv6 on the same 'Default Gateway'
            # line, or on consecutive lines under the same adapter.
            # We scan every 'Default Gateway' line for a colon (IPv6 indicator).
            for line in out.splitlines():
                line = line.strip()
                m = re.match(
                    r"Default Gateway[^:]*:\s*([0-9a-fA-F:]+(?:%\S+)?)",
                    line, re.IGNORECASE
                )
                if m:
                    candidate = m.group(1).strip()
                    # Must contain a colon to be IPv6 (IPv4 uses dots).
                    if ":" in candidate:
                        return candidate
        except Exception:
            pass

    return None


# ----------------------------------------------------------------------------
# 4. Device discovery (ARP / neighbor table)
# ----------------------------------------------------------------------------
def _parse_arp_line(line):
    """Parse one line of `ip neigh`, `arp -a` or `arp -an` output."""
    # Linux: 192.168.1.10 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
    m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+dev\s+\S+", line)
    if m:
        ip = m.group(1)
        lm = re.search(r"lladdr\s+([0-9a-fA-F:]{17})", line)
        sm = re.search(r"(REACHABLE|STALE|DELAY|PROBE|PERMANENT|NOARP|FAILED|INCOMPLETE)", line)
        return {"ip": ip, "mac": normalize_mac(lm.group(1)) if lm else None,
                "state": sm.group(1) if sm else "unknown"}
    # macOS / BSD: ? (192.168.1.10) at aa:bb:cc:dd:ee:ff on en0 ...
    m = re.match(r"^\?\s+\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([0-9a-fA-F:]+|\(incomplete\))", line)
    if m:
        mac_raw = m.group(2)
        return {"ip": m.group(1), "mac": None if mac_raw == "(incomplete)" else normalize_mac(mac_raw),
                "state": "incomplete" if mac_raw == "(incomplete)" else "reachable"}
    # Windows: 192.168.1.10          aa-bb-cc-dd-ee-ff     dynamic
    m = re.match(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5}|[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\s+(\S+)", line)
    if m and m.group(3).lower() in ("static", "dynamic"):
        return {"ip": m.group(1), "mac": normalize_mac(m.group(2)), "state": m.group(3).lower()}
    return None


def get_neighbor_table():
    """Return {ip: {ip, mac, state}} from the local ARP/neighbor table."""
    devices = {}
    raw = ""
    if not IS_WINDOWS:
        raw = run_cmd(["ip", "neigh", "show"])
    if not raw:
        raw = run_cmd(["arp", "-an"] if IS_MAC else ["arp", "-a"])
    for line in raw.splitlines():
        entry = _parse_arp_line(line)
        if entry and entry["ip"] not in devices:
            devices[entry["ip"]] = entry
    return devices


def ping_sweep(network_str, skip_ips):
    """Send one ICMP echo to every usable host (wakes sleeping devices)."""
    net = ipaddress.ip_network(network_str, strict=False)
    print(f"[*] Ping-sweeping {net} ...", file=sys.stderr)
    swept = 0
    for host in net.hosts():
        ip = str(host)
        if ip in skip_ips:
            continue
        cmd = ["ping", "-n", "1", "-w", "500", ip] if IS_WINDOWS \
            else ["ping", "-c", "1", "-W", "1", ip]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=3)
        except Exception:
            pass
        swept += 1
        if swept % 50 == 0:
            print(f"[*] swept {swept}/{net.num_addresses - 2} hosts", file=sys.stderr)
    print("[*] sweep done", file=sys.stderr)


# ----------------------------------------------------------------------------
# Parallel ping sweep (v1.1)  — original ping_sweep() above is unchanged
# ----------------------------------------------------------------------------
def _parse_ping_latency(output):
    """
    Extract round-trip time from ping stdout on Windows, Linux, and macOS.

    Windows : 'Average = 3ms'  or  'Minimum = 2ms, Maximum = 4ms, Average = 3ms'
    Linux   : 'rtt min/avg/max/mdev = 0.312/0.312/0.312/0.000 ms'
    macOS   : 'round-trip min/avg/max/stddev = 0.312/0.500/0.688/0.152 ms'

    Returns the average (or only) RTT as a float in milliseconds, or None.
    Never raises an exception.
    """
    try:
        # Windows: 'Average = 3ms'  (non-English locales may use comma: '3,2ms')
        m = re.search(r"Average\s*=\s*([\d.,]+)ms", output, re.IGNORECASE)
        if m:
            return float(m.group(1).replace(",", "."))
        # Linux: rtt min/avg/max/mdev = 0.312/0.500/0.688/0.000 ms
        m = re.search(r"rtt [^=]+=\s*[\d.]+/([\d.]+)/", output)
        if m:
            return float(m.group(1))
        # macOS: round-trip min/avg/max/stddev = 0.312/0.500/0.688/0.152 ms
        m = re.search(r"round-trip [^=]+=\s*[\d.]+/([\d.]+)/", output)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def _ping_one(ip):
    """
    Send a single ICMP echo request to *ip* and return a result dict.

    Returns:
        {
            "ip":         str,
            "alive":      bool,
            "latency_ms": float | None,
        }

    Contract:
      * Never raises an exception — any failure produces alive=False, latency=None.
      * Does not modify any shared state (thread-safe by design).
      * Uses a 1-second ping timeout on every platform.
    """
    result = {"ip": ip, "alive": False, "latency_ms": None}
    try:
        if IS_WINDOWS:
            # -n 1  : one packet   -w 1000 : 1000 ms timeout
            cmd = ["ping", "-n", "1", "-w", "1000", ip]
        elif IS_MAC:
            # macOS >=13 (Ventura) changed -W to milliseconds;
            # -t N is the portable seconds-based deadline on all macOS versions.
            cmd = ["ping", "-c", "1", "-t", "1", ip]
        else:
            # Linux: -W N = N-second deadline
            cmd = ["ping", "-c", "1", "-W", "1", ip]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            text=True,
            errors="replace",
            check=False,
        )
        if proc.returncode == 0:
            result["alive"]      = True
            result["latency_ms"] = _parse_ping_latency(proc.stdout)
    except Exception:
        pass   # timeout, permission error, or any OS failure → dead
    return result


def ping_sweep_parallel(network_str, skip_ips):
    """
    Concurrent ping sweep using ThreadPoolExecutor.

    Sends one ICMP echo to every usable host in *network_str*, excluding
    any IP in *skip_ips* (typically the machine's own addresses).

    Args:
        network_str : CIDR string, e.g. '192.168.1.0/24'
        skip_ips    : set of IP strings to skip

    Returns:
        {
            "active_hosts" : list of result dicts (ip, alive, latency_ms),
                             sorted by IP, alive hosts only
            "scan_time"    : float seconds (wall-clock)
            "alive_count"  : int
            "dead_count"   : int
        }

    Thread safety:
        _ping_one() is pure — it never writes to shared data.  All result
        dicts are produced inside worker threads and collected by the main
        thread via futures.  No locking is required.
    """
    net = ipaddress.ip_network(network_str, strict=False)
    targets = [str(h) for h in net.hosts() if str(h) not in skip_ips]

    total = len(targets)
    print(f"[*] Parallel ping sweep of {net} ({total} hosts, "
          f"{PING_MAX_WORKERS} workers) ...", file=sys.stderr)

    t0 = time.perf_counter()
    all_results = []

    with ThreadPoolExecutor(max_workers=PING_MAX_WORKERS) as pool:
        futures = {pool.submit(_ping_one, ip): ip for ip in targets}
        done = 0
        # as_completed yields futures as they finish — gives smooth progress
        # and marginally faster collection than iterating in submission order.
        for fut in as_completed(futures):
            try:
                all_results.append(fut.result())
            except Exception:
                # A worker raised unexpectedly — count as dead, keep going
                all_results.append({"ip": futures[fut],
                                     "alive": False, "latency_ms": None})
            done += 1
            if done % 50 == 0:
                print(f"[*] {done}/{total} responses collected", file=sys.stderr)

    elapsed = time.perf_counter() - t0
    print(f"[*] sweep done in {elapsed:.1f}s", file=sys.stderr)

    # Sort deterministically by IP numerical value
    all_results.sort(
        key=lambda r: tuple(int(x) for x in r["ip"].split("."))
    )

    alive      = [r for r in all_results if r["alive"]]
    dead_count = sum(1 for r in all_results if not r["alive"])  # avoid building dead list

    return {
        "active_hosts": alive,
        "scan_time":    round(elapsed, 3),
        "alive_count":  len(alive),
        "dead_count":   dead_count,
    }


def get_network_health(gateway_ip):
    """
    Check network connectivity to default gateway and Internet target (8.8.8.8).

    Reuses _ping_one() to perform single ICMP pings without duplicating logic.

    Status calculation:
      - Healthy     : Gateway reachable AND Internet reachable
      - No Internet : Gateway reachable AND Internet unreachable
      - No Gateway  : Gateway missing/unreachable AND Internet reachable
      - Offline     : Neither gateway nor Internet reachable
    """
    gw_res = _ping_one(gateway_ip) if gateway_ip else {"alive": False, "latency_ms": None}
    inet_res = _ping_one(HEALTH_INTERNET_TARGET)

    gw_ok = gw_res["alive"]
    inet_ok = inet_res["alive"]

    if gw_ok and inet_ok:
        status = "Healthy"
    elif gw_ok and not inet_ok:
        status = "No Internet"
    elif not gw_ok and inet_ok:
        status = "No Gateway"
    else:
        status = "Offline"

    return {
        "gateway_reachable": gw_ok,
        "gateway_rtt_ms": gw_res["latency_ms"],
        "internet_reachable": inet_ok,
        "internet_rtt_ms": inet_res["latency_ms"],
        "status": status,
    }


def _get_dns_servers():
    """
    Extract system-configured DNS servers on Windows, Linux, and macOS.
    Returns a unique list of IP strings (IPv4 and IPv6), preserving order.
    Never raises an exception.
    """
    servers = []

    try:
        if IS_WINDOWS:
            out = _get_windows_ipconfig()
            in_dns_block = False
            for line in out.splitlines():
                if "DNS Servers" in line:
                    in_dns_block = True
                    parts = line.split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        ip = parts[1].strip()
                        if ip and ip not in servers:
                            servers.append(ip)
                elif in_dns_block:
                    # Windows indents subsequent DNS server IPs under the same adapter
                    stripped = line.strip()
                    if stripped and not ":" in line and re.match(r"^[0-9a-fA-F:\.]+$", stripped):
                        if stripped not in servers:
                            servers.append(stripped)
                    elif ":" in line and not re.match(r"^[0-9a-fA-F:\.]+$", stripped):
                        # Reached next field header (e.g. 'NetBIOS over Tcpip . . .')
                        in_dns_block = False
        elif IS_MAC:
            out = run_cmd(["scutil", "--dns"])
            for line in out.splitlines():
                m = re.search(r"nameserver\[\d+\]\s*:\s*(\S+)", line)
                if m:
                    ip = m.group(1).strip()
                    if ip and ip not in servers:
                        servers.append(ip)
        else:
            # Linux & fallback: read /etc/resolv.conf
            content = ""
            try:
                with open("/etc/resolv.conf", "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception:
                content = run_cmd(["cat", "/etc/resolv.conf"])

            for line in content.splitlines():
                line = line.strip()
                if line.startswith("#") or line.startswith(";"):
                    continue
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        ip = parts[1].strip()
                        if ip and ip not in servers:
                            servers.append(ip)
    except Exception:
        pass

    return servers


def _measure_dns_lookup(target=DNS_TEST_TARGET):
    """
    Measure DNS resolution time using socket.getaddrinfo().
    Returns {'success': bool, 'lookup_ms': float | None}.
    Never raises an exception.
    """
    try:
        t0 = time.perf_counter()
        socket.getaddrinfo(target, None)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {"success": True, "lookup_ms": round(elapsed_ms, 2)}
    except Exception:
        return {"success": False, "lookup_ms": None}


def get_dns_info():
    """
    Gather DNS configuration and resolution performance.
    """
    servers = _get_dns_servers()
    lookup = _measure_dns_lookup(DNS_TEST_TARGET)

    primary = servers[0] if len(servers) > 0 else None
    secondary = servers[1] if len(servers) > 1 else None

    return {
        "primary_dns": primary,
        "secondary_dns": secondary,
        "all_servers": servers,
        "resolver": "System",
        "lookup_target": DNS_TEST_TARGET,
        "lookup_ms": lookup["lookup_ms"],
        "success": lookup["success"],
    }


# ----------------------------------------------------------------------------
# Wi-Fi Information (v1.4)
# ----------------------------------------------------------------------------
def _freq_or_channel_to_band(freq_mhz=None, channel=None):
    if freq_mhz:
        try:
            f = int(freq_mhz)
            if 2400 <= f <= 2500:
                return "2.4 GHz"
            if 4900 <= f <= 5895:
                return "5 GHz"
            if 5925 <= f <= 7125:
                return "6 GHz"
        except (ValueError, TypeError):
            pass
    if channel:
        try:
            ch = int(channel)
            if 1 <= ch <= 14:
                return "2.4 GHz"
            if 32 <= ch <= 177:
                return "5 GHz"
            if 1 <= ch <= 233 and freq_mhz and int(freq_mhz) > 5900:
                return "6 GHz"
        except (ValueError, TypeError):
            pass
    return None


def _get_wifi_windows():
    out = run_cmd(["netsh", "wlan", "show", "interfaces"])
    if not out or "State" not in out:
        return None

    ssid, bssid, security, phy = None, None, None, None
    channel, link_speed, signal_pct, signal_dbm = None, None, None, None
    connected = False

    for line in out.splitlines():
        line_str = line.strip()
        if not line_str or ":" not in line_str:
            continue
        k, v = [p.strip() for p in line_str.split(":", 1)]

        if k == "State":
            connected = (v.lower() == "connected")
        elif k == "SSID":
            ssid = v if v else None
        elif k == "BSSID":
            bssid = normalize_mac(v) if v else None
        elif k == "Authentication":
            security = v if v else None
        elif k == "Radio type":
            phy = v if v else None
        elif k == "Channel":
            try:
                channel = int(v)
            except ValueError:
                pass
        elif k in ("Receive rate (Mbps)", "Transmit rate (Mbps)") and link_speed is None:
            try:
                link_speed = float(v)
            except ValueError:
                pass
        elif k == "Signal":
            try:
                signal_pct = int(v.rstrip("%"))
                signal_dbm = int((signal_pct / 2) - 100)
            except ValueError:
                pass

    if not connected or not ssid:
        return None

    band = _freq_or_channel_to_band(channel=channel)

    return {
        "connected": True,
        "ssid": ssid,
        "bssid": bssid,
        "security": security,
        "band": band,
        "channel": channel,
        "frequency_mhz": None,
        "signal_percent": signal_pct,
        "signal_dbm": signal_dbm,
        "link_speed_mbps": link_speed,
        "phy": phy,
    }


def _get_wifi_mac_os():
    airport_path = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
    out = run_cmd([airport_path, "-I"])
    if not out or "SSID" not in out:
        return None

    ssid, bssid, security = None, None, None
    channel, link_speed, rssi = None, None, None

    for line in out.splitlines():
        line_str = line.strip()
        if not line_str or ":" not in line_str:
            continue
        k, v = [p.strip() for p in line_str.split(":", 1)]

        if k == "SSID":
            ssid = v if v else None
        elif k == "BSSID":
            bssid = normalize_mac(v) if v else None
        elif k in ("link auth", "802.11 auth"):
            if not security or security == "open":
                security = v if v else None
        elif k == "channel":
            try:
                channel = int(v.split(",")[0])
            except ValueError:
                pass
        elif k == "lastTxRate":
            try:
                link_speed = float(v)
            except ValueError:
                pass
        elif k == "agrCtlRSSI":
            try:
                rssi = int(v)
            except ValueError:
                pass

    if not ssid:
        return None

    signal_pct = min(max(2 * (rssi + 100), 0), 100) if rssi is not None else None
    band = _freq_or_channel_to_band(channel=channel)

    return {
        "connected": True,
        "ssid": ssid,
        "bssid": bssid,
        "security": security,
        "band": band,
        "channel": channel,
        "frequency_mhz": None,
        "signal_percent": signal_pct,
        "signal_dbm": rssi,
        "link_speed_mbps": link_speed,
        "phy": None,
    }


def _get_wifi_linux():
    # 1. Try nmcli
    nm_out = run_cmd(["nmcli", "-t", "-f", "active,ssid,bssid,chan,rate,signal,security", "dev", "wifi"])
    if nm_out:
        for line in nm_out.splitlines():
            if line.startswith("yes:"):
                parts = line.split(":")
                if len(parts) >= 7:
                    ssid = parts[1] if parts[1] else None
                    bssid_raw = parts[2].replace(r"\:", ":")
                    bssid = normalize_mac(bssid_raw)
                    try:
                        chan = int(parts[3])
                    except ValueError:
                        chan = None
                    rate_str = parts[4]
                    rate_m = re.search(r"([\d.]+)", rate_str)
                    link_speed = float(rate_m.group(1)) if rate_m else None
                    try:
                        sig_pct = int(parts[5])
                        sig_dbm = int((sig_pct / 2) - 100)
                    except ValueError:
                        sig_pct, sig_dbm = None, None
                    sec = parts[6] if parts[6] else None
                    return {
                        "connected": True,
                        "ssid": ssid,
                        "bssid": bssid,
                        "security": sec,
                        "band": _freq_or_channel_to_band(channel=chan),
                        "channel": chan,
                        "frequency_mhz": None,
                        "signal_percent": sig_pct,
                        "signal_dbm": sig_dbm,
                        "link_speed_mbps": link_speed,
                        "phy": None,
                    }

    # 2. Fallback to iwconfig
    iw_out = run_cmd(["iwconfig"])
    if iw_out and "ESSID:" in iw_out:
        m_ssid = re.search(r'ESSID:"([^"]+)"', iw_out)
        if m_ssid and m_ssid.group(1) != "off/any":
            ssid = m_ssid.group(1)
            m_ap = re.search(r"Access Point:\s*([0-9a-fA-F:-]+)", iw_out)
            bssid = normalize_mac(m_ap.group(1)) if m_ap else None
            m_freq = re.search(r"Frequency:([\d.]+)\s*GHz", iw_out)
            freq_mhz = int(float(m_freq.group(1)) * 1000) if m_freq else None
            m_rate = re.search(r"Bit Rate=([\d.]+)\s*Mb/s", iw_out)
            link_speed = float(m_rate.group(1)) if m_rate else None
            m_sig = re.search(r"Signal level=(-?\d+)\s*dBm", iw_out)
            sig_dbm = int(m_sig.group(1)) if m_sig else None
            sig_pct = min(max(2 * (sig_dbm + 100), 0), 100) if sig_dbm is not None else None
            return {
                "connected": True,
                "ssid": ssid,
                "bssid": bssid,
                "security": None,
                "band": _freq_or_channel_to_band(freq_mhz=freq_mhz),
                "channel": None,
                "frequency_mhz": freq_mhz,
                "signal_percent": sig_pct,
                "signal_dbm": sig_dbm,
                "link_speed_mbps": link_speed,
                "phy": None,
            }

    return None


def get_wifi_information():
    """
    Collect Wi-Fi information for the currently connected wireless interface.
    Returns structured dict. Never raises an exception.
    """
    default_info = {
        "connected": False,
        "ssid": None,
        "bssid": None,
        "security": None,
        "band": None,
        "channel": None,
        "frequency_mhz": None,
        "signal_percent": None,
        "signal_dbm": None,
        "link_speed_mbps": None,
        "phy": None,
    }
    try:
        if IS_WINDOWS:
            info = _get_wifi_windows()
        elif IS_MAC:
            info = _get_wifi_mac_os()
        else:
            info = _get_wifi_linux()
        return info if info else default_info
    except Exception:
        return default_info


# ----------------------------------------------------------------------------
# Snapshot Save & Compare (v1.5)
# ----------------------------------------------------------------------------
def save_snapshot(report, filename):
    """
    Save the current report dictionary as formatted JSON to filename.
    Returns True on success, False on error. Never raises exceptions.
    """
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"[*] Snapshot saved to {filename}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[!] Failed to save snapshot to {filename}: {e}", file=sys.stderr)
        return False


def load_snapshot(filename):
    """
    Load a saved report snapshot dictionary from filename.
    Returns dict or None if invalid or missing. Never raises exceptions.
    """
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def compare_reports(old_report, new_report):
    """
    Compare two report dictionaries and detect differences.

    Returns structured dict with 'changes' and 'summary'.
    Never raises exceptions.
    """
    changes = {}

    # Scalar field comparison helper
    def _cmp_scalar(key_name, old_val, new_val):
        if old_val != new_val:
            changes[key_name] = {"old": old_val, "new": new_val}

    old_r = old_report or {}
    new_r = new_report or {}

    _cmp_scalar("public_ip", old_r.get("public_ip"), new_r.get("public_ip"))
    _cmp_scalar("public_ipv6", old_r.get("public_ipv6"), new_r.get("public_ipv6"))
    _cmp_scalar("default_gateway", old_r.get("default_gateway"), new_r.get("default_gateway"))
    _cmp_scalar("default_gateway_ipv6", old_r.get("default_gateway_ipv6"), new_r.get("default_gateway_ipv6"))
    _cmp_scalar("primary_private_ip", old_r.get("primary_private_ip"), new_r.get("primary_private_ip"))

    # Health
    old_nh = old_r.get("network_health") or {}
    new_nh = new_r.get("network_health") or {}
    _cmp_scalar("health_status", old_nh.get("status"), new_nh.get("status"))

    # DNS
    old_dns = old_r.get("dns_information") or {}
    new_dns = new_r.get("dns_information") or {}
    _cmp_scalar("primary_dns", old_dns.get("primary_dns"), new_dns.get("primary_dns"))
    _cmp_scalar("secondary_dns", old_dns.get("secondary_dns"), new_dns.get("secondary_dns"))

    # Wi-Fi
    old_wf = old_r.get("wifi_information") or {}
    new_wf = new_r.get("wifi_information") or {}
    _cmp_scalar("wifi_ssid", old_wf.get("ssid"), new_wf.get("ssid"))
    _cmp_scalar("wifi_bssid", old_wf.get("bssid"), new_wf.get("bssid"))
    _cmp_scalar("wifi_signal_percent", old_wf.get("signal_percent"), new_wf.get("signal_percent"))

    # Device Comparison
    old_devs = {d["ip"]: d for d in old_r.get("devices", []) if isinstance(d, dict) and d.get("ip")}
    new_devs = {d["ip"]: d for d in new_r.get("devices", []) if isinstance(d, dict) and d.get("ip")}

    added_devs = []
    for ip, d in new_devs.items():
        if ip not in old_devs:
            added_devs.append({"ip": ip, "mac": d.get("mac"), "hostname": d.get("hostname")})

    removed_devs = []
    for ip, d in old_devs.items():
        if ip not in new_devs:
            removed_devs.append({"ip": ip, "mac": d.get("mac"), "hostname": d.get("hostname")})

    if added_devs:
        changes["devices_added"] = added_devs
    if removed_devs:
        changes["devices_removed"] = removed_devs

    total_changes = len(changes)

    return {
        "changes": changes,
        "summary": {
            "total_changes": total_changes,
            "devices_added_count": len(added_devs),
            "devices_removed_count": len(removed_devs),
        },
    }


# ----------------------------------------------------------------------------
# 5. Enrichment: reverse DNS + MAC vendor
# ----------------------------------------------------------------------------
def reverse_dns(ip):
    try:
        name = socket.gethostbyaddr(ip)[0]
        return name.rstrip(".") if name else None
    except Exception:
        return None


def vendor_from_oui(mac):
    if not mac:
        return None
    return COMMON_OUI.get(mac[:8], "Unknown")


def vendor_from_online(mac):
    try:
        text = http_get(f"https://api.macvendors.com/{mac}")
        if text and text.lower() != "not found":
            return text
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------------
# Report assembly
# ----------------------------------------------------------------------------
def collect_report(args):
    global _WINDOWS_IPCONFIG_CACHE
    _WINDOWS_IPCONFIG_CACHE = None   # reset cache for fresh system state on each run

    report = {}

    # Public side
    pub = get_public_ipv4()
    report["public_ip"]      = pub
    report["public_details"] = get_public_ip_details(pub) if pub else {}
    report["public_ipv6"]    = get_public_ipv6()          # None when no IPv6 path

    # Local interfaces
    interfaces = get_interfaces()
    primary = get_primary_private_ip()
    for iface in interfaces:
        ip, prefix = iface["ip"], iface.get("prefix")
        if prefix is None:
            iface["prefix_note"] = "assumed /24 (netmask not reported)"
            prefix = 24
        try:
            net = ipaddress.ip_interface(f"{ip}/{prefix}").network
            iface["cidr"]              = str(net)
            iface["network_address"]   = str(net.network_address)
            iface["broadcast_address"] = str(net.broadcast_address)
            iface["usable_hosts"]      = max(net.num_addresses - 2, 0)
        except ValueError:
            iface["cidr"] = None
        iface["is_primary"] = (ip == primary)
    report["interfaces"]          = interfaces
    report["primary_private_ip"]  = primary
    report["default_gateway"]     = get_default_gateway(interfaces)
    report["default_gateway_ipv6"] = get_default_gateway_ipv6(interfaces)

    # Device census
    devices = get_neighbor_table()
    sweep_results = {}   # populated only when --sweep is used
    if args.sweep:
        target = None
        for i in interfaces:
            if i.get("is_primary") and i.get("cidr"):
                target = i["cidr"]
                break
        if target is None and interfaces:
            target = interfaces[0].get("cidr")
        if target:
            skip = {i["ip"] for i in interfaces}
            skip.discard(None)
            sweep_results = ping_sweep_parallel(target, skip)
            devices = get_neighbor_table()   # refresh ARP table after sweep

    device_list = []
    for ip, d in devices.items():
        mac = d.get("mac")
        if not mac:
            continue                                   # incomplete entry
        if mac.startswith(("01:00:5E", "FF:FF:FF", "01:00:0C")):
            continue                                   # multicast/broadcast
        device_list.append({
            "ip":       ip,
            "mac":      mac,
            "hostname": None if args.no_dns else reverse_dns(ip),
            "vendor":   vendor_from_online(mac) if args.vendors else vendor_from_oui(mac),
            "state":    d.get("state"),
        })
    device_list.sort(key=lambda x: tuple(int(p) for p in x["ip"].split(".")))
    report["devices"]         = device_list
    report["device_count"]    = len(device_list)
    report["sweep_performed"] = bool(args.sweep)
    report["active_hosts"] = sweep_results.get("active_hosts", [])
    report["scan_time"]    = sweep_results.get("scan_time",    None)
    report["alive_count"]  = sweep_results.get("alive_count",  None)
    report["dead_count"]   = sweep_results.get("dead_count",   None)

    # Network Health check (v1.2)
    report["network_health"] = get_network_health(report.get("default_gateway"))

    # DNS Information check (v1.3)
    report["dns_information"] = get_dns_info()

    # Wi-Fi Information check (v1.4)
    report["wifi_information"] = get_wifi_information()

    # Snapshot Comparison (v1.5)
    if getattr(args, "compare", None):
        old_snapshot = load_snapshot(args.compare)
        if old_snapshot:
            report["comparison"] = compare_reports(old_snapshot, report)
        else:
            report["comparison"] = {
                "error": f"Failed to load snapshot file '{args.compare}'",
                "changes": {},
                "summary": {"total_changes": 0, "devices_added_count": 0, "devices_removed_count": 0},
            }

    return report


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
def pretty_print(report, colors=None):
    c = colors or Colors(enabled=False)
    W = 72
    print(c.BOLD + c.CYAN + "=" * W + c.RESET)
    print(c.BOLD + c.CYAN + " NETWORK INFORMATION TOOLKIT" + c.RESET)
    print(c.BOLD + c.CYAN + "=" * W + c.RESET)

    pub = report.get("public_ip")
    print(f"\n{c.BOLD}{c.CYAN}[ Public IP ]{c.RESET}")
    if pub:
        print(f"  Public IPv4       : {c.CYAN}{pub}{c.RESET}   (dynamic? reboot your modem to test)")
        det = report.get("public_details") or {}
        for key, label in (("org", "ISP"), ("hostname", "Hostname"), ("city", "City"),
                           ("region", "Region"), ("country", "Country"), ("timezone", "Timezone")):
            if det.get(key):
                print(f"  {label:<17}: {det[key]}")
    else:
        print("  (no public IP reachable - are you offline?)")
    # IPv6 public address — shown regardless of IPv4 status
    pub6 = report.get("public_ipv6")
    print(f"  Public IPv6       : {c.MAGENTA if pub6 else ''}{pub6 if pub6 else 'n/a'}{c.RESET}")

    print(f"\n{c.BOLD}{c.CYAN}[ Local Network ]{c.RESET}")
    print(f"  Default gateway   : {c.BLUE}{report.get('default_gateway') or 'unknown'}{c.RESET}")
    gw6 = report.get("default_gateway_ipv6")
    print(f"  IPv6 gateway      : {c.MAGENTA if gw6 else ''}{gw6 if gw6 else 'n/a'}{c.RESET}")
    for i in report.get("interfaces", []):
        tag = f"   {c.GREEN}(primary){c.RESET}" if i.get("is_primary") else ""
        print(f"  Interface         : {c.BOLD}{i['name']}{c.RESET}{tag}")
        print(f"    IPv4 address    : {c.CYAN}{i['ip']}{c.RESET}")
        print(f"    CIDR            : {i.get('cidr') or 'n/a'}")
        print(f"    Network address : {i.get('network_address') or 'n/a'}")
        print(f"    Broadcast       : {i.get('broadcast_address') or i.get('broadcast') or 'n/a'}")
        print(f"    Usable hosts    : {i.get('usable_hosts', 'n/a')}")
        if i.get("prefix_note"):
            print(f"    (note)          : {i['prefix_note']}")
        # IPv6 — always printed; n/a when the list is empty
        v6g  = ", ".join(i.get("ipv6_global", []))    or "n/a"
        v6u  = ", ".join(i.get("ipv6_ula", []))       or "n/a"
        v6ll = ", ".join(i.get("ipv6_linklocal", [])) or "n/a"
        print(f"    IPv6 Global     : {c.MAGENTA if v6g != 'n/a' else ''}{v6g}{c.RESET}")
        print(f"    IPv6 ULA        : {v6u}")
        print(f"    IPv6 Link-local : {v6ll}")

    devices = report.get("devices", [])
    sweep_note = f"  {c.GRAY}[after ping sweep]{c.RESET}" if report.get("sweep_performed") else ""
    print(f"\n{c.BOLD}{c.CYAN}[ Devices On LAN ]{c.RESET}  {c.BOLD}{report.get('device_count', 0)}{c.RESET} found{sweep_note}")
    if devices:
        print(f"  {c.DIM}{'IP':<15} {'MAC':<19} {'Vendor':<14} Hostname{c.RESET}")
        print("  " + "-" * 62)
        for d in devices:
            host = d.get("hostname") or "-"
            print(f"  {d['ip']:<15} {d['mac']:<19} {str(d.get('vendor') or '-'):<14} {host}")
    else:
        print("  none found - try --sweep to wake sleeping hosts")

    # [ Active Hosts ] section — only shown when --sweep was used
    if report.get("sweep_performed"):
        alive  = report.get("active_hosts", [])
        a_cnt  = report.get("alive_count", 0)
        d_cnt  = report.get("dead_count",  0)
        s_time = report.get("scan_time")
        s_str  = f"{s_time:.1f}s" if s_time is not None else "n/a"
        total  = (a_cnt or 0) + (d_cnt or 0)
        print(f"\n{c.BOLD}{c.CYAN}[ Active Hosts ]{c.RESET}  {c.GREEN}{a_cnt} alive{c.RESET} / {total} scanned  "
              f"(scan time: {s_str})")
        if alive:
            print(f"  {c.DIM}{'IP':<15} Latency{c.RESET}")
            print("  " + "-" * 28)
            for h in alive:
                lat = h.get("latency_ms")
                lat_str = f"{lat:.1f} ms" if lat is not None else "< 1 ms"
                print(f"  {h['ip']:<15} {c.GREEN}{lat_str}{c.RESET}")
        else:
            print("  (no hosts responded to ICMP — firewall may be blocking pings)")

    # [ Network Health ] section (v1.2)
    nh = report.get("network_health")
    if nh:
        print(f"\n{c.BOLD}{c.CYAN}[ Network Health ]{c.RESET}")
        gw_rtt = f"{nh['gateway_rtt_ms']:.1f} ms" if nh.get("gateway_rtt_ms") is not None else "n/a"
        inet_rtt = f"{nh['internet_rtt_ms']:.1f} ms" if nh.get("internet_rtt_ms") is not None else "n/a"
        st = nh.get("status", "n/a")
        st_color = c.GREEN if st == "Healthy" else (c.YELLOW if st in ("No Internet", "No Gateway") else c.RED)
        print(f"  Gateway Reachable : {'Yes' if nh.get('gateway_reachable') else 'No'}")
        print(f"  Gateway RTT       : {gw_rtt}")
        print(f"  Internet Reachable: {'Yes' if nh.get('internet_reachable') else 'No'}")
        print(f"  Internet RTT      : {inet_rtt}")
        print(f"  Overall Status    : {st_color}{st}{c.RESET}")

    # [ DNS Information ] section (v1.3)
    dns_info = report.get("dns_information")
    if dns_info:
        print(f"\n{c.BOLD}{c.CYAN}[ DNS Information ]{c.RESET}")
        p_dns = dns_info.get("primary_dns") or "n/a"
        s_dns = dns_info.get("secondary_dns") or "n/a"
        l_target = dns_info.get("lookup_target") or "n/a"
        l_ms = f"{dns_info['lookup_ms']:.1f} ms" if dns_info.get("lookup_ms") is not None else "n/a"
        status_ok = dns_info.get("success")
        status_str = f"{c.GREEN}OK{c.RESET}" if status_ok else f"{c.RED}Failed{c.RESET}"
        print(f"  Primary DNS       : {p_dns}")
        print(f"  Secondary DNS     : {s_dns}")
        print(f"  Resolver          : {dns_info.get('resolver', 'System')}")
        print(f"  Lookup Target     : {l_target}")
        print(f"  Lookup Time       : {l_ms}")
        print(f"  Status            : {status_str}")

    # [ Wi-Fi Information ] section (v1.4)
    wifi_info = report.get("wifi_information")
    if wifi_info:
        print(f"\n{c.BOLD}{c.CYAN}[ Wi-Fi Information ]{c.RESET}")
        if wifi_info.get("connected"):
            chan_str = str(wifi_info.get("channel")) if wifi_info.get("channel") is not None else "n/a"
            if wifi_info.get("frequency_mhz"):
                chan_str += f"  ({wifi_info['frequency_mhz']} MHz)"
            sig_str = "n/a"
            if wifi_info.get("signal_percent") is not None:
                sig_str = f"{wifi_info['signal_percent']}%"
                if wifi_info.get("signal_dbm") is not None:
                    sig_str += f"  ({wifi_info['signal_dbm']} dBm)"
            elif wifi_info.get("signal_dbm") is not None:
                sig_str = f"{wifi_info['signal_dbm']} dBm"

            speed_str = f"{wifi_info['link_speed_mbps']:.0f} Mbps" if wifi_info.get("link_speed_mbps") is not None else "n/a"

            print(f"  SSID              : {c.GREEN}{wifi_info.get('ssid') or 'n/a'}{c.RESET}")
            print(f"  BSSID             : {wifi_info.get('bssid') or 'n/a'}")
            print(f"  Security          : {wifi_info.get('security') or 'n/a'}")
            print(f"  Band              : {wifi_info.get('band') or 'n/a'}")
            print(f"  Channel           : {chan_str}")
            print(f"  Signal Strength   : {c.GREEN}{sig_str}{c.RESET}")
            print(f"  Link Speed        : {speed_str}")
            print(f"  PHY Standard      : {wifi_info.get('phy') or 'n/a'}")
        else:
            print("  Status            : Disconnected / Unavailable")

    # [ Snapshot Comparison ] section (v1.5)
    cmp_data = report.get("comparison")
    if cmp_data:
        print(f"\n{c.BOLD}{c.CYAN}[ Snapshot Comparison ]{c.RESET}")
        if "error" in cmp_data:
            print(f"  Status            : {c.RED}Error ({cmp_data['error']}){c.RESET}")
        else:
            changes = cmp_data.get("changes", {})
            summary = cmp_data.get("summary", {})
            tot = summary.get("total_changes", 0)
            print(f"  Total Changes     : {tot}")

            if not changes:
                print("  State             : No changes detected (identical to snapshot)")
            else:
                for k, v in changes.items():
                    if k in ("devices_added", "devices_removed"):
                        continue
                    label = k.replace("_", " ").title()
                    old_v = v.get("old") if v.get("old") is not None else "n/a"
                    new_v = v.get("new") if v.get("new") is not None else "n/a"
                    print(f"  {label:<18}: {old_v}  →  {new_v}")

                added = changes.get("devices_added", [])
                removed = changes.get("devices_removed", [])
                if added or removed:
                    print("  Devices:")
                    for d in added:
                        host = f" ({d['hostname']})" if d.get("hostname") else ""
                        mac = f" [{d['mac']}]" if d.get("mac") else ""
                        print(f"    {c.GREEN}+ Added         : {d['ip']}{mac}{host}{c.RESET}")
                    for d in removed:
                        host = f" ({d['hostname']})" if d.get("hostname") else ""
                        mac = f" [{d['mac']}]" if d.get("mac") else ""
                        print(f"    {c.RED}- Removed       : {d['ip']}{mac}{host}{c.RESET}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Network Information Toolkit (netinfo) — Fast, zero-dependency network CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--json", action="store_true", help="output machine-readable JSON")
    parser.add_argument("--sweep", action="store_true", help="perform parallel ping sweep before listing devices")
    parser.add_argument("--vendors", action="store_true", help="lookup MAC OUI vendors online (api.macvendors.com)")
    parser.add_argument("--no-dns", action="store_true", help="skip reverse-DNS hostname resolution")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI color output")
    parser.add_argument("--save", metavar="FILE", help="save report snapshot to JSON file")
    parser.add_argument("--compare", metavar="FILE", help="compare report against a saved snapshot file")
    parser.add_argument("--version", action="version", version="netinfo 2.0.0")
    args = parser.parse_args()

    colors = _init_colors(args)

    try:
        report = collect_report(args)

        if args.save:
            save_snapshot(report, args.save)

        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            pretty_print(report, colors=colors)
    except KeyboardInterrupt:
        print(f"\n{colors.YELLOW}[!] Aborted by user.{colors.RESET}", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"{colors.RED}[!] Error: {e}{colors.RESET}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


# save as netinfo.py, then:
#python3 netinfo.py            # normal report
#python3 netinfo.py --sweep    # ping-sweep first — finds sleeping Wi-Fi devices
#python3 netinfo.py --json | jq .   # parse programmatically
#python3 netinfo.py --vendors  # online vendor lookup for unknown MACs