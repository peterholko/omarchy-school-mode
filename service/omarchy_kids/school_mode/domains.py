"""A deliberately small domain-list format, shared by config and enforcement."""
import ipaddress
import re

MAX_DOMAINS = 100
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z", re.ASCII)


def normalize_domains(value):
    if not isinstance(value, list) or len(value) > MAX_DOMAINS:
        raise ValueError("Enter up to 100 domains, one per line.")
    result = set()
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError("Enter domain names, one per line.")
        domain = entry.strip().lower().removeprefix("*.").rstrip(".")
        if not domain:
            continue
        labels = domain.split(".")
        if (len(domain) > 253 or len(labels) < 2 or
                any(not LABEL.fullmatch(label) for label in labels) or labels[-1].isdigit()):
            raise ValueError("Use domains such as youtube.com, without https://, paths or ports. Use punycode for international names.")
        try:
            ipaddress.ip_address(domain)
        except ValueError:
            result.add(domain)
        else:
            raise ValueError("Use a domain name rather than an IP address.")
    return sorted(result)
