class CursorTelemetryBlocker < Formula
  desc "Block Cursor IDE telemetry while preserving AI functionality"
  homepage "https://github.com/taberoajorge/cursor-telemetry-blocker"
  url "https://github.com/taberoajorge/cursor-telemetry-blocker/archive/refs/heads/main.tar.gz"
  version "0.2.0"
  license "MIT"

  depends_on "uv"

  def install
    prefix.install Dir["*"]

    bin.install_symlink prefix/"scripts/cursor-private.sh" => "cursor-private"
    bin.install_symlink prefix/"scripts/setup-ca-cert.sh" => "cursor-setup-cert"
    bin.install_symlink prefix/"scripts/setup-hosts.sh" => "cursor-setup-hosts"
  end

  def post_install
    system "uv", "sync", "--quiet", "--project", prefix.to_s
  end

  def caveats
    <<~EOS
      To start blocking telemetry:
        cursor-private          # block mode (default)
        cursor-private deep     # deep mode (strip repo info)

      First-time setup:
        cursor-setup-cert       # install CA certificate
        cursor-setup-hosts      # block domains via /etc/hosts
    EOS
  end

  test do
    assert_match "cursor-telemetry-blocker", (prefix/"pyproject.toml").read
  end
end
