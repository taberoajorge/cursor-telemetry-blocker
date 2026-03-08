#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CERT_PATH="$PROJECT_DIR/.mitmproxy/mitmproxy-ca-cert.pem"
OS_TYPE="$(uname -s)"

if [ ! -f "$CERT_PATH" ]; then
    echo "Error: CA cert not found at $CERT_PATH"
    echo "Run the proxy once first to generate it."
    exit 1
fi

case "$OS_TYPE" in
    Darwin)
        echo "Installing mitmproxy CA cert into macOS System Keychain..."
        echo "(requires sudo)"
        sudo security add-trusted-cert \
            -d \
            -r trustRoot \
            -k /Library/Keychains/System.keychain \
            "$CERT_PATH"
        echo "CA cert installed and trusted."
        echo "Verify in Keychain Access > System > Certificates > mitmproxy"
        ;;
    Linux)
        echo "Installing mitmproxy CA cert into system trust store..."
        echo "(requires sudo)"
        if [ -d "/usr/local/share/ca-certificates" ]; then
            sudo cp "$CERT_PATH" /usr/local/share/ca-certificates/mitmproxy-ca-cert.crt
            sudo update-ca-certificates
        elif [ -d "/etc/pki/ca-trust/source/anchors" ]; then
            sudo cp "$CERT_PATH" /etc/pki/ca-trust/source/anchors/mitmproxy-ca-cert.pem
            sudo update-ca-trust
        else
            echo "Error: Could not find system CA certificate directory."
            echo "Manually copy $CERT_PATH to your system trust store."
            exit 1
        fi
        echo "CA cert installed and trusted."
        ;;
    *)
        echo "Unsupported OS: $OS_TYPE"
        exit 1
        ;;
esac
