// The server keeps no state: we send this browser's own events (saved in
// localStorage) with every request, and store what comes back.

export type Option = {
  number: number
  title: string
  recovered_days: number
  new_finish: string
  cost: string
  rationale: string
  risks: string
}

export type Recovery = { event: number; chosen: string | null; options: Option[] }

export type Alert = {
  kind: 'delay' | 'suggestion'
  headline: string
  slip_days: number
  recovery: Recovery | null
}

export type Link = { po: string; material: string; supplier: string; delivery: string; suggested: string | null }

export type CalendarItem = {
  title: string
  start: string
  end: string | null
  kind: 'activity' | 'delivery' | 'delivery_moved'
}

export type Email = {
  id: string
  date: string
  from: string
  subject: string
  body: string
  result: string
  problems: string[]
}

export type Material = {
  po: string
  material: string
  supplier: string
  delivery: string
  status: 'ordered' | 'confirmed' | 'moved'
  needed_for: string | null
}

export type Message = { to: string; name: string; role: string; subject: string; body: string; plan: string }

export type View = {
  project: { name: string; location: string }
  completion: { date: string; planned: string; slip_days: number }
  alerts: Alert[]
  absorbed: string[]
  links: Link[]
  activities: { id: string; name: string }[]
  calendar: CalendarItem[]
  calendar_start: string
  inbox: Email[]
  materials: Material[]
  outbox: Message[]
  chat: { role: 'user' | 'assistant'; text: string }[]
  ai_ready: boolean
}

export type Action =
  | { kind: 'link'; links: [string, string][] }
  | { kind: 'choose'; options_event: number; number: number }
  | { kind: 'chat'; text: string }

type Saved = { seed: string | null; events: unknown[] }

const STORAGE_KEY = 'delay-ai-demo'

function load(): Saved {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '') as Saved
  } catch {
    return { seed: null, events: [] }
  }
}

export function resetSaved() {
  localStorage.removeItem(STORAGE_KEY)
}

export async function fetchView(action?: Action): Promise<View> {
  const response = await fetch('/api/view', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...load(), action }),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? `Request failed (${response.status})`)
  }
  const { seed, events, view } = await response.json()
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ seed, events }))
  } catch {
    // storage full or blocked: the demo still works, it just won't be remembered
  }
  return view as View
}
