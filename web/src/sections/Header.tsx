import type { View } from '../api'
import { days, longDate } from '../format'

export default function Header({ view }: { view: View }) {
  const { slip_days } = view.completion
  return (
    <header className="header">
      <div>
        <span className="eyebrow">Construction projects /</span>
        <h1>{view.project.name}</h1>
        <p className="muted">{view.project.location}</p>
      </div>
      <div className="completion">
        <span className="label">Completion</span>
        <strong>{longDate(view.completion.date)}</strong>
        {slip_days > 0 && <span className="pill warn">{days(slip_days)} late</span>}
        {slip_days < 0 && <span className="pill ok">{days(-slip_days)} early</span>}
        {slip_days === 0 && <span className="pill ok">On plan</span>}
      </div>
    </header>
  )
}
