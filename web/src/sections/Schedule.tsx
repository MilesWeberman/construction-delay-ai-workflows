import dayGridPlugin from '@fullcalendar/daygrid'
import listPlugin from '@fullcalendar/list'
import FullCalendar from '@fullcalendar/react'
import { useState } from 'react'
import type { View } from '../api'
import { longDate } from '../format'

const STYLE = {
  activity: { backgroundColor: '#eef1f5', textColor: '#1f2937', kind: 'Task' },
  delivery: { backgroundColor: '#e6f4ea', textColor: '#14532d', kind: 'Delivery' },
  delivery_moved: { backgroundColor: '#fdecdc', textColor: '#9a3412', kind: 'Delivery moved' },
}

type Tip = { title: string; when: string; kind: string; x: number; y: number }

export default function Schedule({ view }: { view: View }) {
  const [tip, setTip] = useState<Tip | null>(null)
  const events = view.calendar.map((item) => {
    const style = STYLE[item.kind]
    return {
      title: item.title,
      start: item.start,
      end: item.end ?? undefined,
      allDay: true,
      backgroundColor: style.backgroundColor,
      borderColor: 'transparent',
      textColor: style.textColor,
      extendedProps: { kind: style.kind, last: item.end ? lastDay(item.end) : null },
    }
  })
  return (
    <div className="card calendar">
      <FullCalendar
        plugins={[dayGridPlugin, listPlugin]}
        initialView="dayGridMonth"
        initialDate={view.calendar_start}
        headerToolbar={{ left: 'title', right: 'today prev,next dayGridMonth,listMonth' }}
        buttonText={{ today: 'Today', month: 'Month', list: 'List' }}
        firstDay={1}
        height="auto"
        dayMaxEvents={4}
        events={events}
        eventMouseEnter={(info) => {
          const box = info.el.getBoundingClientRect()
          const { kind, last } = info.event.extendedProps
          const start = info.event.startStr
          setTip({
            title: info.event.title,
            kind,
            when: last && last !== start ? `${longDate(start)} to ${longDate(last)}` : longDate(start),
            x: Math.min(box.left, window.innerWidth - 340),
            y: box.bottom + 6,
          })
        }}
        eventMouseLeave={() => setTip(null)}
      />
      <div className="legend muted small">
        {Object.values(STYLE).map((s) => (
          <span key={s.kind}><i style={{ background: s.backgroundColor }} />{s.kind}</span>
        ))}
      </div>
      {tip && (
        <div className="tooltip" style={{ left: tip.x, top: tip.y }}>
          <div className="muted small">{tip.kind}</div>
          <strong>{tip.title}</strong>
          <div className="small">{tip.when}</div>
        </div>
      )}
    </div>
  )
}

// Calendar ends are exclusive; show the last day of the task.
function lastDay(end: string) {
  const d = new Date(`${end}T00:00:00`)
  d.setDate(d.getDate() - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
