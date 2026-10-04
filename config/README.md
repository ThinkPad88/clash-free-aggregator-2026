# Source configuration

Edit `sources.yaml` to add/remove upstream feeds.

Supported formats:

- `clash_yaml`: a Clash/Mihomo YAML document containing `proxies:`
- `base64`: Base64 encoded URI list, or plain URI-per-line text

Keep source URLs public and stable. If an upstream project changes its path,
update this file; the final output URL does not change.
