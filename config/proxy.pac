function FindProxyForURL(url, host) {
  if (
    dnsDomainIs(host, ".cursor.sh") ||
    dnsDomainIs(host, "cursor.sh")
  ) {
    return "PROXY 127.0.0.1:18080; DIRECT";
  }
  return "DIRECT";
}
