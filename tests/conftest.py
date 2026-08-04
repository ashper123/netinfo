import pytest

@pytest.fixture
def windows_ipconfig_output():
    return """
Windows IP Configuration

   Host Name . . . . . . . . . . . . : DESKTOP-NETINFO
   Primary Dns Suffix  . . . . . . . : 
   Node Type . . . . . . . . . . . . : Hybrid
   IP Routing Enabled. . . . . . . . : No

Wireless LAN adapter Wi-Fi:

   Connection-specific DNS Suffix  . : localdomain
   Description . . . . . . . . . . . : Intel(R) Wi-Fi 6 AX200 160MHz
   Physical Address. . . . . . . . . : 80-B5-05-AB-CD-EF
   DHCP Enabled. . . . . . . . . . . : Yes
   IPv6 Address. . . . . . . . . . . : 2001:db8::1234(Preferred)
   Link-local IPv6 Address . . . . . : fe80::80b5:5ff:feab:cdef%12(Preferred) 
   IPv4 Address. . . . . . . . . . . : 192.168.1.50(Preferred) 
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : fe80::1%12
                                       192.168.1.1
   DNS Servers . . . . . . . . . . . : 192.168.1.1
                                       8.8.8.8
"""

@pytest.fixture
def macos_ifconfig_output():
    return """
lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
	options=1203<RXCSUM,TXCSUM,SHA1,SHA256>
	inet 127.0.0.1 netmask 0xff000000 
	inet6 ::1 prefixlen 128 
	inet6 fe80::1%lo0 prefixlen 64 scopeid 0x1 
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
	options=400<CHANNEL_IO>
	ether 80:b5:05:ab:cd:ef 
	inet6 fe80::1234:5678:9abc:def0%en0 prefixlen 64 scopeid 0x6 
	inet6 2001:db8::5678 prefixlen 64 
	inet 192.168.1.50 netmask 0xffffff00 broadcast 192.168.1.255
"""

@pytest.fixture
def linux_ip_addr_output():
    return """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP
    link/ether 80:b5:05:ab:cd:ef brd ff:ff:ff:ff:ff:ff
    inet 192.168.1.50/24 brd 192.168.1.255 scope global eth0
"""

@pytest.fixture
def linux_ip6_addr_output():
    return """
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536
    inet6 ::1/128 scope host
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500
    inet6 2001:db8::100/64 scope global
    inet6 fe80::80b5:5ff:feab:cdef/64 scope link
"""

@pytest.fixture
def windows_netsh_wlan_output():
    return """
    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX200 160MHz
    State                  : connected
    SSID                   : HomeNet_5G
    BSSID                  : 00:50:56:ab:cd:ef
    Network type           : Infrastructure
    Radio type             : 802.11ac
    Authentication         : WPA2-Personal
    Cipher                 : CCMP
    Channel                : 36
    Receive rate (Mbps)    : 866
    Transmit rate (Mbps)   : 866
    Signal                 : 92%
"""

@pytest.fixture
def macos_airport_output():
    return """
     agrCtlRSSI: -54
     agrCtlNoise: -92
           state: running
         lastTxRate: 866
          BSSID: 00:50:56:ab:cd:ef
           SSID: HomeNet_5G
        channel: 36,1
      link auth: wpa2-psk
"""
