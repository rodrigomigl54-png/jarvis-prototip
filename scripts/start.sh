#!/usr/bin/env bash
# Start Jarvis (and the optional WhatsApp bridge); restart automatically if it crashes.
#   ./scripts/start.sh          run in the foreground
#   ./scripts/start.sh --open   also open the HUD in the phone's browser
cd "$(dirname "$0")/.."
command -v termux-wake-lock >/dev/null && termux-wake-lock

if grep -q '^WHATSAPP_MODE=bridge' .env 2>/dev/null; then
  (cd whatsapp-bridge && while true; do node index.mjs; echo "bridge exited, restarting in 10s"; sleep 10; done) \
    >> data/whatsapp-bridge.log 2>&1 &
fi

if [ "${1:-}" = "--open" ]; then
  (for _ in $(seq 1 30); do
     if [ -f data/hud_url.txt ] && curl -s -o /dev/null "http://127.0.0.1:${HUD_PORT:-8765}/"; then
       termux-open-url "$(cat data/hud_url.txt)"; break
     fi
     sleep 1
   done) &
fi

while true; do
  python -m jarvis
  code=$?
  [ "$code" -eq 0 ] && break
  echo "Jarvis exited with $code, restarting in 5s…"
  sleep 5
done
