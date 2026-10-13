# Jarvis — lični AI asistent na tvom telefonu

Jarvis živi na tvom **Android telefonu** i radi 24/7. Prati **pozive, SMS, WhatsApp i Gmail**,
sastavlja odgovore tvojim stilom, vodi **zadatke, podsetnike i kalendar**, svako jutro ti da
**brifing** i priča sa tobom **glasom** preko HUD ekrana u stilu Iron Man-a.

**Glavno pravilo (ugrađeno u kod, ne samo u prompt):** Jarvis **nikad ništa ne šalje i nikog ne
zove bez tvog ✅**. Svaki odgovor, SMS, mejl i poziv prvo dobiješ kao nacrt sa dugmićima
**Pošalji / Izmeni / Odbij** — u HUD-u, u Android notifikaciji i (opciono) na Telegramu.

---

## Šta radi besplatno, a šta ne (iskreno)

| Funkcija | Besplatno? | Kako |
|---|---|---|
| Razgovor sa Jarvisom (tekst + glas) | ✅ | HUD u pregledaču telefona; Gemini/Groq free tier; srpski glas (edge-tts) |
| Automatsko prebacivanje LLM-a | ✅ | Gemini → Groq kad se potroši limit ili pukne |
| Propušten poziv → ko je zvao + kontekst + predlog poruke | ✅ | običan poziv → SMS, WhatsApp poziv → WhatsApp poruka |
| Jarvis **pozove** nekoga (posle tvog ✅) | ✅ | telefon okrene broj, **ti pričaš** |
| Jarvis **priča u pozivu** umesto tebe | ❌ | Android ne dozvoljava aplikacijama da govore u običnom pozivu. Moguće samo uz plaćeni Twilio (vidi dole) |
| SMS: čitanje + nacrt odgovora + slanje posle ✅ | ✅ | Termux:API |
| WhatsApp: čitanje + nacrt odgovora | ✅ | iz Android notifikacija (bez rizika) |
| WhatsApp: slanje | ✅ uz 1 dodir | posle ✅ otvori se WhatsApp sa upisanim tekstom, ti pritisneš Pošalji |
| WhatsApp: potpuno automatsko slanje | ⚠️ besplatno ali **rizično** | neoficijelni „most” (Baileys) — **WhatsApp može da ti blokira broj** |
| Gmail: sažetak + nacrt odgovora + slanje posle ✅ | ✅ | Gmail API |
| Google kalendar: čitanje + dodavanje | ✅ | Calendar API |
| Zadaci, podsetnici, beleške, brifing, večernji rezime | ✅ | lokalna SQLite baza |
| Pretraga interneta + prognoza (Novi Sad) | ✅ | DuckDuckGo + Open-Meteo, bez ključa |
| Telegram | ✅ opciono | sporedni kanal, isključen dok ne upišeš token |

---

## HUD — Jarvisov ekran

Otvara se u Chrome-u na telefonu (`http://127.0.0.1:8765`), izgleda kao Stark HUD:
reaktor u sredini (**dodirni i pričaj**), sat i datum u prstenovima, energija baterije, nacrti
koji čekaju odobrenje, razgovor, prognoza za Novi Sad, današnji kalendar, zadaci i „Novosti”.

U Chrome-u: meni ⋮ → **Dodaj na početni ekran**, pa se otvara kao aplikacija.

Dugmići gore: **STOP** (odmah zaustavlja sve odlazne akcije), **DND** (ne uznemiravaj — sve se čuva i
stiže kao jedan rezime), **Tekst/Glas/Oba** (kako ti odgovara), **Brifing**.

---

## Instalacija na telefon (Android)

### 1. Instaliraj aplikacije sa **F-Droid**-a (ne sa Google Play-a!)
Google Play verzija Termux:API nema dozvolu za SMS i listu poziva.

1. Instaliraj **F-Droid**: <https://f-droid.org>
2. U F-Droid-u instaliraj: **Termux**, **Termux:API**, **Termux:Boot**

