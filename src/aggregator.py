#!/usr/bin/env python3
"""Clash Free Aggregator 2026 - OpenClash/Mihomo edition.

Purpose:
  - Fetch public Clash YAML or URI/Base64 subscriptions.
  - Normalize and deduplicate proxy nodes.
  - Keep a stable generated subscription URL for OpenClash.
  - Generate Mihomo/OpenClash-friendly proxy groups for YouTube/Google.
  - NEVER overwrite a known-good subscription with an empty result.

The GitHub Action is the aggregation/update side. OpenClash/Mihomo remains
responsible for live health checks and selecting the fastest working node.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "sources.yaml"
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)

HEADERS = {"User-Agent": "clash-free-aggregator-2026/OpenClash"}

REGIONS = [
    ("Hong Kong", r"(?i)(香港|港|hong[\s_-]*kong|\bhk\b|🇭🇰)"),
    ("Taiwan", r"(?i)(台湾|台灣|taiwan|\btw\b|🇹🇼)"),
    ("Japan", r"(?i)(日本|japan|\bjp\b|🇯🇵)"),
    ("Singapore", r"(?i)(新加坡|singapore|\bsg\b|🇸🇬)"),
    ("United States", r"(?i)(美国|美國|united[\s_-]*states|\busa?\b|\bus\b|🇺🇸)"),
    ("Netherlands", r"(?i)(荷兰|荷蘭|netherlands|\bnl\b|amsterdam|🇳🇱)"),
    ("France", r"(?i)(法国|法國|france|\bfr\b|paris|🇫🇷)"),
    ("Germany", r"(?i)(德国|德國|germany|\bde\b|frankfurt|🇩🇪)"),
    ("United Kingdom", r"(?i)(英国|英國|united[\s_-]*kingdom|\buk\b|london|🇬🇧)"),
    ("South Korea", r"(?i)(韩国|韓國|south[\s_-]*korea|\bkr\b|seoul|🇰🇷)"),
    ("Canada", r"(?i)(加拿大|canada|\bca\b|toronto|🇨🇦)"),
    ("Australia", r"(?i)(澳大利亚|澳洲|australia|\bau\b|sydney|🇦🇺)"),
    ("Russia", r"(?i)(俄罗斯|俄羅斯|russia|\bru\b|moscow|🇷🇺)"),
]

REGION_ALIASES = {
    "Hong Kong": "HK",
    "Taiwan": "TW",
    "Japan": "JP",
    "Singapore": "SG",
    "United States": "US",
    "Netherlands": "NL",
    "France": "FR",
    "Germany": "DE",
    "United Kingdom": "UK",
    "South Korea": "KR",
    "Canada": "CA",
    "Australia": "AU",
    "Russia": "RU",
}


def load_config():
    with open(CONFIG, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def http_get(url: str, timeout: int) -> str:
    r = requests.get(url, timeout=timeout, headers=HEADERS, allow_redirects=True)
    r.raise_for_status()
    return r.text


def b64decode_loose(text: str) -> str | None:
    raw = re.sub(r"\s+", "", text.strip())
    if not raw:
        return None
    try:
        pad = "=" * ((4 - len(raw) % 4) % 4)
        return base64.b64decode(raw + pad, validate=False).decode("utf-8", errors="ignore")
    except Exception:
        return None


def decode_subscription(text: str) -> str:
    """Return text as URI-list when possible; otherwise leave it untouched."""
    raw = text.strip()
    if re.search(r"(?m)^(vless|vmess|trojan|ss|hysteria2|hy2|tuic|http|socks5)://", raw, re.I):
        return raw
    decoded = b64decode_loose(raw)
    if decoded and re.search(r"(?m)^(vless|vmess|trojan|ss|hysteria2|hy2|tuic|http|socks5)://", decoded, re.I):
        return decoded
    return raw


def clean_name(name, fallback):
    name = str(name or fallback).strip()
    name = re.sub(r"[\r\n\t]+", " ", name)
    name = re.sub(r"\s{2,}", " ", name)
    return name[:120] or fallback


def region_of(name: str) -> str:
    for region, pattern in REGIONS:
        if re.search(pattern, name or ""):
            return region
    return "Other"


def parse_clash(text: str, source: str):
    doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        return []
    proxies = doc.get("proxies")
    if not isinstance(proxies, list):
        return []
    out = []
    for i, item in enumerate(proxies, 1):
        if not isinstance(item, dict):
            continue
        p = dict(item)
        p["_source"] = source
        p["_original_name"] = clean_name(p.get("name"), f"{source}-{i}")
        out.append(p)
    return out


def q_first(qs, key, default=None):
    values = qs.get(key)
    return values[0] if values else default


def parse_ss(uri: str, name: str):
    u = urlparse(uri)
    host, port, method, password = u.hostname, u.port, None, None
    if u.username:
        user = unquote(u.username)
        try:
            dec = base64.urlsafe_b64decode(user + "=" * ((4 - len(user) % 4) % 4)).decode()
            if ":" in dec:
                method, password = dec.split(":", 1)
        except Exception:
            pass
    elif u.netloc and "@" not in u.netloc:
        try:
            dec = base64.urlsafe_b64decode(u.netloc + "=" * ((4 - len(u.netloc) % 4) % 4)).decode()
            if "@" in dec:
                creds, hp = dec.rsplit("@", 1)
                method, password = creds.split(":", 1)
                host, port_s = hp.rsplit(":", 1)
                port = int(port_s)
        except Exception:
            return None
    if not (host and port and method and password):
        return None
    return {"name": name, "type": "ss", "server": host, "port": int(port),
            "cipher": method, "password": password, "udp": True}


def parse_uri(uri: str, source: str, idx: int):
    uri = uri.strip()
    if not re.match(r"^[a-zA-Z0-9+.-]+://", uri):
        return None
    u = urlparse(uri)
    scheme = u.scheme.lower()
    if scheme == "hy2":
        scheme = "hysteria2"
    fragment = unquote(u.fragment or "")
    name = clean_name(fragment, f"{source}-{idx}")

    if scheme == "ss":
        return parse_ss(uri, name)

    if scheme in ("vless", "trojan", "hysteria2", "tuic"):
        host, port = u.hostname, u.port
        if not host or not port:
            return None
        qs = parse_qs(u.query)
        p = {"name": name, "type": scheme, "server": host, "port": int(port), "udp": True}

        if scheme == "vless":
            p["uuid"] = unquote(u.username or "")
            if not p["uuid"]:
                return None
            network = q_first(qs, "type", "tcp")
            p["network"] = network
            security = q_first(qs, "security", "")
            if security in ("tls", "reality"):
                p["tls"] = True
            if security == "reality":
                ro = {}
                if q_first(qs, "pbk"):
                    ro["public-key"] = q_first(qs, "pbk")
                if q_first(qs, "sid"):
                    ro["short-id"] = q_first(qs, "sid")
                if ro:
                    p["reality-opts"] = ro
            if q_first(qs, "sni"):
                p["servername"] = q_first(qs, "sni")
            if q_first(qs, "fp"):
                p["client-fingerprint"] = q_first(qs, "fp")
            if q_first(qs, "flow"):
                p["flow"] = q_first(qs, "flow")
            if network == "ws":
                p["ws-opts"] = {"path": q_first(qs, "path", "/"), "headers": {}}
                if q_first(qs, "host"):
                    p["ws-opts"]["headers"]["Host"] = q_first(qs, "host")
            elif network == "grpc":
                p["grpc-opts"] = {"grpc-service-name": q_first(qs, "serviceName", "")}

        elif scheme == "trojan":
            p["password"] = unquote(u.username or "")
            if not p["password"]:
                return None
            p["tls"] = True
            if q_first(qs, "sni"):
                p["sni"] = q_first(qs, "sni")
            if q_first(qs, "allowInsecure") in ("1", "true"):
                p["skip-cert-verify"] = True
            network = q_first(qs, "type")
            if network == "ws":
                p["network"] = "ws"
                p["ws-opts"] = {"path": q_first(qs, "path", "/"), "headers": {}}
                if q_first(qs, "host"):
                    p["ws-opts"]["headers"]["Host"] = q_first(qs, "host")

        elif scheme == "hysteria2":
            p["password"] = unquote(u.username or "")
            if not p["password"]:
                return None
            p["tls"] = True
            if q_first(qs, "sni"):
                p["sni"] = q_first(qs, "sni")
            if q_first(qs, "insecure") in ("1", "true"):
                p["skip-cert-verify"] = True

        elif scheme == "tuic":
            password = unquote(u.password or "")
            p["uuid"] = unquote(u.username or "")
            p["password"] = password
            if not p["uuid"] or not password:
                return None
            if q_first(qs, "sni"):
                p["sni"] = q_first(qs, "sni")
            p["udp-relay-mode"] = q_first(qs, "udp_relay_mode", "native")
            p["congestion-controller"] = q_first(qs, "congestion_control", "bbr")
        return p

    if scheme == "vmess":
        try:
            payload = uri.split("://", 1)[1]
            dec = b64decode_loose(payload)
            if not dec:
                return None
            v = json.loads(dec)
            p = {
                "name": clean_name(fragment or v.get("ps"), f"{source}-{idx}"),
                "type": "vmess", "server": v["add"], "port": int(v["port"]),
                "uuid": v["id"], "alterId": int(v.get("aid", 0)),
                "cipher": v.get("scy", "auto"), "udp": True,
                "network": v.get("net", "tcp"),
            }
            if v.get("tls") == "tls":
                p["tls"] = True
                if v.get("sni"):
                    p["servername"] = v["sni"]
            if p["network"] == "ws":
                p["ws-opts"] = {"path": v.get("path", "/"), "headers": {}}
                if v.get("host"):
                    p["ws-opts"]["headers"]["Host"] = v["host"]
            return p
        except Exception:
            return None

    if scheme in ("http", "https", "socks5", "socks5h"):
        host, port = u.hostname, u.port
        if not host or not port:
            return None
        p = {"name": name, "type": "socks5" if scheme.startswith("socks") else "http",
             "server": host, "port": int(port)}
        if u.username:
            p["username"] = unquote(u.username)
        if u.password:
            p["password"] = unquote(u.password)
        return p
    return None


def parse_uri_list(text: str, source: str):
    decoded = decode_subscription(text)
    out = []
    for i, line in enumerate(decoded.splitlines(), 1):
        line = line.strip().strip("\ufeff")
        if not re.match(r"^(vless|vmess|trojan|ss|hysteria2|hy2|tuic|http|socks5)://", line, re.I):
            continue
        try:
            p = parse_uri(line, source, i)
            if p:
                p["_source"] = source
                p["_original_name"] = p["name"]
                out.append(p)
        except Exception:
            continue
    return out



def valid_hostname(value: str) -> bool:
    """Accept DNS names, IPv4 and IPv6 literals; reject URLs/garbled SNI."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value or len(value) > 253 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        return False
    if value.lower() in {"off", "false", "null", "none"}:
        return False
    if "/" in value or "%" in value or "://" in value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    labels = value.rstrip(".").split(".")
    if not labels or any(not x or len(x) > 63 for x in labels):
        return False
    return all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", x) for x in labels)


