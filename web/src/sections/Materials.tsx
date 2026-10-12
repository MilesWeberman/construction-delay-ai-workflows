import type { Material } from '../api'
import { longDate } from '../format'

const STATUS = {
  ordered: { label: 'Ordered', tone: 'plain' },
  confirmed: { label: 'Confirmed', tone: 'ok' },
  moved: { label: 'Moved', tone: 'amber' },
}

export default function Materials({ items }: { items: Material[] }) {
  return (
    <div className="card flush">
      <table>
        <thead>
          <tr><th>Material</th><th>Supplier</th><th>Delivery</th><th>Status</th><th>Needed for</th></tr>
        </thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.po}>
              <td>{m.material}<div className="muted small">{m.po}</div></td>
              <td>{m.supplier}</td>
              <td className="nowrap">{longDate(m.delivery)}</td>
              <td><span className={`tag ${STATUS[m.status].tone}`}>{STATUS[m.status].label}</span></td>
              <td>{m.needed_for ?? <span className="muted">Not matched yet</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
