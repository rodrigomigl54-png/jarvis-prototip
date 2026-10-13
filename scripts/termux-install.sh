#!/data/data/com.termux/files/usr/bin/bash
# One-time Jarvis setup inside Termux on Android.
# Run from the project folder:  bash scripts/termux-install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo ">> Installing Termux packages…"
pkg update -y
pkg install -y python nodejs-lts termux-api curl git

echo ">> Installing Python packages (pure-Python builds, no compiler needed)…"
export AIOHTTP_NO_EXTENSIONS=1 MULTIDICT_NO_EXTENSIONS=1 YARL_NO_EXTENSIONS=1 \
       FROZENLIST_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo ">> Created .env - open it and fill in your keys:  nano .env"
fi
mkdir -p data

echo ">> Autostart on phone boot (needs the Termux:Boot app)…"
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/jarvis.sh <<BOOT
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd "$(pwd)"
./scripts/start.sh >> data/jarvis.log 2>&1
BOOT
chmod +x ~/.termux/boot/jarvis.sh scripts/start.sh

if grep -q '^WHATSAPP_MODE=bridge' .env; then
  echo ">> Installing the optional WhatsApp bridge…"
  (cd whatsapp-bridge && npm install --omit=dev)
fi

echo
echo ">> Done. Next:"
echo "   1) nano .env        (at least GEMINI_API_KEY; GROQ_API_KEY recommended)"
echo "   2) termux-sms-list -l 1 && termux-call-log -l 1 && termux-contact-list | head"
echo "      (Android will ask for permissions - allow all)"
echo "   3) ./scripts/start.sh --open"
