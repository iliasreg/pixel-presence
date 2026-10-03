#!/bin/sh
# PixelPresence installer.
#
# Run it from the checkout:
#
#     ./install.sh
#
# It optionally connects Hermes state updates. The companion starts manually.
# There is nothing to build or install into the system.
#
# Set PIXELPRESENCE_ART to use your own sprite sheet; see the README.

set -eu

REPO_DIR=$(cd "$(dirname "$0")" && pwd)
COMPANION="$REPO_DIR/companion/pixel_presence.py"
HOOK="$REPO_DIR/adapters/hermes/pixelpresence_state.py"
EVENTS="on_session_start pre_llm_call post_llm_call pre_tool_call post_tool_call pre_approval_request post_approval_response subagent_start subagent_stop on_session_end"

say() { printf '%s\n' "$*"; }

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

if ! command -v python3 >/dev/null 2>&1; then
    say "python3 is required but was not found on PATH."
    exit 1
fi

if ! python3 -c 'import tkinter' >/dev/null 2>&1; then
    say "python3 is here, but it was built without tkinter, so the companion"
    say "window cannot be drawn. Install it with your package manager:"
    say ""
    say "  Debian/Ubuntu   sudo apt install python3-tk"
    say "  Fedora          sudo dnf install python3-tkinter"
    say "  Arch            sudo pacman -S tk"
    say ""
    say "On Windows the official python.org installer already includes it."
    exit 1
fi

say "PixelPresence"
say "  checkout : $REPO_DIR"
say "  python   : $(python3 --version 2>&1)"
say ""

# ---------------------------------------------------------------------------
# The one question
# ---------------------------------------------------------------------------

say "Connect Hermes state updates?"
say ""
say "  yes           Hermes updates the state of a manually started companion"
say "  no (default)  leave the Hermes configuration unchanged"
say ""
printf 'Connect Hermes? [y/N] '
answer=""
read -r answer || answer=""

case "$answer" in
[yY]*) WITH_AGENT=yes ;;
*)     WITH_AGENT=no ;;
esac

if [ "$WITH_AGENT" = "yes" ]; then
    if ! command -v hermes >/dev/null 2>&1; then
        say ""
        say "The 'hermes' command was not found, so the hooks could not be wired."
        say "Add these to ~/.hermes/config.yaml by hand:"
        say ""
        say "  hooks:"
        for event in $EVENTS; do
            say "    $event:"
            say "      - command: $HOOK"
            say "        timeout: 5"
        done
        exit 0
    fi

    say ""
    say "Wiring the Hermes hooks..."
    for event in $EVENTS; do
        hermes config set "hooks.$event" "[{\"command\":\"$HOOK\",\"timeout\":5}]" --force >/dev/null
    done
    say "Done. One more step: shell hooks need first-use consent, granted once with"
    say ""
    say "    HERMES_ACCEPT_HOOKS=1 hermes chat -q hi"
    say "    hermes hooks doctor"
    say ""
    say "A new agent session is needed for the state hooks to take effect."
    say "This integration does not start the companion. Launch it yourself."
    say ""
    say "To start it by hand:  python3 $COMPANION"
else
    say ""
    say "Nothing else to do. Start the companion whenever you want it:"
    say ""
    say "    python3 $COMPANION"
    say ""
    say "Any other agent can drive it too, without knowing about Hermes:"
    say "    python3 $REPO_DIR/cli/pixel-presence.py state working --label build"
fi
