# Jarvis — lični AI asistent

Jarvis radi 24/7, priča sa tobom preko **Telegrama** (tekst, kasnije i glas), vodi računa o
zadacima, poruka i pozivima — i **nikad ništa ne šalje drugima bez tvog ✅**.

> Status: **Faza 1 (Core)** gotova. Ostale faze dolaze redom (vidi dole).

---

## Glavno pravilo (ugrađeno u kod, ne samo u prompt)

Svaka odlazna poruka ide u **red čekanja** (`pending_actions`). Ti dobiješ karticu sa
dugmićima **✅ Pošalji / ✏️ Izmeni / ❌ Odbij**. Samo `Executor` može da pošalje nešto, i to
samo akciju sa statusom `approved`. LLM nema pristup ni kanalima ni executor-u — najviše što
može je da napravi nacrt. `/stop` trenutno blokira sve odlazne akcije.

---

## Struktura projekta

```
jarvis-prototip/
├── jarvis/
│   ├── __main__.py          # pokretanje: python -m jarvis
│   ├── config.py            # čitanje .env
│   ├── db.py                # SQLite šema i pristup
│   ├── audit.py             # audit log (/log)
│   ├── memory.py            # razgovor + dugoročne činjenice (/memorija)
│   ├── persona.py           # Jarvis ličnost / system prompt
│   ├── agent.py             # petlja: poruka → LLM + alati → odgovor
│   ├── llm/                 # LLM sloj nezavisan od provajdera
│   │   ├── base.py          #   zajednički interfejs + tool calling tipovi
│   │   ├── openai_compat.py #   Gemini / Groq / Ollama (svi imaju OpenAI-kompatibilan API)
│   │   └── anthropic.py     #   Claude (plaćeno, opciono)
│   ├── approval/
│   │   ├── queue.py         # red čekanja: nacrt → odobreno/izmenjeno/odbijeno
│   │   └── executor.py      # JEDINI kod koji zaista šalje
│   ├── channels/
│   │   ├── base.py          # ChannelAdapter interfejs
│   │   └── test_channel.py  # probni kanal (šalje tebi, ne drugima)
│   ├── tools/               # jedan fajl = jedan alat, automatska registracija
│   │   ├── memory_tools.py
│   │   ├── time_tool.py
│   │   └── propose_message.py
│   └── bot/
│       ├── app.py           # Telegram bot, zaključan na tvoj ID
│       └── ui.py            # kartice i dugmići
├── tests/                   # testovi (approval engine, agent, LLM)
├── data/                    # SQLite baza (ne ide u git)
├── .env.example
└── requirements.txt
```

---

## Nalozi i ključevi koji će ti trebati (ukupno)

| Faza | Šta | Cena | Obavezno? |
|---|---|---|---|
| 1 | Telegram bot token (@BotFather) | besplatno | ✅ |
| 1 | Tvoj Telegram user ID (@userinfobot) | besplatno | ✅ |
| 1 | Google Gemini API ključ (aistudio.google.com) | besplatno (free tier) | ✅ (ili Groq/Ollama) |
| 1 | Groq API ključ (console.groq.com) | besplatno | opciono (alternativni LLM) |
| 1 | Anthropic API ključ | **plaćeno** (Haiku je jeftin) | opciono |
| 2 | Groq API ključ — za Whisper (prepoznavanje govora) | besplatno | preporučeno (fallback: lokalni faster-whisper) |
| 2 | edge-tts (srpski glasovi) | besplatno, bez ključa | — |
| 4 | Telegram `api_id` / `api_hash` (my.telegram.org) — tvoj lični nalog | besplatno | za odgovaranje na poruke |
| 4 | Google Cloud projekat + Gmail API OAuth | besplatno | opciono |
| 5 | MacroDroid na Android telefonu | besplatno | za pozive |
| 5 | Cloudflare nalog (Cloudflare Tunnel) | besplatno | ako server radi kod kuće |
| 6 | Twilio nalog + broj | **plaćeno** | opciono |
| 7 | Oracle Cloud Always Free ili Raspberry Pi | besplatno / jednokratno | opciono (24/7) |

⚠️ **Besplatni LLM tierovi** (Gemini, Groq) imaju ograničenja broja zahteva, a Gemini free tier
može da koristi tvoje podatke za treniranje modela. Za privatnost: Ollama (lokalno) ili plaćeni API.

---

## Pokretanje (Faza 1)

### 1. Napravi Telegram bota
1. U Telegramu otvori **@BotFather** → pošalji `/newbot`.
2. Daj mu ime (npr. `Jarvis`) i korisničko ime koje se završava na `bot` (npr. `dario_jarvis_bot`).
3. BotFather ti vrati **token** (`123456:ABC...`). To je `TELEGRAM_BOT_TOKEN`. Ne deli ga ni sa kim.

### 2. Nađi svoj Telegram ID
1. Otvori **@userinfobot** i pošalji mu bilo šta.
2. Broj koji ti vrati (`Id: 123456789`) je `OWNER_TELEGRAM_ID`.

### 3. Gemini API ključ (besplatno)
1. Idi na <https://aistudio.google.com/apikey> i uloguj se Google nalogom.
2. Klikni **Create API key** → kopiraj ključ. To je `GEMINI_API_KEY`.

### 4. Instalacija
Treba ti Python 3.12+.
```bash
git clone <ovaj repo> && cd jarvis-prototip
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # pa upiši vrednosti iz koraka 1–3
```

### 5. Pokreni
```bash
python -m jarvis
```
Pa u Telegramu otvori svog bota i pošalji `/start`.

### 6. Testovi
```bash
pytest
```

---

## Kako da testiraš Fazu 1

| Probaj | Očekivano |
|---|---|
| `/start` | Jarvis se javi i nabroji komande |
| „koliko je sati?” | tačno vreme (alat `get_current_time`) |
| „zapamti da pijem kafu bez šećera” | potvrda; `/memorija` je prikazuje sa 🗑 dugmetom |
| „kakvu kafu pijem?” | koristi zapamćenu činjenicu |
| `/test Ćao, kasnim 10 min` | kartica nacrta sa ✅ / ✏️ / ❌ |
| ✏️ Izmeni → pošalji novi tekst | nova kartica sa izmenjenim tekstom |
| ✅ Pošalji | stigne ti „🧪 [test kanal] Poslato…” |
| „pošalji Marku na test kanal da kasnim” | Jarvis napravi nacrt, NE šalje sam |
| `/stop`, pa ✅ na nekom nacrtu | odbije: „Pauzirano” · `/nastavi` vraća |
| `/log` | poslednjih 20 akcija (nacrt, izmena, odobreno, poslato…) |
| Neko drugi piše tvom botu | bot ga potpuno ignoriše |

---

## Faze
1. ✅ **Core** — bot zaključan na tvoj ID, LLM sloj sa alatima, memorija, red odobravanja, audit log, testovi
2. ⏳ **Glas** — prepoznavanje glasovnih poruka, odgovori glasom, `/rezim`
3. ⏳ **Zadaci** — zadaci, podsetnici, jutarnji brifing, večernji rezime
4. ⏳ **Poruke** — tvoj lični Telegram (Telethon), Gmail (opciono)
5. ⏳ **Pozivi** — MacroDroid webhook, Cloudflare Tunnel
6. ⏳ **Opciono plaćeno** — Twilio, WhatsApp (sa upozorenjem)
7. ⏳ **Deploy** — Docker Compose, 24/7 hosting, tabela troškova