def normalize_proxy(p):
    """Normalize upstream proxy dictionaries to the fields expected by Mihomo."""
    p = dict(p)
    typ = str(p.get("type", "")).lower()
    p["type"] = typ

    # Source-specific / non-Mihomo fields that have appeared in public feeds.
    p.pop("_source", None)
    p.pop("_original_name", None)

    if typ == "hysteria2":
        # Hysteria2 is TLS by definition in current Mihomo; generic tls:true is
        # not part of the Hysteria2 proxy schema.
        p.pop("tls", None)
        if "sni" in p:
            sni = str(p.get("sni", "")).strip()
            if not sni:
                p.pop("sni", None)
            elif not valid_hostname(sni):
                return None

    if typ == "vless":
        flow = str(p.get("flow", ""))
        # Vision without Reality parameters is unsafe to publish as a normalized
        # Clash/Mihomo node because the public-key/short-id pair is missing.
        if flow == "xtls-rprx-vision" and not isinstance(p.get("reality-opts"), dict):
            return None
        sni = p.get("servername")
        if sni is not None and not valid_hostname(str(sni)):
            return None

    return p


def proxy_to_v2ray_uri(p):
    """Convert normalized proxy to a standard share URI for v2rayN."""
    typ = str(p.get("type", "")).lower()
    name = str(p.get("name", "Node"))
    fragment = quote(name, safe="")
    server = p.get("server")
    port = p.get("port")
    if not server or not port:
        return None

    if typ == "vless":
        uuid = p.get("uuid")
        if not uuid:
            return None
        q = {"encryption": "none"}
        if p.get("flow"):
            q["flow"] = p["flow"]
        if p.get("tls"):
            if isinstance(p.get("reality-opts"), dict):
                q["security"] = "reality"
                ro = p["reality-opts"]
                if ro.get("public-key"):
                    q["pbk"] = ro["public-key"]
                if ro.get("short-id"):
                    q["sid"] = ro["short-id"]
            else:
                q["security"] = "tls"
        if p.get("servername"):
            q["sni"] = p["servername"]
        if p.get("client-fingerprint"):
            q["fp"] = p["client-fingerprint"]
        network = p.get("network", "tcp")
        if network:
            q["type"] = network
        if network == "ws":
            wo = p.get("ws-opts") or {}
            if wo.get("path"):
                q["path"] = wo["path"]
            headers = wo.get("headers") or {}
            if headers.get("Host"):
                q["host"] = headers["Host"]
        elif network == "grpc":
            go = p.get("grpc-opts") or {}
            if go.get("grpc-service-name"):
                q["serviceName"] = go["grpc-service-name"]
        return f"vless://{quote(str(uuid), safe='')}@{server}:{port}?{urlencode(q)}#{fragment}"

    if typ == "trojan":
        password = p.get("password")
        if not password:
            return None
        q = {"security": "tls", "type": p.get("network", "tcp")}
        if p.get("sni"):
            q["sni"] = p["sni"]
        if p.get("skip-cert-verify"):
            q["allowInsecure"] = "1"
        if p.get("network") == "ws":
            wo = p.get("ws-opts") or {}
            q["path"] = wo.get("path", "/")
            headers = wo.get("headers") or {}
            if headers.get("Host"):
                q["host"] = headers["Host"]
        return f"trojan://{quote(str(password), safe='')}@{server}:{port}?{urlencode(q)}#{fragment}"

    if typ == "hysteria2":
        password = p.get("password")
        if not password:
            return None
        q = {}
        if p.get("sni"):
            q["sni"] = p["sni"]
        if p.get("skip-cert-verify"):
            q["insecure"] = "1"
        return f"hysteria2://{quote(str(password), safe='')}@{server}:{port}?{urlencode(q)}#{fragment}"

    if typ == "ss":
        method, password = p.get("cipher"), p.get("password")
        if not method or password is None:
            return None
        userinfo = f"{method}:{password}@{server}:{port}"
        token = base64.urlsafe_b64encode(userinfo.encode()).decode().rstrip("=")
        return f"ss://{token}#{fragment}"

    if typ == "vmess":
        payload = {
            "v": "2", "ps": name, "add": server, "port": str(port),
            "id": p.get("uuid", ""), "aid": str(p.get("alterId", 0)),
            "scy": p.get("cipher", "auto"), "net": p.get("network", "tcp"),
            "type": "none", "host": "", "path": "/", "tls": ""
        }
        if not payload["id"]:
            return None
        if p.get("tls"):
            payload["tls"] = "tls"
            payload["sni"] = p.get("servername", "")
        if p.get("network") == "ws":
            wo = p.get("ws-opts") or {}
            payload["path"] = wo.get("path", "/")
            payload["host"] = (wo.get("headers") or {}).get("Host", "")
        raw = base64.b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode()
        return f"vmess://{raw}"

    if typ == "socks5":
        user = p.get("username")
        password = p.get("password")
        auth = ""
        if user is not None:
            auth = quote(str(user), safe="")
            if password is not None:
                auth += ":" + quote(str(password), safe="")
            auth += "@"
        return f"socks://{auth}{server}:{port}#{fragment}"

    return None


