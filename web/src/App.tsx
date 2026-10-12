import { useEffect, useState } from 'react'
import { type Action, type View, fetchView, resetSaved } from './api'
import Alerts from './sections/Alerts'
import Assistant from './sections/Assistant'
import Header from './sections/Header'
import Inbox from './sections/Inbox'
import Materials from './sections/Materials'
import Outbox from './sections/Outbox'
import Schedule from './sections/Schedule'

export type Act = (action: Action, busyLabel: string) => Promise<void>

export default function App() {
  const [view, setView] = useState<View | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = async (action?: Action, busyLabel?: string) => {
    setBusy(busyLabel ?? null)
    setError(null)
    try {
      setView(await fetchView(action))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  const act: Act = (action, busyLabel) => load(action, busyLabel)

  useEffect(() => {
    load()
  }, [])

  if (!view) return <div className="splash">{error ?? 'Loading…'}</div>

  return (
    <div className="layout">
      <main className="main">
        <Header view={view} />
        {error && <div className="banner">{error}</div>}
        <Alerts view={view} act={act} busy={busy !== null} />
        <Section title="Schedule">
          <Schedule view={view} />
        </Section>
        <Section title="Inbox" note="A fixed sample inbox for the demo">
          <Inbox emails={view.inbox} />
        </Section>
        <Section title="Materials">
          <Materials items={view.materials} />
        </Section>
        {view.outbox.length > 0 && (
          <Section title="Outbox" note="Drafts only. Nothing is sent in the pilot.">
            <Outbox messages={view.outbox} />
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
      {busy && <div className="toast">{busy}…</div>}
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
