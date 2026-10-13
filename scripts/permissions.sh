#!/data/data/com.termux/files/usr/bin/bash
# Walks through every Android permission Jarvis needs, opening the right
# settings screen each time. Safe to run again:  bash scripts/permissions.sh
cd "$(dirname "$0")/.."

wait_enter() { read -r -p "   …kad završiš, pritisni Enter ovde u Termux-u. " _ < /dev/tty || true; }
ok() { echo "   ✅ $1"; }
bad() { echo "   ❌ $1"; }

echo
echo "=== Dozvole za Jarvisa ==="
echo "Android će sada pitati za dozvole. Na svako pitanje pritisni DOZVOLI."
echo

echo "1/5 SMS poruke"
if termux-sms-list -l 1 >/dev/null 2>&1; then ok "SMS"; else bad "SMS - dozvoli SMS za Termux:API"; fi

echo "2/5 Lista poziva i telefon"
if termux-call-log -l 1 >/dev/null 2>&1; then ok "Pozivi"; else bad "Pozivi - dozvoli Evidenciju poziva i Telefon"; fi

echo "3/5 Kontakti"
if termux-contact-list >/dev/null 2>&1; then ok "Kontakti"; else bad "Kontakti - dozvoli Kontakte"; fi

echo
echo "   Otvaram dozvole aplikacije Termux:API - proveri da su uključeni:"
echo "   SMS, Telefon, Evidencija poziva, Kontakti."
am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d package:com.termux.api >/dev/null 2>&1 || true
wait_enter

echo "4/5 Pristup obaveštenjima (da Jarvis vidi WhatsApp poruke)"
if termux-notification-list 2>/dev/null | grep -q '"packageName"'; then
  ok "Pristup obaveštenjima"
else
  echo "   Otvaram ekran 'Pristup obaveštenjima' - uključi Termux:API."
  echo "   Ako je siv ('ograničeno podešavanje'): Podešavanja > Aplikacije > Termux:API >"
  echo "   ⋮ (gore desno) > 'Dozvoli ograničena podešavanja', pa probaj ponovo."
  am start -a android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS >/dev/null 2>&1 || true
  wait_enter
  if termux-notification-list 2>/dev/null | grep -q '"packageName"'; then ok "Pristup obaveštenjima"; else
    bad "Još ne vidim obaveštenja (proveri kasnije: bash scripts/permissions.sh)"; fi
fi

echo "5/5 Baterija (da Android ne gasi Jarvisa)"
echo "   Otvaram podešavanja baterije: za Termux i Termux:API izaberi 'Bez ograničenja'."
am start -a android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS >/dev/null 2>&1 || true
wait_enter

echo
echo "Još samo jednom otvori aplikaciju Termux:Boot (otvori i zatvori) - da se Jarvis pali sam."
echo "Dozvole: gotovo."
