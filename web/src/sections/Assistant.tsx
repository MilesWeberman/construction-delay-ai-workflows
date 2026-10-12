import { useEffect, useRef, useState } from 'react'
import type { Act } from '../App'
import type { View } from '../api'

const CAN_DO = [
  ['Report a delivery change', 'Pennine rang, steel now arrives 19 Jan'],
  ['Report site news', 'Storm Thursday to Monday, no crane lifts'],
  ['Try a schedule change', 'Can glazing start floor by floor during decking?'],
  ['Ask about the schedule', "Why don't the late kitchens move completion?"],
]

type Props = { view: View; act: Act; busy: string | null; onReset: () => void }

export default function Assistant({ view, act, busy, onReset }: Props) {
  const [text, setText] = useState('')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // braces matter: newer browsers return a Promise here, and React would call it
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [view.chat.length, busy])

  const send = (e: React.FormEvent) => {
    e.preventDefault()
    if (!text.trim() || busy) return
    act({ kind: 'chat', text: text.trim() }, 'Thinking')
    setText('')
  }

  return (
    <aside className="assistant">
      <div className="assistant-head">
        <h2>Assistant</h2>
        <button className="link small" onClick={onReset}>Reset demo</button>
      </div>
      <div className="messages">
        {view.chat.length === 0 && (
          <div className="can-do">
            <p className="muted">You can:</p>
            <ul>
              {CAN_DO.map(([what, example]) => (
                <li key={what}><strong>{what}</strong><span className="muted">“{example}”</span></li>
              ))}
            </ul>
          </div>
        )}
        {view.chat.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>{m.text}</div>
        ))}
        {busy === 'Thinking' && <div className="bubble assistant muted">Thinking…</div>}
        <div ref={end} />
      </div>
      {!view.ai_ready && <p className="muted small">The AI isn't configured on this server.</p>}
      <form className="composer" onSubmit={send}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Message the assistant" disabled={!!busy} />
        <button className="primary" disabled={!!busy || !text.trim()}>Send</button>
      </form>
    </aside>
  )
}
