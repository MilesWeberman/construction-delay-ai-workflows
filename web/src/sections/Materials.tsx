import type { Material } from '../api'
import { longDate, shortDate } from '../format'

const TONE: Record<Material['status'], string> = {
  on_track: 'plain',
  confirmed: 'ok',
  unmatched: 'plain',
  late_slips: 'warn',
  late_recovered: 'ok',
  late_absorbed: 'amber',
  late_unchecked: 'warn',
}

const goTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })

export default function Materials({ items }: { items: Material[] }) {
  return (
    <div className="card flush">
      <table>
        <thead>
          <tr><th>Material</th><th>Delivery</th><th>Needed for</th><th>Status</th></tr>
        </thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.po}>
              <td>{m.material}<div className="muted small">{m.supplier} · {m.po}</div></td>
              <td className="nowrap">
                {longDate(m.delivery)}
                {m.was && <div className="muted small">was {shortDate(m.was)}</div>}
              </td>
              <td>{m.needed_for ?? <span className="muted">Not matched yet</span>}</td>
              <td>
                <span className={`tag ${TONE[m.status]}`}>{m.label}</span>
                {m.status === 'late_slips' && (
                  <button className="link small action" onClick={() => goTo('alerts')}>See recovery options</button>
                )}
                {(m.status === 'late_unchecked' || m.status === 'unmatched') && (
                  <button className="link small action" onClick={() => goTo('matching')}>Match to a task</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
