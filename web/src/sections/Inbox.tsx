import { Fragment, useState } from 'react'
import type { Act } from '../App'
import type { Email } from '../api'
import { shortDate } from '../format'

const TONE: Record<Email['status'], string> = {
  review: 'warn',
  reviewed: 'plain',
  moved: 'amber',
  confirmed: 'ok',
  orders: 'plain',
  ignored: 'plain',
  pending: 'plain',
}

type Props = { emails: Email[]; act: Act; busy: boolean }

export default function Inbox({ emails, act, busy }: Props) {
  const firstReview = emails.find((e) => e.status === 'review')?.id ?? null
  const [open, setOpen] = useState<string | null>(firstReview)
  return (
    <div className="card flush">
      <table>
        <thead>
          <tr><th>Date</th><th>From</th><th>Subject</th><th>What the AI did</th></tr>
        </thead>
        <tbody>
          {emails.map((e) => (
            <Fragment key={e.id}>
              <tr className={`clickable ${open === e.id ? 'selected' : ''}`} onClick={() => setOpen(open === e.id ? null : e.id)}>
                <td className="nowrap muted">{shortDate(e.date)}</td>
                <td className="nowrap">{e.from.split('@')[1]}</td>
                <td>{e.subject}</td>
                <td><span className={`tag ${TONE[e.status]}`}>{e.label}</span></td>
              </tr>
              {open === e.id && (
                <tr className="detail">
                  <td colSpan={4}>
                    <div className="muted small">From {e.from}</div>
                    <pre>{e.body}</pre>
                    {e.review && <ReviewActions email={e} act={act} busy={busy} />}
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

function ReviewActions({ email, act, busy }: { email: Email; act: Act; busy: boolean }) {
  const review = email.review!
  const [po, setPo] = useState(review.suggested_po ?? review.candidates[0]?.po ?? '')
  const [date, setDate] = useState('')
  return (
    <div className="review">
      <strong>The AI couldn't record this one</strong>
      <p className="muted">{review.problems.join('. ')}.</p>
      <p>If you know the new delivery date, enter it. Otherwise dismiss it and wait for the supplier.</p>
      <div className="review-actions">
        <select value={po} onChange={(e) => setPo(e.target.value)}>
          {review.candidates.map((c) => (
            <option key={c.po} value={c.po}>{c.material} (now {shortDate(c.delivery)})</option>
          ))}
        </select>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <button className="primary" disabled={busy || !po || !date}
          onClick={() => act({ kind: 'set_delivery', email_id: email.id, po_number: po, date }, 'Updating the schedule')}>
          Save new date
        </button>
        <button disabled={busy} onClick={() => act({ kind: 'dismiss_review', email_id: email.id }, 'Saving')}>
          Dismiss
        </button>
      </div>
    </div>
  )
}
