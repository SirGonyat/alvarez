#!/usr/bin/env bash
# Universal Quick Installer for Alvarez
set -e

echo "✦ Installing Alvarez Universal Assistant..."

INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

pip install --no-build-isolation -e .

echo ""
echo "✔ Installation complete!"
echo "Run 'alvarez' to launch the live HUD and assistant."
echo "Run 'alvarez-stream <preset>' to control streams."
