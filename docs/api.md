# API Reference

`netinfo` can be imported programmatically into Python applications:

```python
import argparse
import netinfo

# Collect network report dictionary
report = netinfo.collect_report(argparse.Namespace(
    sweep=False,
    vendors=False,
    no_dns=False,
    compare=None
))

print("Public IP:", report["public_ip"])
print("Default Gateway:", report["default_gateway"])
print("Wi-Fi SSID:", report["wifi_information"].get("ssid"))
```

::: netinfo.collect_report
::: netinfo.get_network_health
::: netinfo.get_dns_info
::: netinfo.get_wifi_information
::: netinfo.compare_reports
