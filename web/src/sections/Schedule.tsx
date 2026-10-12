import dayGridPlugin from '@fullcalendar/daygrid'
import listPlugin from '@fullcalendar/list'
import FullCalendar from '@fullcalendar/react'
import type { View } from '../api'

const STYLE = {
  activity: { backgroundColor: '#eef1f5', textColor: '#1f2937', prefix: '' },
  delivery: { backgroundColor: '#e6f4ea', textColor: '#14532d', prefix: 'Delivery: ' },
  delivery_moved: { backgroundColor: '#fdecdc', textColor: '#9a3412', prefix: 'Moved: ' },
}

export default function Schedule({ view }: { view: View }) {
  const events = view.calendar.map((item) => {
    const style = STYLE[item.kind]
    return {
      title: style.prefix + item.title,
      start: item.start,
      end: item.end ?? undefined,
      allDay: true,
      backgroundColor: style.backgroundColor,
      borderColor: 'transparent',
      textColor: style.textColor,
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
        eventDidMount={(info) => {
          info.el.title = info.event.title // full name on hover
        }}
      />
      <div className="legend muted small">
        <span><i style={{ background: STYLE.activity.backgroundColor }} />Task</span>
        <span><i style={{ background: STYLE.delivery.backgroundColor }} />Delivery</span>
        <span><i style={{ background: STYLE.delivery_moved.backgroundColor }} />Delivery moved</span>
      </div>
    </div>
  )
}