### 2. Dozvole na telefonu
Podešavanja → Aplikacije → **Termux:API** → Dozvole → dozvoli **SMS, Telefon, Evidencija poziva,
Kontakti**. Zatim Podešavanja → Obaveštenja → **Pristup obaveštenjima** → uključi **Termux:API**
(da bi Jarvis video WhatsApp poruke).

Podešavanja → Baterija → **Termux** i **Termux:API** → **Bez ograničenja** (da ih Android ne gasi).
Jednom otvori **Termux:Boot** da bi se Jarvis sam palio posle restarta telefona.

### 3. Preuzmi Jarvisa i instaliraj
U Termux-u:
```bash
pkg update -y && pkg install -y git
git clone -b claude/sleepy-fermat-hj9eo6 https://github.com/rodrigomigl54-png/jarvis-prototip.git
cd jarvis-prototip
bash scripts/termux-install.sh
```
Skripta na kraju pita kako da te zove i traži da nalepiš Gemini (i opciono Groq) ključ.

### 4. Ključevi
Minimum: **`GEMINI_API_KEY`**. Preporučeno i **`GROQ_API_KEY`** (rezervni LLM + prepoznavanje glasa).
Instalacija ih pita sama; kasnije ih menjaš sa `nano .env` (snimi: Ctrl+O pa Enter, izađi: Ctrl+X).

- **Gemini (besplatno):** <https://aistudio.google.com/apikey> → *Create API key* → kopiraj.
- **Groq (besplatno):** <https://console.groq.com/keys> → *Create API Key* → kopiraj.

⚠️ Besplatni tierovi imaju ograničen broj zahteva, a Gemini free tier može da koristi tvoje podatke
za treniranje. Za veću privatnost: plaćeni Anthropic (Claude Haiku je jeftin).

### 5. Proveri dozvole i pokreni
```bash
termux-sms-list -l 1; termux-call-log -l 1; termux-contact-list | head
./scripts/start.sh --open
```
Prvi put će Android tražiti dozvole — dozvoli sve. HUD se otvori sam (link sa ključem je i u
`data/hud_url.txt`). Posle restarta telefona Jarvis se pali sam (Termux:Boot).

---

## Google: Gmail i kalendar (besplatno, ~10 minuta, jednom)

1. Idi na <https://console.cloud.google.com> → gore **Select project → New project** → ime „Jarvis” → Create.
2. **APIs & Services → Library**: nađi i uključi (**Enable**) **Gmail API** i **Google Calendar API**.
3. **Google Auth Platform / OAuth consent screen** → Get started → ime aplikacije „Jarvis”, tvoj mejl →
   Audience: **External** → sačuvaj. Pod **Audience → Test users** dodaj svoj Gmail.
   Zatim klikni **Publish app** (inače Google gasi pristup posle 7 dana).
4. **Clients / Credentials → Create client → OAuth client ID → Application type: Desktop app** →
   kopiraj **Client ID** i **Client secret**.
5. U `.env`:
   ```
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   GMAIL_ENABLED=true
   CALENDAR_ENABLED=true
   ```
6. Restartuj Jarvisa, u HUD-u pritisni **Poveži Google** (ili napiši `/google`), uloguj se.
   Google će reći „aplikacija nije verifikovana” — to je tvoja aplikacija: **Advanced → Go to Jarvis**.

Jarvis onda svake 2 minute gleda nepročitane mejlove u *Primary*, pravi kratak sažetak i nacrt
odgovora (newslettere i „no-reply” samo sažme), a ti odobriš slanje.

---

## WhatsApp — dva režima

**`WHATSAPP_MODE=notifications` (podrazumevano, bezbedno):** Jarvis čita WhatsApp poruke iz
notifikacija i pravi nacrt odgovora. Kad pritisneš ✅, otvori se WhatsApp sa već upisanim tekstom —
ti samo pritisneš Pošalji. Ništa neoficijelno, nema rizika od blokade. Ograničenja: Jarvis vidi samo
ono što piše u notifikaciji, a za odgovor osoba mora da bude u tvojim kontaktima (zbog broja).

