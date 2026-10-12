import { Fragment, useState } from 'react'
import type { Act } from '../App'
import type { Message } from '../api'

type Props = { messages: Message[]; act: Act; busy: boolean }

export default function Outbox({ messages, act, busy }: Props) {
  const [open, setOpen] = useState<string | null>(null)
  if (!messages.length) {
    return <div className="card muted">No drafts yet. Choose a recovery option and the AI drafts a message to everyone affected.</div>
  }
  return (
    <div className="card flush">
      <table>
        <thead>
          <tr><th>To</th><th>Subject</th><th>Status</th></tr>
        </thead>
        <tbody>
          {messages.map((m) => (
            <Fragment key={m.id}>
              <tr className={`clickable ${open === m.id ? 'selected' : ''}`} onClick={() => setOpen(open === m.id ? null : m.id)}>
                <td className="nowrap">{m.name}<div className="muted small">{m.role}</div></td>
                <td>{m.subject}</td>
                <td>
                  <span className={`tag ${m.sent ? 'ok' : 'amber'}`}>{m.sent ? 'Sent' : 'Draft, not sent'}</span>
                </td>
              </tr>
              {open === m.id && (
                <tr className="detail">
                  <td colSpan={3}>
                    <div className="muted small">To {m.to}</div>
                    <pre>{m.body}</pre>
                    <div className="review-actions">
                      <a className="button primary"
                        href={`mailto:${m.to}?subject=${encodeURIComponent(m.subject)}&body=${encodeURIComponent(m.body)}`}>
                        Open in email app
                      </a>
                      {!m.sent && (
                        <button disabled={busy} onClick={() => act({ kind: 'mark_sent', message_id: m.id }, 'Saving')}>
                          Mark as sent
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}
