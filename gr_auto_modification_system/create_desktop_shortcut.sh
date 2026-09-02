#!/bin/bash
# Run this ONCE to create a double-clickable Desktop icon for the app.
# After this, you will never need to open a terminal again - just
# double-click "GR Auto Modification System" on your Desktop (or find it
# in your Applications menu).

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$DIR/start_app.sh"

APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
DESKTOP_FILE="$APPS_DIR/gr-auto-modification-system.desktop"

ICON="utilities-terminal"
if [ -f "$DIR/static/img/icon.png" ]; then
  ICON="$DIR/static/img/icon.png"
fi

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=GR Auto Modification System
Comment=Start the CN / Docket Modification tool
Exec=bash -c "cd '$DIR' && ./start_app.sh; exec bash"
Icon=$ICON
Terminal=true
Categories=Office;
EOF
chmod +x "$DESKTOP_FILE"

# Also copy to the Desktop folder if one exists, so it shows up as an icon
# you can see immediately (some desktops need you to right-click ->
# "Allow Launching" / "Trust" the very first time - this is normal).
if [ -d "$HOME/Desktop" ]; then
  cp "$DESKTOP_FILE" "$HOME/Desktop/gr-auto-modification-system.desktop"
  chmod +x "$HOME/Desktop/gr-auto-modification-system.desktop"
  gio set "$HOME/Desktop/gr-auto-modification-system.desktop" "metadata::trusted" true 2>/dev/null || true
fi

echo "Shortcut ban gaya!"
echo
echo "Ab aapko 'GR Auto Modification System' naam ka icon milega:"
echo "  - Desktop par, aur"
echo "  - Applications menu me (search karke bhi mil jaayega)"
echo
echo "Bas usi par double-click karo - app start hogi aur Chrome khud khul jaayega."
echo "(Pehli baar double-click karne par 'Trust and Launch' / 'Allow Launching'"
echo " ka option aa sakta hai - ek baar allow kar dena, uske baad seedha chalega.)"
