import os
import sys

import pytest

# Add parent directory to path to import netinfo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import netinfo


class TestNormalizeMac:
    @pytest.mark.parametrize("input_mac,expected", [
        ("00:1B:44:11:22:33", "00:1B:44:11:22:33"),
        ("00-1b-44-11-22-33", "00:1B:44:11:22:33"),
        ("001b.4411.2233", "00:1B:44:11:22:33"),
        ("001b44112233", "00:1B:44:11:22:33"),
        ("8:0:27:1:2:3", "08:00:27:01:02:03"),
        ("8:0:27:12:34:56", "08:00:27:12:34:56"),
        ("AA-bb:CC-dd:EE-ff", "AA:BB:CC:DD:EE:FF"),
        ("  00:11:22:33:44:55  ", "00:11:22:33:44:55"),
        ("0:0:0:0:0:0", "00:00:00:00:00:00"),
        ("f:f:f:f:f:f", "0F:0F:0F:0F:0F:0F"),
    ])
    def test_valid_mac_formats(self, input_mac, expected):
        assert netinfo.normalize_mac(input_mac) == expected

    @pytest.mark.parametrize("invalid_mac", [
        "", None, "12345", "00:11:22:33:44", "00:11:22:33:44:55:66",
        "GG:HH:II:JJ:KK:LL", "0011.2233.4455.6677", "aa.bb.cc.dd.ee.ff",
        "001B4411223", "001B441122334"
    ])
    def test_invalid_mac_formats(self, invalid_mac):
        assert netinfo.normalize_mac(invalid_mac) is None


class TestIPv6Classification:
    def test_classify_ipv6(self):
        addrs = [
            "2001:db8::1",
            "fd12:3456:789a::1",
            "fe80::1234%eth0",
            "::1",
            "ff02::1",
            "invalid_ipv6",
        ]
        g, u, ll = netinfo._classify_ipv6_addresses(addrs)
        assert g == ["2001:db8::1"]
        assert u == ["fd12:3456:789a::1"]
        assert ll == ["fe80::1234%eth0"]


class TestParsers:
    def test_parse_windows_ipconfig(self, windows_ipconfig_output):
        ifaces = netinfo._parse_windows_ipconfig(windows_ipconfig_output)
        assert len(ifaces) == 1
        assert ifaces[0]["name"] == "Wi-Fi"
        assert ifaces[0]["ip"] == "192.168.1.50"
        assert ifaces[0]["prefix"] == 24
        assert ifaces[0]["gateway"] == "192.168.1.1"
        assert "2001:db8::1234" in ifaces[0]["ipv6_global"]

    def test_parse_mac_ifconfig(self, macos_ifconfig_output):
        ifaces = netinfo._parse_mac_ifconfig(macos_ifconfig_output)
        assert len(ifaces) == 1
        assert ifaces[0]["name"] == "en0"
        assert ifaces[0]["ip"] == "192.168.1.50"
        assert ifaces[0]["prefix"] == 24
        assert "2001:db8::5678" in ifaces[0]["ipv6_global"]

    def test_parse_linux_ip_addr(self, linux_ip_addr_output, linux_ip6_addr_output, monkeypatch):
        monkeypatch.setattr(netinfo, "run_cmd", lambda cmd: linux_ip6_addr_output if "-6" in cmd else "")
        ifaces = netinfo._parse_linux_ip_addr(linux_ip_addr_output)
        assert len(ifaces) == 1
        assert ifaces[0]["name"] == "eth0"
        assert ifaces[0]["ip"] == "192.168.1.50"
        assert ifaces[0]["prefix"] == 24

    def test_parse_arp_line(self):
        # Linux format
        res = netinfo._parse_arp_line("192.168.1.10 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE")
        assert res == {"ip": "192.168.1.10", "mac": "00:11:22:33:44:55", "state": "REACHABLE"}

        # macOS standard format
        res = netinfo._parse_arp_line("? (192.168.1.1) at 00:50:56:ab:cd:ef on en0 ifscope [ethernet]")
        assert res == {"ip": "192.168.1.1", "mac": "00:50:56:AB:CD:EF", "state": "reachable"}

        # macOS unpadded format
        res = netinfo._parse_arp_line("? (192.168.1.20) at 8:0:27:12:34:56 on en0 ifscope [ethernet]")
        assert res == {"ip": "192.168.1.20", "mac": "08:00:27:12:34:56", "state": "reachable"}

        # Windows format
        res = netinfo._parse_arp_line("  192.168.1.1          00-50-56-ab-cd-ef     dynamic")
        assert res == {"ip": "192.168.1.1", "mac": "00:50:56:AB:CD:EF", "state": "dynamic"}


