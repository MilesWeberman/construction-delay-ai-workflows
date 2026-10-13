// The server keeps no state: we send this browser's own events (saved in
// localStorage) with every request, and store what comes back.

export type Option = {
  number: number
  title: string
  strategy: 'resequence' | 'accelerate' | 'supply'
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

export type Review = {
  problems: string[]
  suggested_po: string | null
  candidates: { po: string; material: string; delivery: string }[]
}

export type Email = {
  id: string
  date: string
  from: string
  subject: string
  body: string
  status: 'review' | 'reviewed' | 'moved' | 'confirmed' | 'orders' | 'ignored' | 'pending'
  label: string
  review: Review | null
}

export type Material = {
  po: string
  material: string
  supplier: string
  delivery: string
  was: string | null
  status: 'on_track' | 'confirmed' | 'unmatched' | 'late_slips' | 'late_recovered' | 'late_absorbed' | 'late_unchecked'
  label: string
  needed_for: string | null
}

export type Message = {
  id: string
  to: string
  name: string
  role: string
  subject: string
  body: string
  plan: string
  sent: boolean
}

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
  counts: { review: number; drafts: number }
  ai_ready: boolean
}

export type Action =
  | { kind: 'link'; links: [string, string][] }
  | { kind: 'choose'; options_event: number; number: number }
  | { kind: 'chat'; text: string }
  | { kind: 'set_delivery'; email_id: string; po_number: string; date: string }
  | { kind: 'dismiss_review'; email_id: string }
  | { kind: 'mark_sent'; message_id: string }

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
