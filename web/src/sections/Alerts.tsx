import { useState } from 'react'
import type { Act } from '../App'
import type { Option, Recovery, View } from '../api'
import { days, shortDate } from '../format'

type Props = { view: View; act: Act; busy: boolean }

const STRATEGY = {
  resequence: 'Resequence · no extra labour',
  accelerate: 'Speed up · extra resource',
  supply: 'Supply · earlier delivery',
}

export default function Alerts({ view, act, busy }: Props) {
  return (
    <div className="alerts" id="alerts">
      {view.alerts.map((alert, i) => {
        const resolved = Boolean(alert.recovery?.chosen)
        const delay = alert.kind === 'delay'
        return (
          <div className={`card alert ${resolved ? 'resolved' : delay ? 'action' : ''}`} key={i}>
            <span className="eyebrow">
              {resolved ? 'Resolved' : delay ? 'Action needed' : 'Your suggestion'}
            </span>
            <h3>{alert.headline}</h3>
            {delay && (
              <p className={resolved ? 'muted' : 'consequence'}>
                {resolved
                  ? `It had moved completion ${days(alert.slip_days)} later. A recovery option was chosen.`
                  : `This pushes completion ${days(alert.slip_days)} later. Choose how to recover.`}
              </p>
            )}
            {alert.recovery && (
              <RecoveryOptions recovery={alert.recovery} act={act} busy={busy} open={!delay} />
            )}
          </div>
        )
      })}
      {view.absorbed.length > 0 && (
        <p className="muted small">Also late, with no effect on completion: {view.absorbed.join('; ')}.</p>
      )}
    </div>
  )
}

function RecoveryOptions({ recovery, act, busy, open }: { recovery: Recovery; act: Act; busy: boolean; open: boolean }) {
  const [shown, setShown] = useState(open)
  if (recovery.chosen) {
    return <p className="ok-text">Chosen: {recovery.chosen}. Messages to everyone affected are in the Outbox.</p>
  }
  if (!recovery.options.length) return <p className="muted">No workable way to recover was found.</p>
  return (
    <>
      {!shown && (
        <button className="primary cta" onClick={() => setShown(true)}>
          Choose how to recover ({recovery.options.length} options)
        </button>
      )}
      {shown && (
        <div className="options">
          <p className="muted small">Suggested by AI, then checked against the schedule. Pick one.</p>
          {recovery.options.map((o) => (
            <OptionRow key={o.number} option={o} busy={busy}
              onChoose={() => act({ kind: 'choose', options_event: recovery.event, number: o.number },
                'Updating the schedule and drafting messages, about a minute')} />
          ))}
        </div>
      )}
    </>
  )
}

function OptionRow({ option, busy, onChoose }: { option: Option; busy: boolean; onChoose: () => void }) {
  const [why, setWhy] = useState(false)
  return (
    <div className="option">
      <div className="grow">
        <span className={`strategy ${option.strategy}`}>{STRATEGY[option.strategy]}</span>
        <div className="option-title">{option.title}</div>
        <div className="muted small">
          {option.recovered_days > 0
            ? `Wins back ${days(option.recovered_days)} · completion ${shortDate(option.new_finish)}`
            : 'Does not bring completion forward'}
        </div>
        <div className="muted small">{option.cost}</div>
        <button className="link small" onClick={() => setWhy(!why)}>{why ? 'Less' : 'Why and risks'}</button>
        {why && (
          <div className="why">
            <p>{option.rationale}</p>
            <p><strong>Risks.</strong> {option.risks}</p>
          </div>
        )}
      </div>
      <button className="primary" disabled={busy} onClick={onChoose}>Choose</button>
    </div>
  )
}

export function Links({ view, act, busy }: Props) {
  const [picks, setPicks] = useState<Record<string, string>>({})
  const pick = (po: string, suggested: string | null) => picks[po] ?? suggested ?? view.activities[0].id
  const confirm = (pairs: [string, string][]) => act({ kind: 'link', links: pairs }, 'Updating the schedule')
  return (
    <div className="card" id="matching">
      <strong>AI matched {view.links.length} deliveries to the tasks that need them</strong>
      <p className="muted">Check each one. Once confirmed, a late delivery is checked against its task.</p>
      <div className="rows">
        {view.links.map((l) => (
          <div className="row" key={l.po}>
            <div className="grow">
              <div>{l.material}</div>
              <div className="muted small">{l.supplier} · {shortDate(l.delivery)}</div>
            </div>
            <select value={pick(l.po, l.suggested)} onChange={(e) => setPicks({ ...picks, [l.po]: e.target.value })}>
              {view.activities.map((a) => <option key={a.id} value={a.id}>Needed for: {a.name}</option>)}
            </select>
            <button disabled={busy} onClick={() => confirm([[l.po, pick(l.po, l.suggested)]])}>Confirm</button>
          </div>
        ))}
      </div>
    </div>
  )
}