class TestPingLatency:
    def test_parse_ping_latency(self):
        assert netinfo._parse_ping_latency("Average = 3ms") == 3.0
        assert netinfo._parse_ping_latency("Average = 3,2ms") == 3.2
        assert netinfo._parse_ping_latency("rtt min/avg/max/mdev = 0.312/1.500/2.688/0.000 ms") == 1.5
        assert netinfo._parse_ping_latency("round-trip min/avg/max/stddev = 0.312/2.400/3.688/0.152 ms") == 2.4
        assert netinfo._parse_ping_latency("Request timed out.") is None


class TestNetworkHealth:
    def test_health_rules(self, monkeypatch):
        # Mock _ping_one
        def mock_ping(ip):
            if ip == "192.168.1.1":
                return {"alive": True, "latency_ms": 1.2}
            elif ip == netinfo.HEALTH_INTERNET_TARGET:
                return {"alive": True, "latency_ms": 14.5}
            return {"alive": False, "latency_ms": None}

        monkeypatch.setattr(netinfo, "_ping_one", mock_ping)
        nh = netinfo.get_network_health("192.168.1.1")
        assert nh["status"] == "Healthy"
        assert nh["gateway_reachable"] is True
        assert nh["internet_reachable"] is True


class TestDNSInfo:
    def test_measure_dns_lookup(self):
        res = netinfo._measure_dns_lookup("google.com")
        assert "success" in res
        assert "lookup_ms" in res

    def test_dns_servers_parsing(self, monkeypatch, windows_ipconfig_output):
        monkeypatch.setattr(netinfo, "IS_WINDOWS", True)
        monkeypatch.setattr(netinfo, "_get_windows_ipconfig", lambda: windows_ipconfig_output)
        servers = netinfo._get_dns_servers()
        assert "192.168.1.1" in servers
        assert "8.8.8.8" in servers


class TestWiFiInformation:
    def test_wifi_windows(self, monkeypatch, windows_netsh_wlan_output):
        monkeypatch.setattr(netinfo, "IS_WINDOWS", True)
        monkeypatch.setattr(netinfo, "run_cmd", lambda cmd: windows_netsh_wlan_output)
        res = netinfo._get_wifi_windows()
        assert res["connected"] is True
        assert res["ssid"] == "HomeNet_5G"
        assert res["bssid"] == "00:50:56:AB:CD:EF"
        assert res["band"] == "5 GHz"
        assert res["channel"] == 36
        assert res["signal_percent"] == 92


class TestSnapshot:
    def test_save_load_compare(self, tmp_path):
        snap_file = tmp_path / "test_snapshot.json"
        report1 = {
            "public_ip": "1.1.1.1",
            "default_gateway": "192.168.1.1",
            "devices": [{"ip": "192.168.1.10", "mac": "00:11:22:33:44:55"}],
        }
        report2 = {
            "public_ip": "2.2.2.2",
            "default_gateway": "192.168.1.1",
            "devices": [
                {"ip": "192.168.1.10", "mac": "00:11:22:33:44:55"},
                {"ip": "192.168.1.20", "mac": "AA:BB:CC:DD:EE:FF"},
            ],
        }

        assert netinfo.save_snapshot(report1, str(snap_file)) is True
        loaded = netinfo.load_snapshot(str(snap_file))
        assert loaded["public_ip"] == "1.1.1.1"

        cmp_res = netinfo.compare_reports(loaded, report2)
        assert cmp_res["summary"]["total_changes"] == 2
        assert "public_ip" in cmp_res["changes"]
        assert len(cmp_res["changes"]["devices_added"]) == 1


class TestColors:
    def test_colors_disabled(self):
        c = netinfo.Colors(enabled=False)
        assert c.BOLD == ""
        assert c.GREEN == ""
        assert c.RESET == ""

    def test_colors_enabled(self):
        c = netinfo.Colors(enabled=True)
        assert c.BOLD == "\033[1m"
        assert c.GREEN == "\033[32m"
        assert c.RESET == "\033[0m"

    def test_init_colors_no_color_flag(self):
        class DummyArgs:
            no_color = True
        c = netinfo._init_colors(DummyArgs())
        assert c.enabled is False