**`WHATSAPP_MODE=bridge` (neoficijelno, automatski, RIZIČNO):**
> ⚠️ Za lični WhatsApp **ne postoji zvaničan besplatan API**. Most koristi neoficijelnu biblioteku
> Baileys, što je **protiv WhatsApp pravila — broj može biti trajno blokiran**. Koristiš na svoju odgovornost.

Ako ipak želiš: u `.env` stavi `WHATSAPP_MODE=bridge`, `WHATSAPP_NUMBER=38164…` (tvoj broj bez +)
i `WHATSAPP_BRIDGE_TOKEN=` (bilo koji dug nasumičan tekst), pa ponovo pokreni
`bash scripts/termux-install.sh`. Posle `./scripts/start.sh` u HUD-u se pojavi **kod za povezivanje**:
WhatsApp → Povezani uređaji → Poveži uređaj → **Poveži brojem telefona** → upiši kod.
I dalje važi: ništa ne odlazi bez tvog ✅.

Za buduću verziju za firme pravi put je zvanični **WhatsApp Business (Cloud) API**.

---

## Pozivi — šta je moguće

- **Propušten poziv:** Jarvis ti kaže ko je zvao i kontekst („Marko — poslednji kontakt pre 3 dana
  (WhatsApp): ‚Kad završavaš sajt?‘”) i predloži poruku — ti odobriš. Na **običan** poziv odgovara
  **SMS-om**, na **WhatsApp** poziv **WhatsApp porukom** (`FOLLOWUP_CHANNEL=auto`; može i `sms`/`whatsapp`).
- **„Pozovi Marka”:** posle tvog ✅ telefon okrene broj, ti pričaš.
- **AI se javlja umesto tebe / Jarvis tebe zove i priča:** nije moguće besplatno — Android ne pušta
  aplikacije da govore u GSM pozivu. Rešenje je plaćeni **Twilio** modul (broj + preusmeravanje kad se
  ne javiš; Jarvis pozdravi na srpskom, uzme poruku, pošalje ti transkript). Okvirno nekoliko dolara do
  ~15 $ mesečno, zavisno od minuta i cene preusmeravanja kod tvog operatera. **Nije uključen** —
  javi ako želiš da ga napravim.
- Besplatna zamena za „Jarvis me zove”: hitne stvari i podsetnici stižu kao glasna notifikacija i
  Jarvis ih **izgovori naglas** na telefonu (osim u tihim satima 23–08).

---

## Kako pričaš sa Jarvisom

Primeri (glasom ili tekstom):
- „podseti me sutra u 10 da pozovem Marka”
- „dodaj zadatak: završiti sajt za Veritas do petka”, „šta imam danas?”
- „javi Ani na WhatsApp da kasnim 10 minuta” → nacrt → ✅
- „pozovi Marka” → ✅ → telefon zove
- „pošalji Ani mejl da sastanak pomeramo na 11” → nacrt → ✅
- „ubaci u kalendar zubar u četvrtak u 9”, „šta imam u kalendaru sutra?”
- „kakvo je vreme ovog vikenda?”, „potraži radno vreme Ideje na Limanu”
- „sačuvaj ovo za kanal: https://…” → beleška sa tagom
- „zapamti da pijem kafu bez šećera”
- „blokiraj broj 0601234567”, „Mami odgovaraj bez pitanja na WhatsApp-u” (auto pravilo)

Komande: `/pomoc`, `/zadaci`, `/gotovo N`, `/danas`, `/beleske [tag]`, `/memorija`, `/zaboravi N`,
`/cekanje`, `/rezim tekst|glas|oba`, `/dnd on|off`, `/stop`, `/nastavi`, `/log`, `/kontakti`, `/google`, `/reset`.

**Dnevni ritam:** 08:00 jutarnji brifing (vreme, kalendar, zadaci, propušteno od juče), 21:00 večernji
rezime, opomena za zadatke koji kasne (najviše jednom dnevno po zadatku), tihi sati 23:00–08:00,
rezervna kopija baze svake noći (`data/backups/`, čuva 7 dana — ostaje na telefonu, nigde se ne šalje).

