#!/data/data/com.termux/files/usr/bin/bash
# One-time Jarvis setup inside Termux on Android.
# Run from the project folder:  bash scripts/termux-install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo ">> Instaliram Termux pakete…"
pkg update -y
pkg install -y python termux-api curl git

echo ">> Instaliram Python pakete (bez kompajlera)…"
# NOTE: never run "pip install --upgrade pip" in Termux - it breaks Termux's Python.
export AIOHTTP_NO_EXTENSIONS=1 MULTIDICT_NO_EXTENSIONS=1 YARL_NO_EXTENSIONS=1 \
       FROZENLIST_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1
pip install -r requirements.txt

set_env() {  # set_env KEY VALUE  -> writes KEY=VALUE into .env
  local key="$1" value="$2"
  value="${value//|/\\|}"
  sed -i "s|^${key}=.*|${key}=${value}|" .env
}

if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo ">> Podešavanje ključeva (možeš kasnije da menjaš sa: nano .env)"
  read -r -p "   Kako da te zovem? [Dario]: " owner
  set_env OWNER_NAME "${owner:-Dario}"
  read -r -p "   Nalepi GEMINI ključ (aistudio.google.com/apikey): " gemini
  set_env GEMINI_API_KEY "$gemini"
  read -r -p "   Nalepi GROQ ključ (console.groq.com/keys) ili samo Enter za preskakanje: " groq
  set_env GROQ_API_KEY "$groq"
fi
mkdir -p data

echo ">> Automatsko pokretanje posle restarta telefona (treba aplikacija Termux:Boot)…"
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/jarvis.sh <<BOOT
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd "$(pwd)"
./scripts/start.sh >> data/jarvis.log 2>&1
BOOT
chmod +x ~/.termux/boot/jarvis.sh scripts/start.sh

if grep -q '^WHATSAPP_MODE=bridge' .env; then
  echo ">> Instaliram opcioni (RIZIČNI) WhatsApp most…"
  pkg install -y nodejs-lts
  (cd whatsapp-bridge && npm install --omit=dev)
fi

echo
echo ">> Gotovo. Sledeće:"
echo "   1) Proveri dozvole (Android će pitati - dozvoli sve):"
echo "        termux-sms-list -l 1; termux-call-log -l 1; termux-contact-list | head -5"
echo "   2) Pokreni Jarvisa:   ./scripts/start.sh --open"
