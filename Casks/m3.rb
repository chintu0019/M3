# Homebrew Cask for M3 — auto-updated by .github/workflows/release.yml
# after each tagged release. The version + sha256 lines below are rewritten
# by the workflow; the rest of the file is hand-maintained.
#
# Install:
#   brew tap chintu0019/m3 https://github.com/chintu0019/M3.git
#   brew install --cask m3

cask "m3" do
  version "0.1.2"
  sha256 "37da4cf38954239cfc7f921c8b8503965349de3f6b002accbc2b44377e3aa94f"

  url "https://github.com/chintu0019/M3/releases/download/v#{version}/M3_#{version}_aarch64.dmg"
  name "M3"
  desc "Self-hosted personal knowledge OS — chat with your own notes"
  homepage "https://github.com/chintu0019/M3"

  livecheck do
    url :url
    strategy :github_latest
  end

  auto_updates true
  depends_on macos: ">= :monterey"

  app "M3.app"

  # Removed when the user runs `brew uninstall --zap`. Leaves ~/brain/ alone
  # — that's the user's data and survives uninstalls.
  zap trash: [
    "~/Library/Application Support/local.m3.app",
    "~/Library/Caches/local.m3.app",
    "~/Library/Logs/local.m3.app",
    "~/Library/Preferences/local.m3.app.plist",
    "~/Library/Saved Application State/local.m3.app.savedState",
    "~/Library/WebKit/local.m3.app",
  ]
end
