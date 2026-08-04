class Netinfo < Formula
  desc "Zero-dependency, fast, cross-platform network diagnostic CLI & JSON tool"
  homepage "https://github.com/your-username/netinfo"
  url "https://github.com/your-username/netinfo/archive/refs/tags/v2.0.0.tar.gz"
  sha256 "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  license "MIT"

  depends_on "python@3.11"

  def install
    bin.install "netinfo.py" => "netinfo"
  end

  test do
    assert_match "netinfo", shell_output("#{bin}/netinfo --version")
  end
end