def write_v2rayn_subscription(path: Path, proxies):
    uris = []
    for p in proxies:
        uri = proxy_to_v2ray_uri(p)
        if uri:
            uris.append(uri)
    body = "\n".join(uris) + ("\n" if uris else "")
    encoded = base64.b64encode(body.encode("utf-8")).decode("ascii")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(encoded + "\n", encoding="ascii")
    tmp.replace(path)
    return len(uris)

def valid_proxy(p, keep):
    p2 = normalize_proxy(p)
    if p2 is None:
        return False
    typ = str(p2.get("type", "")).lower()
    if typ not in keep:
        return False
    host, port = p2.get("server"), p2.get("port")
    if not host or not isinstance(port, int) or not 1 <= port <= 65535:
        return False
    if typ == "vless" and not p2.get("uuid"):
        return False
    if typ in ("trojan", "hysteria2") and not p2.get("password"):
        return False
    p.clear()
    p.update(p2)
    return True


def fingerprint(p):
    q = {k: v for k, v in p.items() if k not in ("name", "_source", "_original_name")}
    return hashlib.sha256(json.dumps(q, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def unique_name(base, used):
    base = clean_name(base, "Node")
    if base not in used:
        used.add(base)
        return base
    i = 2
    while f"{base} #{i}" in used:
        i += 1
    n = f"{base} #{i}"
    used.add(n)
    return n


def group_url(group_name: str):
    # Google generate_204 is generally lightweight and suitable for latency testing.
    if group_name == "YouTube Auto":
        return "https://www.gstatic.com/generate_204"
    if group_name == "Google Auto":
        return "https://www.google.com/generate_204"
    return "https://www.gstatic.com/generate_204"


def build_config(nodes, settings):
    proxies = []
    used = set()
    for idx, raw in enumerate(nodes, 1):
        p = dict(raw)
        source = p.pop("_source", "unknown")
        original = p.pop("_original_name", p.get("name", f"node-{idx}"))
        region = region_of(original)
        alias = REGION_ALIASES.get(region, "OT")
        name = unique_name(f"{alias} | {source} | {original}", used)
        p["name"] = name
        proxies.append(p)

    groups = []

    def add_url_test(name, pattern=None, tolerance=80):
        g = {
            "name": name,
            "type": "url-test",
            "include-all": True,
            "url": group_url(name),
            "interval": int(settings.get("health_check_interval", 300)),
            "tolerance": tolerance,
            "timeout": int(settings.get("health_check_timeout", 5000)),
        }
        if pattern:
            g["filter"] = pattern
        groups.append(g)

    # All-nodes group plus explicit region groups. include-all keeps the file small
    # while letting Mihomo discover proxies from the top-level proxies list.
    add_url_test("Auto")
    for region, pattern in REGIONS:
        add_url_test(f"{region} Auto", pattern)

    preferred = [
        "Auto", "Japan Auto", "Singapore Auto", "Hong Kong Auto", "Taiwan Auto",
        "United States Auto", "Netherlands Auto", "France Auto", "Germany Auto",
        "United Kingdom Auto", "South Korea Auto", "Canada Auto", "Australia Auto",
    ]
    groups += [
        {"name": "YouTube", "type": "select", "proxies": ["YouTube Auto", *preferred, "DIRECT"]},
        {"name": "Google", "type": "select", "proxies": ["Google Auto", *preferred, "DIRECT"]},
        {"name": "Proxy", "type": "select", "proxies": ["Auto", "YouTube", "Google", *preferred, "DIRECT"]},
        {"name": "Final", "type": "select", "proxies": ["Proxy", "Auto", "DIRECT"]},
    ]
    # Dedicated URL-test groups for the two main use cases.
    add_url_test("YouTube Auto", r"(?i).*")
    add_url_test("Google Auto", r"(?i).*")

    rules = [
        "DOMAIN-SUFFIX,youtube.com,YouTube",
        "DOMAIN-SUFFIX,youtu.be,YouTube",
        "DOMAIN-SUFFIX,youtube-nocookie.com,YouTube",
        "DOMAIN-SUFFIX,googlevideo.com,YouTube",
        "DOMAIN-SUFFIX,ytimg.com,YouTube",
        "DOMAIN-SUFFIX,ggpht.com,YouTube",
        "DOMAIN-SUFFIX,google.com,Google",
        "DOMAIN-SUFFIX,googleapis.com,Google",
        "DOMAIN-SUFFIX,gstatic.com,Google",
        "DOMAIN-SUFFIX,googleusercontent.com,Google",
        "DOMAIN-SUFFIX,github.com,Proxy",
        "DOMAIN-SUFFIX,githubusercontent.com,Proxy",
        "GEOIP,LAN,DIRECT,no-resolve",
        "GEOIP,CN,DIRECT",
        "MATCH,Final",
    ]

    return {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "proxies": proxies,
        "proxy-groups": groups,
        "rules": rules,
    }


def atomic_write_yaml(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=180)
    tmp.replace(path)


def main():
    cfg = load_config()
    settings = cfg.get("settings", {})
    timeout = int(settings.get("request_timeout", 30))
    max_nodes = int(settings.get("max_nodes", 300))
    min_publish_nodes = int(settings.get("min_publish_nodes", 1))
    keep = {str(x).lower() for x in settings.get("keep_protocols", [])}

    all_nodes, stats = [], []
    enabled_count = 0
    successful_sources = 0

    for source in cfg.get("sources", []):
        if not source.get("enabled", True):
            continue
        enabled_count += 1
        name = str(source["name"])
        try:
            text = http_get(source["url"], timeout)
            source_type = source.get("type", "auto")
            if source_type == "clash_yaml":
                nodes = parse_clash(text, name)
            elif source_type in ("base64", "uri_list", "auto"):
                try:
                    nodes = parse_clash(text, name) if source_type == "auto" and isinstance(yaml.safe_load(text), dict) and isinstance(yaml.safe_load(text).get("proxies"), list) else parse_uri_list(text, name)
                except Exception:
                    nodes = parse_uri_list(text, name)
            else:
                raise ValueError(f"unsupported source type: {source_type}")
            before = len(nodes)
            nodes = [p for p in nodes if valid_proxy(p, keep)]
            all_nodes.extend(nodes)
            successful_sources += 1
            stats.append({"source": name, "fetched": before, "valid": len(nodes), "error": None})
            print(f"[OK] {name}: fetched={before}, valid={len(nodes)}")
        except Exception as exc:
            stats.append({"source": name, "fetched": 0, "valid": 0, "error": str(exc)})
            print(f"[WARN] {name}: {exc}", file=sys.stderr)

    dedup = {}
    for p in all_nodes:
        dedup.setdefault(fingerprint(p), p)
    nodes = list(dedup.values())
    nodes.sort(key=lambda p: (region_of(p.get("_original_name", "")), p.get("_source", ""), p.get("_original_name", "")))
    nodes = nodes[:max_nodes]

    status = {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "openclash-mihomo",
        "successful_sources": successful_sources,
        "enabled_sources": enabled_count,
        "raw_nodes": len(all_nodes),
        "unique_nodes": len(dedup),
        "published_nodes": len(nodes),
        "publication": "updated" if len(nodes) >= min_publish_nodes else "kept_previous",
        "sources": stats,
        "protocols": {},
        "regions": {},
    }
    for p in nodes:
        typ = str(p["type"])
        status["protocols"][typ] = status["protocols"].get(typ, 0) + 1
        r = region_of(p.get("_original_name", ""))
        status["regions"][r] = status["regions"].get(r, 0) + 1

    # Critical safety behavior: never replace a working subscription with an empty file.
    if len(nodes) < min_publish_nodes:
        status["warning"] = "No publishable nodes. Existing dist/clash.yaml was preserved."
        with open(DIST / "status.json", "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0

    output_cfg = build_config(nodes, settings)
    atomic_write_yaml(DIST / "clash.yaml", output_cfg)
    # Explicit alias for OpenClash users. Both files contain the same config.
    atomic_write_yaml(DIST / "openclash.yaml", output_cfg)

    v2_count = write_v2rayn_subscription(DIST / "v2rayn.txt", output_cfg["proxies"])
    status["v2rayn_uris"] = v2_count

    with open(DIST / "nodes.txt", "w", encoding="utf-8") as f:
        for p in output_cfg["proxies"]:
            f.write(p["name"] + "\n")

    with open(DIST / "status.json", "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
