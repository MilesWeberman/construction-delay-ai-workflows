import type { EventHoveringArg } from '@fullcalendar/core'
import dayGridPlugin from '@fullcalendar/daygrid'
import listPlugin from '@fullcalendar/list'
import FullCalendar from '@fullcalendar/react'
import { memo, useEffect, useMemo, useState } from 'react'
import type { CalendarItem, View } from '../api'
import { longDate } from '../format'

const STYLE = {
  activity: { backgroundColor: '#eef1f5', textColor: '#1f2937', kind: 'Task' },
  delivery: { backgroundColor: '#e6f4ea', textColor: '#14532d', kind: 'Delivery' },
  delivery_moved: { backgroundColor: '#fdecdc', textColor: '#9a3412', kind: 'Delivery moved' },
}

type Tip = { title: string; when: string; kind: string; x: number; y: number }
type Hover = (tip: Tip | null) => void

export default function Schedule({ view }: { view: View }) {
  const [tip, setTip] = useState<Tip | null>(null)

  // A safety net: hide the tooltip if the page scrolls under the pointer.
  useEffect(() => {
    const hide = () => setTip(null)
    window.addEventListener('scroll', hide, true)
    return () => window.removeEventListener('scroll', hide, true)
  }, [])

  return (
    <div className="card calendar" onMouseLeave={() => setTip(null)}>
      <Calendar items={view.calendar} start={view.calendar_start} onHover={setTip} />
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

// Memoised so showing the tooltip doesn't re-render the calendar: a re-render
// replaces the hovered element, and then its mouse-leave never fires.
const Calendar = memo(function Calendar({ items, start, onHover }: { items: CalendarItem[]; start: string; onHover: Hover }) {
  const events = useMemo(
    () =>
      items.map((item) => {
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
      }),
    [items],
  )
  const enter = (info: EventHoveringArg) => {
    const box = info.el.getBoundingClientRect()
    const { kind, last } = info.event.extendedProps
    const first = info.event.startStr
    onHover({
      title: info.event.title,
      kind,
      when: last && last !== first ? `${longDate(first)} to ${longDate(last)}` : longDate(first),
      x: Math.min(box.left, window.innerWidth - 340),
      y: box.bottom + 6,
    })
  }
  return (
    <FullCalendar
      plugins={[dayGridPlugin, listPlugin]}
      initialView="dayGridMonth"
      initialDate={start}
      headerToolbar={{ left: 'title', right: 'today prev,next dayGridMonth,listMonth' }}
      buttonText={{ today: 'Today', month: 'Month', list: 'List' }}
      firstDay={1}
      height="auto"
      dayMaxEvents={4}
      events={events}
      eventMouseEnter={enter}
      eventMouseLeave={() => onHover(null)}
    />
  )
})

// Calendar ends are exclusive; show the last day of the task.
function lastDay(end: string) {
  const d = new Date(`${end}T00:00:00`)
  d.setDate(d.getDate() - 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
