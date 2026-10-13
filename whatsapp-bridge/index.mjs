// OPTIONAL, UNOFFICIAL WhatsApp bridge for Jarvis (WHATSAPP_MODE=bridge).
//
// WARNING: this logs into your personal WhatsApp as a "linked device" through
// the unofficial Baileys library. That breaks WhatsApp's Terms of Service and
// your number CAN BE BANNED. Jarvis works without it (WHATSAPP_MODE=notifications).
//
// What it does:
//   * incoming private messages  -> POST {JARVIS_URL}/api/hooks/whatsapp
//   * POST /send {to, text}      -> sends a WhatsApp message
// It only listens on 127.0.0.1 and every request needs the shared token.

import http from 'node:http'
import { readFileSync, existsSync } from 'node:fs'
import makeWASocket, {
  Browsers,
  DisconnectReason,
  isJidGroup,
  jidNormalizedUser,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys'

// --- config: read the same .env Jarvis uses -------------------------------
function loadEnv(path) {
  const env = {}
  if (!existsSync(path)) return env
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/)
    if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '')
  }
  return env
}
const env = { ...loadEnv(new URL('../.env', import.meta.url).pathname), ...process.env }
const TOKEN = env.WHATSAPP_BRIDGE_TOKEN
const PORT = Number(new URL(env.WHATSAPP_BRIDGE_URL || 'http://127.0.0.1:8766').port || 8766)
const JARVIS = `http://127.0.0.1:${env.HUD_PORT || 8765}`
const MY_NUMBER = (env.WHATSAPP_NUMBER || '').replace(/\D/g, '')
const INCLUDE_GROUPS = ['1', 'true', 'da', 'yes'].includes((env.INCLUDE_GROUPS || '').toLowerCase())

if (!TOKEN) {
  console.error('WHATSAPP_BRIDGE_TOKEN is missing in .env')
  process.exit(1)
}

const silentLogger = {
  level: 'silent', trace() {}, debug() {}, info() {}, warn() {}, error() {}, fatal() {},
  child() { return silentLogger },
}

let sock = null
let ready = false

async function postToJarvis(path, body) {
  try {
    await fetch(JARVIS + path, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-bridge-token': TOKEN },
      body: JSON.stringify(body),
    })
  } catch (e) {
    console.error('Jarvis unreachable:', e.message)
  }
}

function textOf(msg) {
  const m = msg.message || {}
  return (
    m.conversation ||
    m.extendedTextMessage?.text ||
    m.imageMessage?.caption ||
    m.videoMessage?.caption ||
    (m.audioMessage ? '[glasovna poruka]' : '') ||
    (m.imageMessage ? '[slika]' : '') ||
    (m.documentMessage ? `[dokument] ${m.documentMessage.fileName || ''}` : '')
  )
}

async function connect() {
  const { state, saveCreds } = await useMultiFileAuthState(new URL('./auth', import.meta.url).pathname)
  sock = makeWASocket({ auth: state, logger: silentLogger, browser: Browsers.ubuntu('Jarvis') })
  sock.ev.on('creds.update', saveCreds)

  if (!sock.authState.creds.registered) {
    if (!MY_NUMBER) {
      console.error('Set WHATSAPP_NUMBER=381641234567 in .env to link with a pairing code.')
      process.exit(1)
    }
    setTimeout(async () => {
      const code = await sock.requestPairingCode(MY_NUMBER)
      console.log(`\n>>> WhatsApp pairing code: ${code}`)
      console.log('    WhatsApp > Linked devices > Link a device > Link with phone number instead\n')
      await postToJarvis('/api/hooks/whatsapp/pairing', { code })
    }, 3000)
  }

  sock.ev.on('connection.update', ({ connection, lastDisconnect }) => {
    if (connection === 'open') {
      ready = true
      console.log('WhatsApp bridge connected.')
    }
    if (connection === 'close') {
      ready = false
      const code = lastDisconnect?.error?.output?.statusCode
      if (code === DisconnectReason.loggedOut) {
        console.error('Logged out. Delete whatsapp-bridge/auth and link again.')
        process.exit(1)
      }
      setTimeout(connect, 5000)
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return
    for (const msg of messages) {
      if (msg.key.fromMe) continue
      const chatId = msg.key.remoteJid
      if (!chatId || chatId === 'status@broadcast') continue
      const group = isJidGroup(chatId)
      if (group && !INCLUDE_GROUPS) continue
      const text = textOf(msg)
      if (!text) continue
      // Prefer the phone-number JID when WhatsApp hands us a LID.
      const pnJid = msg.key.remoteJidAlt?.endsWith('@s.whatsapp.net') ? msg.key.remoteJidAlt : chatId
      const phone = pnJid.endsWith('@s.whatsapp.net') ? '+' + jidNormalizedUser(pnJid).split('@')[0] : ''
      await postToJarvis('/api/hooks/whatsapp', {
        id: msg.key.id,
        chat_id: chatId,
        phone,
        name: msg.pushName || '',
        text,
        is_group: Boolean(group),
      })
    }
  })
}

// --- local HTTP API ---------------------------------------------------------
const server = http.createServer(async (req, res) => {
  const reply = (status, obj) => {
    res.writeHead(status, { 'content-type': 'application/json' })
    res.end(JSON.stringify(obj))
  }
  if (req.headers['x-bridge-token'] !== TOKEN) return reply(401, { error: 'unauthorized' })
  if (req.method === 'GET' && req.url === '/health') return reply(200, { ready })
  if (req.method !== 'POST' || req.url !== '/send') return reply(404, { error: 'not found' })

  let body = ''
  for await (const chunk of req) body += chunk
  try {
    const { to, text } = JSON.parse(body)
    if (!ready) return reply(503, { error: 'not connected' })
    if (!to || !text) return reply(400, { error: 'to and text required' })
    const jid = String(to).includes('@') ? String(to) : `${String(to).replace(/\D/g, '')}@s.whatsapp.net`
    await sock.sendMessage(jid, { text })
    reply(200, { ok: true })
  } catch (e) {
    reply(500, { error: e.message })
  }
})

server.listen(PORT, '127.0.0.1', () => console.log(`Bridge API on 127.0.0.1:${PORT}`))
connect()
