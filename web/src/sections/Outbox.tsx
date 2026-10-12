import { Fragment, useState } from 'react'
import type { Message } from '../api'

export default function Outbox({ messages }: { messages: Message[] }) {
  const [open, setOpen] = useState<number | null>(null)
  return (
    <div className="card flush">
      <table>
        <thead>
          <tr><th>To</th><th>Role</th><th>Subject</th></tr>
        </thead>
        <tbody>
          {messages.map((m, i) => (
            <Fragment key={i}>
              <tr className={`clickable ${open === i ? 'selected' : ''}`} onClick={() => setOpen(open === i ? null : i)}>
                <td className="nowrap">{m.name}</td>
                <td className="muted nowrap">{m.role}</td>
                <td>{m.subject}</td>
              </tr>
              {open === i && (
                <tr className="detail">
                  <td colSpan={3}>
                    <div className="muted small">To {m.to}</div>
                    <pre>{m.body}</pre>
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
