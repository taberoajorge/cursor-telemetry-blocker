#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CERT_PATH="$PROJECT_DIR/.mitmproxy/mitmproxy-ca-cert.pem"

if [ ! -f "$CERT_PATH" ]; then
    echo "Error: CA cert not found at $CERT_PATH"
    echo "Run the proxy once first to generate it."
    exit 1
fi

echo "Installing mitmproxy CA cert into macOS System Keychain..."
echo "(requires sudo)"

sudo security add-trusted-cert \
    -d \
    -r trustRoot \
    -k /Library/Keychains/System.keychain \
    "$CERT_PATH"

echo "CA cert installed and trusted."
echo "You can verify in Keychain Access > System > Certificates > mitmproxy"