---

## Bezbednost i privatnost

- Svi ključevi su u `.env` (nije u git-u). HUD sluša **samo na telefonu** (127.0.0.1) i traži ključ.
- **Odobravanje je u kodu:** samo `Executor` šalje, i samo akcije sa statusom „odobreno”. Dupli klik ne
  može poslati dvaput. `/stop` blokira sve.
- **Tuđe poruke su podaci, ne naredbe:** poruke, mejlovi i web stranice ne mogu da upravljaju Jarvisom.
  Nacrte piše poseban model **bez alata i bez tvojih privatnih podataka**, a odgovor može da ode samo
  osobi koja je pisala, i to tek posle ✅. Kad Jarvis u istom zahtevu pročita tuđi sadržaj, blokiraju se
  alati koji šalju podatke napolje (testovi u `tests/`).
- **Audit log:** svaki nacrt, izmena, odobrenje, odbijanje i slanje — `/log`.
- Kontakti: blokiranje, lista dozvoljenih (ako postoji, nacrti samo za njih), grupe se ignorišu.

---

## Troškovi

| Stavka | Cena |
|---|---|
| Jarvis, Termux, F-Droid aplikacije | 0 |
| Gemini / Groq (free tier) | 0 (uz ograničenja) |
| edge-tts glas, DuckDuckGo, Open-Meteo | 0 |
| Gmail + Calendar API | 0 |
| WhatsApp (notifikacije) | 0 |
| SMS koje Jarvis pošalje | po tarifi tvog operatera |
| Anthropic Claude (opciono) | plaćeno po upotrebi, Haiku je jeftin |
| Twilio pozivi (opciono, nije uključen) | okvirno do ~15 $/mesec |

---

## Na računaru umesto telefona (opciono)

Bez funkcija telefona (pozivi/SMS/WhatsApp notifikacije), ali sa HUD-om, Gmail-om, kalendarom i zadacima:
```bash
cp .env.example .env    # popuni
docker compose up -d    # HUD: link sa ključem u: docker compose logs jarvis | grep HUD
```
Ili bez Dockera: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt && python -m jarvis`.

Za 24/7 bez telefona: **Oracle Cloud Always Free** VM (Ubuntu) + Docker Compose. HUD tada otvaraš preko
SSH tunela (`ssh -L 8765:127.0.0.1:8765 korisnik@server`) — nikad ga ne izlaži javno.

---

## Za programere

```
jarvis/
  core.py            spaja sve delove; HUD i Telegram pričaju samo sa njim
  agent.py           petlja LLM + alati (sa zaštitom od ubačenih instrukcija)
  llm/               Gemini/Groq/Ollama (OpenAI-kompatibilno), Anthropic, automatsko prebacivanje
  approval/          red čekanja + executor (jedino mesto koje šalje)
  channels/          SMS, poziv, WhatsApp (notifikacije / most), test
  google.py          OAuth, Gmail (kanal + watcher), kalendar
  phone/             Termux:API, brojevi, notifikacije/glas na telefonu
  watchers.py        pozivi, SMS, WhatsApp notifikacije (pamte šta su već videli)
  inbox.py           dolazne poruke i propušteni pozivi -> sažetak + nacrt
  drafting.py        nacrti tvojim stilom (uči iz odobrenih/izmenjenih odgovora)
  notify.py          sva obaveštenja: HUD, telefon, Telegram; DND i tihi sati
  scheduler.py       podsetnici, brifing, rezime, opomene, backup
  tools/             jedan fajl = grupa alata, automatska registracija (@tool)
  web/               HUD server (aiohttp) i statični HUD (HTML/CSS/JS)
  bot/               opcioni Telegram bot
whatsapp-bridge/     opcioni neoficijelni WhatsApp most (Node.js, Baileys)
scripts/             instalacija i pokretanje na Termux-u
tests/               pytest
```

Testovi: `pip install -r requirements-dev.txt && pytest`. Novi alat: napravi fajl u `jarvis/tools/`
i dekoriši async funkciju sa `@tool(...)`.
