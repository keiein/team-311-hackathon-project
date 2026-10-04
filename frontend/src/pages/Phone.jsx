import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ConversationProvider, useConversation } from '@elevenlabs/react'

// The "Calgary 311 Intake" voice agent on ElevenLabs. It is a public agent, so its ID is all this page needs.
// The ID is kept out of the repo: set VITE_ELEVENLABS_AGENT_ID in frontend/.env.
const AGENT_ID = import.meta.env.VITE_ELEVENLABS_AGENT_ID
const HOTLINE = '311'

const KEYS = [
  ['1', ''], ['2', 'ABC'], ['3', 'DEF'],
  ['4', 'GHI'], ['5', 'JKL'], ['6', 'MNO'],
  ['7', 'PQRS'], ['8', 'TUV'], ['9', 'WXYZ'],
  ['*', ''], ['0', '+'], ['#', ''],
]

const ROUND_BUTTON_CLASS =
  'flex h-16 w-16 flex-col items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20 active:bg-white/30'

function formatTime(seconds) {
  const minutes = String(Math.floor(seconds / 60)).padStart(2, '0')
  return `${minutes}:${String(seconds % 60).padStart(2, '0')}`
}

// Round picture beside each chat bubble: a headset for the AI agent, a person for the caller.
function Avatar({ fromAgent }) {
  return (
    <span
      aria-hidden="true"
      className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${
        fromAgent ? 'bg-sidebar text-white' : 'bg-calgary-red-light text-calgary-red'
      }`}
    >
      <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        {fromAgent ? (
          <>
            <path d="M4 13v-1a8 8 0 0 1 16 0v1" />
            <rect x="2.5" y="13" width="4" height="6" rx="1.5" />
            <rect x="17.5" y="13" width="4" height="6" rx="1.5" />
            <path d="M19.5 19v.5a2.5 2.5 0 0 1-2.5 2.5h-3" />
          </>
        ) : (
          <>
            <circle cx="12" cy="8" r="4" />
            <path d="M4 21a8 8 0 0 1 16 0" />
          </>
        )}
      </svg>
    </span>
  )
}

function Keypad({ onPress }) {
  return (
    <div className="grid grid-cols-3 justify-items-center gap-x-5 gap-y-3">
      {KEYS.map(([digit, letters]) => (
        <button key={digit} type="button" onClick={() => onPress(digit)} className={ROUND_BUTTON_CLASS}>
          <span className="text-2xl leading-none">{digit}</span>
          <span className="mt-0.5 h-3 text-[9px] tracking-widest text-white/50">{letters}</span>
        </button>
      ))}
    </div>
  )
}

function PhoneCall() {
  const [screen, setScreen] = useState('dialer') // 'dialer' -> 'call' -> 'ended'
  const [dialed, setDialed] = useState('')
  const [pressed, setPressed] = useState('') // keys pressed during the call
  const [seconds, setSeconds] = useState(0)
  const [messages, setMessages] = useState([])
  const [notice, setNotice] = useState('')
  const lastKey = useRef({ text: '', at: 0 })
  const transcriptEnd = useRef(null)

  const addMessage = (role, text) =>
    setMessages((list) => [...list, { id: list.length, role, text }])

  const conversation = useConversation({
    onMessage: ({ message, role, source }) => {
      const fromAgent = role === 'agent' || source === 'ai'
      // A key press is already on screen as a key bubble, so skip its echo.
      const isKeyEcho =
        !fromAgent && message.trim() === lastKey.current.text && Date.now() - lastKey.current.at < 4000
      if (!isKeyEcho) addMessage(fromAgent ? 'agent' : 'caller', message)
    },
    onDisconnect: () => {
      setMessages([])
      setScreen((current) => (current === 'call' ? 'ended' : current))
    },
    onError: (message) => setNotice(typeof message === 'string' ? message : 'The call could not connect.'),
  })
  const { status, isSpeaking, isMuted } = conversation
  const connected = status === 'connected'

  useEffect(() => {
    if (screen !== 'call' || !connected) return undefined
    const timer = setInterval(() => setSeconds((value) => value + 1), 1000)
    return () => clearInterval(timer)
  }, [screen, connected])

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function startCall() {
    if (dialed !== HOTLINE) {
      setNotice(`This demo phone can only call ${HOTLINE}.`)
      return
    }
    setNotice('')
    setMessages([])
    setPressed('')
    setSeconds(0)
    setScreen('call')
    conversation.startSession()
  }

  function pressKeyInCall(digit) {
    if (!connected) return
    lastKey.current = { text: digit, at: Date.now() }
    setPressed((value) => value + digit)
    addMessage('key', digit)
    conversation.sendUserMessage(digit)
  }

  function hangUp() {
    conversation.endSession()
    setMessages([])
    setScreen('ended')
  }

  function backToDialer() {
    setDialed('')
    setNotice('')
    setMessages([])
    setScreen('dialer')
  }

  return (
    <div className="flex h-full w-full bg-panel">
      {/* The resident's phone */}
      <section className="flex w-[440px] shrink-0 items-center justify-center p-6" aria-label="Resident phone">
        <div className="flex h-[700px] max-h-full w-[340px] flex-col rounded-[2.5rem] bg-sidebar px-6 py-8 text-white shadow-xl">
          {screen === 'dialer' && (
            <>
              <div className="flex h-24 flex-col items-center justify-end">
                <p className="h-10 text-4xl tracking-widest">{dialed}</p>
                <p className="mt-2 h-5 text-center text-xs text-calgary-red-light">{notice}</p>
              </div>
              <div className="mt-6 flex-1">
                <Keypad onPress={(digit) => setDialed((value) => (value + digit).slice(0, 12))} />
              </div>
              <div className="grid grid-cols-3 items-center justify-items-center">
                <span />
                <button
                  type="button"
                  onClick={startCall}
                  aria-label="Call"
                  className="flex h-16 w-16 items-center justify-center rounded-full bg-green-600 text-sm font-semibold hover:bg-green-500"
                >
                  Call
                </button>
                <button
                  type="button"
                  onClick={() => setDialed((value) => value.slice(0, -1))}
                  aria-label="Delete last digit"
                  className="px-3 py-2 text-sm text-white/70 hover:text-white"
                >
                  Delete
                </button>
              </div>
            </>
          )}

          {screen === 'call' && (
            <>
              <div className="flex h-28 flex-col items-center justify-end text-center">
                <p className="text-3xl font-semibold">{HOTLINE}</p>
                <p className="mt-1 text-sm text-white/70">City of Calgary</p>
                <p className="mt-2 text-sm" aria-live="polite">
                  {connected ? formatTime(seconds) : 'Calling...'}
                  {connected && (isSpeaking ? ' · Agent speaking' : ' · Listening')}
                </p>
                <p className="h-5 text-lg tracking-widest text-white/80">{pressed}</p>
              </div>
              <div className="mt-4 flex-1">
                <Keypad onPress={pressKeyInCall} />
              </div>
              <div className="grid grid-cols-3 items-center justify-items-center">
                <button
                  type="button"
                  onClick={() => conversation.setMuted(!isMuted)}
                  aria-pressed={isMuted}
                  className="px-3 py-2 text-sm text-white/70 hover:text-white"
                >
                  {isMuted ? 'Unmute' : 'Mute'}
                </button>
                <button
                  type="button"
                  onClick={hangUp}
                  aria-label="Hang up"
                  className="flex h-16 w-16 items-center justify-center rounded-full bg-calgary-red text-sm font-semibold hover:bg-calgary-red-dark"
                >
                  End
                </button>
                <span />
              </div>
            </>
          )}

          {screen === 'ended' && (
            <div className="flex flex-1 flex-col items-center justify-center text-center">
              <p className="text-2xl font-semibold">Call ended</p>
              <p className="mt-2 text-sm text-white/70">{formatTime(seconds)}</p>
              {notice && <p className="mt-3 text-xs text-calgary-red-light">{notice}</p>}
              <button
                type="button"
                onClick={backToDialer}
                className="mt-8 rounded-full bg-white/10 px-6 py-3 text-sm hover:bg-white/20"
              >
                Back to keypad
              </button>
            </div>
          )}
        </div>
      </section>

      {/* What is being said on the call */}
      <section className="flex min-w-0 flex-1 flex-col border-l border-border bg-white" aria-label="Call transcript">
        <header className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-5 py-3">
          <div>
            <h2 className="text-2xl font-semibold text-text">Live call transcript</h2>
            <p className="text-base text-text-muted">
              {screen === 'call' && connected && 'On a call with the 311 voice agent.'}
              {screen === 'call' && !connected && 'Connecting to the 311 voice agent...'}
              {screen === 'dialer' && `Dial ${HOTLINE} on the phone and press Call.`}
              {screen === 'ended' && 'The call has ended.'}
            </p>
          </div>
          <Link to="/map" className="text-sm text-calgary-red hover:underline">
            Open map
          </Link>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {messages.length === 0 && screen !== 'ended' && (
            <p className="text-lg text-text-muted">The conversation will appear here once the call starts.</p>
          )}
          <ul className="flex flex-col gap-4">
            {messages.map((item) => {
              if (item.role === 'key') {
                return (
                  <li key={item.id} className="self-center rounded-full bg-panel px-4 py-1.5 text-base text-text-muted">
                    Caller pressed {item.text}
                  </li>
                )
              }
              const fromAgent = item.role === 'agent'
              return (
                <li
                  key={item.id}
                  className={`flex max-w-[80%] items-end gap-3 ${fromAgent ? 'self-start' : 'flex-row-reverse self-end'}`}
                >
                  <Avatar fromAgent={fromAgent} />
                  <div className={`flex flex-col ${fromAgent ? 'items-start' : 'items-end'}`}>
                    <span className="mb-1 px-1 text-sm font-medium text-text-muted">
                      {fromAgent ? '311 AI agent' : 'Caller'}
                    </span>
                    <span
                      className={`rounded-3xl px-5 py-3 text-xl leading-snug ${
                        fromAgent ? 'rounded-bl-md bg-panel text-text' : 'rounded-br-md bg-calgary-red text-white'
                      }`}
                    >
                      {item.text}
                    </span>
                  </div>
                </li>
              )
            })}
          </ul>
          <div ref={transcriptEnd} />
        </div>
      </section>
    </div>
  )
}

function Phone() {
  return (
    <ConversationProvider agentId={AGENT_ID}>
      <PhoneCall />
    </ConversationProvider>
  )
}

export default Phone
