import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import type { Act } from '../App'
import type { View } from '../api'

const STARTERS = [
  'Pennine rang, steel now arrives 19 Jan',
  'Storm forecast 25 to 29 January, no crane lifts',
  'Can glazing start floor by floor during decking?',
  "Why don't the late lifts move completion?",
]

type Props = { view: View; act: Act; busy: string | null; onReset: () => void }

export default function Assistant({ view, act, busy, onReset }: Props) {
  const [text, setText] = useState('')
  const [pending, setPending] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const end = useRef<HTMLDivElement>(null)
  const thinking = pending !== null

  useEffect(() => {
    // braces matter: newer browsers return a Promise here, and React would call it
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [view.chat.length, pending, failed])

  useEffect(() => {
    const el = input.current // grow with the text, up to about five lines
    if (el) {
      el.style.height = 'auto'
      el.style.height = `${Math.min(el.scrollHeight, 120)}px`
    }
  }, [text])

  const send = async () => {
    const message = text.trim()
    if (!message || busy) return
    setText('')
    setFailed(null)
    setPending(message)
    const error = await act({ kind: 'chat', text: message }, 'Thinking')
    setPending(null)
    if (error) {
      setFailed(error)
      setText(message) // give it back so it can be sent again
    }
  }

  return (
    <aside className="assistant">
      <div className="assistant-head">
        <Avatar />
        <div className="grow">
          <h3>Assistant</h3>
          <div className="muted small">{view.ai_ready ? 'Knows your schedule and deliveries' : 'AI not configured on this server'}</div>
        </div>
        <button className="link small" onClick={onReset}>Reset demo</button>
      </div>

      <div className="messages">
        <Bot>
          Hi, I'm your scheduling assistant. Tell me about a **late delivery** or something
          on **site** (weather, labour, plant), ask me to **try a change**, or ask anything about
          the schedule.
        </Bot>
        {view.chat.length === 0 && !thinking && (
          <div className="starters">
            {STARTERS.map((s) => (
              <button key={s} onClick={() => { setText(s); input.current?.focus() }}>{s}</button>
            ))}
          </div>
        )}
        {view.chat.map((m, i) =>
          m.role === 'user' ? <div key={i} className="bubble user">{m.text}</div> : <Bot key={i}>{m.text}</Bot>,
        )}
        {pending && <div className="bubble user">{pending}</div>}
        {thinking && (
          <div className="bot">
            <Avatar />
            <div className="bubble reply typing" aria-label="Assistant is typing"><i /><i /><i /></div>
          </div>
        )}
        {failed && <div className="bubble error">Sorry, that didn't go through: {failed}</div>}
        <div ref={end} />
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); send() }}>
        <textarea
          ref={input}
          rows={1}
          value={text}
          placeholder="Message the assistant"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        <button className="send" aria-label="Send" disabled={!!busy || !text.trim()}>
          <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
            <path d="M3 10h12M10 4l6 6-6 6" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </form>
      <div className="muted small hint">Enter to send · Shift+Enter for a new line</div>
    </aside>
  )
}

function Bot({ children }: { children: string | string[] }) {
  return (
    <div className="bot">
      <Avatar />
      <div className="bubble reply">
        <Markdown>{Array.isArray(children) ? children.join('') : children}</Markdown>
      </div>
    </div>
  )
}

function Avatar() {
  return (
    <span className="avatar" aria-hidden="true">
      <svg viewBox="0 0 20 20" width="14" height="14">
        <path d="M10 2l1.8 4.9L17 8.7l-5.2 1.8L10 15.4 8.2 10.5 3 8.7l5.2-1.8z" fill="currentColor" />
      </svg>
    </span>
  )
}
