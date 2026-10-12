import { Fragment, useState } from 'react'
import type { Email } from '../api'
import { shortDate } from '../format'

function tone(result: string) {
  if (result.startsWith('Needs')) return 'warn'
  if (result.startsWith('Delivery moved')) return 'amber'
  if (result.startsWith('Delivery confirmed')) return 'ok'
  return 'plain'
}

export default function Inbox({ emails }: { emails: Email[] }) {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <div className="card flush">
      <table>
        <thead>
          <tr><th>Date</th><th>From</th><th>Subject</th><th>Read by AI as</th></tr>
        </thead>
        <tbody>
          {emails.map((e) => (
            <Fragment key={e.id}>
              <tr className={`clickable ${open === e.id ? 'selected' : ''}`} onClick={() => setOpen(open === e.id ? null : e.id)}>
                <td className="nowrap muted">{shortDate(e.date)}</td>
                <td className="nowrap">{e.from.split('@')[1]}</td>
                <td>{e.subject}</td>
                <td>{e.result && <span className={`tag ${tone(e.result)}`}>{e.result}</span>}</td>
              </tr>
              {open === e.id && (
                <tr className="detail">
                  <td colSpan={4}>
                    <div className="muted small">From {e.from}</div>
                    {e.problems.length > 0 && <div className="note">{e.problems.join('; ')}</div>}
                    <pre>{e.body}</pre>
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
