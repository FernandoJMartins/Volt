import { useEffect, useState } from 'react'
import { api, type Candidate } from '../api/client'
import {
  Empty,
  ErrorBanner,
  Loading,
  MediaStrip,
  Modal,
  Pill,
  TopBar,
  formatDate,
} from '../components/ui'

const TABS = [
  { key: 'pending', label: 'Pendentes' },
  { key: 'approved', label: 'Aprovados' },
  { key: 'blocked', label: 'Bloqueados' },
  { key: 'published', label: 'Publicados' },
]

export default function Inbox() {
  const [tab, setTab] = useState('pending')
  const [items, setItems] = useState<Candidate[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Candidate | null>(null)
  const [draft, setDraft] = useState('')
  const [scheduling, setScheduling] = useState<Candidate | null>(null)
  const [when, setWhen] = useState('')
  const [notice, setNotice] = useState('')
  const [autoBusy, setAutoBusy] = useState(false)
  const [autoOpen, setAutoOpen] = useState(false)
  const [startIn, setStartIn] = useState(5)
  const [gapMin, setGapMin] = useState(30)
  const [gapMax, setGapMax] = useState(120)
  const [horizon, setHorizon] = useState(30)
  const [respectWindow, setRespectWindow] = useState(true)

  async function autoScheduleAll() {
    // Agenda por conta, respeitando a janela e o limite diario de cada uma.
    const accountIds = [...new Set(items.map((i) => i.target_x_account_id).filter(Boolean))]
    if (!accountIds.length) return

    setAutoBusy(true)
    setError('')
    try {
      let total = 0
      for (const id of accountIds) {
        const res = await api.autoSchedule({
          x_account_id: id as number,
          start_in_minutes: startIn,
          min_interval_minutes: gapMin,
          max_interval_minutes: gapMax,
          horizon_days: horizon,
          respect_window: respectWindow,
        })
        total += res.scheduled
      }
      setNotice(`${total} post(s) agendados. Veja em Fila.`)
      setAutoOpen(false)
      load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setAutoBusy(false)
    }
  }

  async function load(status = tab) {
    setLoading(true)
    setError('')
    try {
      setItems(await api.candidates(status))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(tab)
  }, [tab])

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn()
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function saveEdit() {
    if (!editing) return
    await act(async () => {
      await api.editCandidate(editing.id, draft)
      setEditing(null)
    })
  }

  async function confirmSchedule() {
    if (!scheduling) return
    await act(async () => {
      await api.schedule({
        content_candidate_id: scheduling.id,
        scheduled_at: when ? new Date(when).toISOString() : null,
      })
      setScheduling(null)
      setWhen('')
    })
  }

  return (
    <>
      <TopBar title="Conteúdo" />

      <div className="tabs">
        {TABS.map((t) => (
          <div
            key={t.key}
            className={`tab${tab === t.key ? ' active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </div>
        ))}
      </div>

      {error && <ErrorBanner message={error} />}
      {notice && <div className="banner info">{notice}</div>}

      {tab === 'approved' && items.length > 0 && (
        <div className="row" style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
          <span className="small muted">{items.length} aprovado(s) aguardando agendamento</span>
          <button
            className="btn sm"
            style={{ marginLeft: 'auto' }}
            disabled={autoBusy}
            onClick={() => setAutoOpen(true)}
          >
            {autoBusy ? 'Agendando...' : 'Agendar tudo automaticamente'}
          </button>
        </div>
      )}

      {loading ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty title="Nada por aqui" hint="Crie conteúdo a partir de um post no Início." />
      ) : (
        items.map((c) => (
          <div className="card" key={c.id}>
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="bold">@{c.account_username ?? '—'}</span>
              <Pill status={c.status}>{c.status}</Pill>
              {c.origin === 'ai' && <Pill>IA</Pill>}
              <span className="muted small" style={{ marginLeft: 'auto' }}>
                {formatDate(c.created_at)}
              </span>
            </div>

            <p className="post-text">{c.text}</p>
            <MediaStrip media={c.media} />

            {c.block_reason && <div className="banner error">{c.block_reason}</div>}

            <div className="row wrap" style={{ gap: 8 }}>
              <button
                className="btn ghost sm"
                onClick={() => {
                  setEditing(c)
                  setDraft(c.text)
                }}
              >
                Editar
              </button>
              {(c.status === 'pending' || c.status === 'blocked') && (
                <button className="btn sm" onClick={() => act(() => api.approve(c.id))}>
                  Aprovar
                </button>
              )}
              {c.status === 'approved' && (
                <button className="btn sm" onClick={() => setScheduling(c)}>
                  Agendar
                </button>
              )}
              {c.status !== 'published' && (
                <button className="btn danger sm" onClick={() => act(() => api.reject(c.id))}>
                  Descartar
                </button>
              )}
            </div>
          </div>
        ))
      )}

      {editing && (
        <Modal title="Editar conteúdo" onClose={() => setEditing(null)}>
          <textarea
            className="textarea"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={280}
          />
          <div className="row" style={{ marginTop: 12 }}>
            <span className="counter">{draft.length}/280</span>
            <button className="btn" style={{ marginLeft: 'auto' }} onClick={saveEdit}>
              Salvar
            </button>
          </div>
        </Modal>
      )}

      {scheduling && (
        <Modal title="Agendar publicação" onClose={() => setScheduling(null)}>
          <div className="field">
            <label className="label">Data e hora (vazio = publicar agora)</label>
            <input
              className="input"
              type="datetime-local"
              value={when}
              onChange={(e) => setWhen(e.target.value)}
            />
          </div>
          <button className="btn block" onClick={confirmSchedule}>
            {when ? 'Colocar na fila' : 'Publicar agora'}
          </button>
        </Modal>
      )}

      {autoOpen && (
        <Modal title="Agendar automaticamente" onClose={() => setAutoOpen(false)}>
          <div className="field">
            <label className="label">Começar daqui a (minutos)</label>
            <input
              className="input"
              type="number"
              min={1}
              max={1440}
              value={startIn}
              onChange={(e) => setStartIn(Number(e.target.value))}
            />
            <div className="small muted" style={{ marginTop: 6 }}>
              De 1 minuto até 24 horas.
            </div>
          </div>

          <label className="label">Intervalo entre posts (minutos)</label>
          <div className="row" style={{ gap: 12, marginBottom: 16 }}>
            <div style={{ flex: 1 }}>
              <input
                className="input"
                type="number"
                min={1}
                max={1440}
                value={gapMin}
                onChange={(e) => setGapMin(Number(e.target.value))}
              />
              <div className="small muted" style={{ marginTop: 4 }}>mínimo</div>
            </div>
            <div style={{ flex: 1 }}>
              <input
                className="input"
                type="number"
                min={1}
                max={1440}
                value={gapMax}
                onChange={(e) => setGapMax(Number(e.target.value))}
              />
              <div className="small muted" style={{ marginTop: 4 }}>máximo</div>
            </div>
          </div>

          <div className="field">
            <label className="label">Programar até quantos dias à frente? (máx. 30)</label>
            <input
              className="input"
              type="number"
              min={1}
              max={30}
              value={horizon}
              onChange={(e) => setHorizon(Math.min(Number(e.target.value), 30))}
            />
          </div>

          <label className="checkline">
            <input
              type="checkbox"
              checked={respectWindow}
              onChange={(e) => setRespectWindow(e.target.checked)}
            />
            <span>Respeitar a janela de horário de cada conta</span>
          </label>

          <div className="banner" style={{ marginTop: 12 }}>
            Cada post cai em um horário sorteado dentro do intervalo acima — só para o feed não
            ficar mecânico. Nada aqui tenta esconder automação do X.
          </div>

          <button
            className="btn block"
            style={{ marginTop: 16 }}
            onClick={autoScheduleAll}
            disabled={autoBusy}
          >
            {autoBusy ? 'Agendando...' : 'Agendar'}
          </button>
        </Modal>
      )}

      {autoOpen && (
        <Modal title="Agendar automaticamente" onClose={() => setAutoOpen(false)}>
          <div className="field">
            <label className="label">Começar daqui a (minutos)</label>
            <input
              className="input"
              type="number"
              min={1}
              max={1440}
              value={startIn}
              onChange={(e) => setStartIn(Number(e.target.value))}
            />
            <div className="small muted" style={{ marginTop: 6 }}>
              De 1 minuto até 24 horas.
            </div>
          </div>

          <label className="label">Intervalo entre posts (minutos)</label>
          <div className="row" style={{ gap: 12, marginBottom: 16 }}>
            <div style={{ flex: 1 }}>
              <input
                className="input"
                type="number"
                min={1}
                max={1440}
                value={gapMin}
                onChange={(e) => setGapMin(Number(e.target.value))}
              />
              <div className="small muted" style={{ marginTop: 4 }}>mínimo</div>
            </div>
            <div style={{ flex: 1 }}>
              <input
                className="input"
                type="number"
                min={1}
                max={1440}
                value={gapMax}
                onChange={(e) => setGapMax(Number(e.target.value))}
              />
              <div className="small muted" style={{ marginTop: 4 }}>máximo</div>
            </div>
          </div>

          <div className="field">
            <label className="label">Programar até quantos dias à frente? (máx. 30)</label>
            <input
              className="input"
              type="number"
              min={1}
              max={30}
              value={horizon}
              onChange={(e) => setHorizon(Math.min(Number(e.target.value), 30))}
            />
          </div>

          <label className="checkline">
            <input
              type="checkbox"
              checked={respectWindow}
              onChange={(e) => setRespectWindow(e.target.checked)}
            />
            <span>Respeitar a janela de horário de cada conta</span>
          </label>

          <div className="banner" style={{ marginTop: 12 }}>
            Cada post cai em um horário sorteado dentro do intervalo acima — só para o feed não
            ficar mecânico. Nada aqui tenta esconder automação do X.
          </div>

          <button
            className="btn block"
            style={{ marginTop: 16 }}
            onClick={autoScheduleAll}
            disabled={autoBusy}
          >
            {autoBusy ? 'Agendando...' : 'Agendar'}
          </button>
        </Modal>
      )}
    </>
  )
}
