#!/data/data/com.termux/files/usr/bin/bash
# One command to install Jarvis in Termux:
#   curl -fsSL https://raw.githubusercontent.com/rodrigomigl54-png/jarvis-prototip/claude/sleepy-fermat-hj9eo6/scripts/bootstrap.sh -o j.sh && bash j.sh
set -euo pipefail
REPO=https://github.com/rodrigomigl54-png/jarvis-prototip.git
BRANCH=claude/sleepy-fermat-hj9eo6
DIR="$HOME/jarvis-prototip"

echo ">> Pripremam Termux (ako nešto pita, samo pritisni Enter)…"
pkg update -y
pkg install -y git

if [ -d "$DIR/.git" ]; then
  echo ">> Jarvis već postoji - preuzimam najnoviju verziju…"
  git -C "$DIR" pull --ff-only
else
  git clone -b "$BRANCH" "$REPO" "$DIR"
fi

cd "$DIR"
bash scripts/termux-install.sh
