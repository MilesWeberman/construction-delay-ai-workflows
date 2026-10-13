import { useEffect, useState } from 'react'
import { type Action, type View, fetchView, resetSaved } from './api'
import Alerts, { Links } from './sections/Alerts'
import Assistant from './sections/Assistant'
import Header from './sections/Header'
import Inbox from './sections/Inbox'
import Materials from './sections/Materials'
import Outbox from './sections/Outbox'
import Schedule from './sections/Schedule'

// Resolves to an error message, or null if it worked.
export type Act = (action: Action, busyLabel: string) => Promise<string | null>
type Tab = 'schedule' | 'inbox' | 'outbox'

export default function App() {
  const [view, setView] = useState<View | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('schedule')

  const load = async (action?: Action, busyLabel?: string, quiet = false) => {
    setBusy(busyLabel ?? null)
    setError(null)
    try {
      setView(await fetchView(action))
      return null
    } catch (e) {
      const message = (e as Error).message
      if (!quiet) setError(message)
      return message
    } finally {
      setBusy(null)
    }
  }
  // chat errors are shown inside the chat, everything else at the top of the page
  const act: Act = (action, busyLabel) => load(action, busyLabel, action.kind === 'chat')

  useEffect(() => {
    load()
  }, [])

  if (!view) return <div className="splash">{error ?? 'Loading…'}</div>

  const tabs: [Tab, string, string | null][] = [
    ['schedule', 'Schedule', null],
    ['inbox', 'Inbox', view.counts.review ? `${view.counts.review} to review` : null],
    ['outbox', 'Outbox', view.counts.drafts ? `${view.counts.drafts} drafts` : null],
  ]

  return (
    <div className="layout">
      <main className="main">
        <Header view={view} />
        <nav className="tabs">
          {tabs.map(([id, label, badge]) => (
            <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
              {label}
              {badge && <span className="badge">{badge}</span>}
            </button>
          ))}
        </nav>
        {error && <div className="banner">{error}</div>}

        {tab === 'schedule' && (
          <>
            <Alerts view={view} act={act} busy={busy !== null} />
            <Section title="Schedule">
              <Schedule view={view} />
              {view.links.length > 0 && <Links view={view} act={act} busy={busy !== null} />}
            </Section>
            <Section title="Materials">
              <Materials items={view.materials} />
            </Section>
          </>
        )}
        {tab === 'inbox' && (
          <Section title="Inbox" note="A fixed sample inbox for the demo">
            <Inbox emails={view.inbox} act={act} busy={busy !== null} />
          </Section>
        )}
        {tab === 'outbox' && (
          <Section title="Outbox" note="Drafted by AI. Nothing is sent automatically.">
            <Outbox messages={view.outbox} act={act} busy={busy !== null} />
          </Section>
        )}
      </main>
      <Assistant
        view={view}
        act={act}
        busy={busy}
        onReset={() => {
          resetSaved()
          load()
        }}
      />
      {busy && busy !== 'Thinking' && <div className="toast">{busy}…</div>}
    </div>
  )
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="section">
      <div className="section-head">
        <h2>{title}</h2>
        {note && <span className="muted">{note}</span>}
      </div>
      {children}
    </section>
  )
}
