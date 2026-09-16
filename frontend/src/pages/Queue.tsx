import { useEffect, useState } from 'react'
import { api, type Account, type QueueItem, type RetweetJob } from '../api/client'
import {
  Empty,
  ErrorBanner,
  Loading,
  MediaThumb,
  Modal,
  Pill,
  PlatformTabs,
  TopBar,
  formatDate,
  usePlatformTab,
} from '../components/ui'

export default function Queue() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [retweets, setRetweets] = useState<RetweetJob[]>([])
  const [platform, setPlatform] = usePlatformTab()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // Modal "Retweetar nas outras contas" — retweet é conceito só do X, então
  // a opção só aparece para posts publicados na plataforma X.
  const [rtTarget, setRtTarget] = useState<QueueItem | null>(null)
  const [rtAccounts, setRtAccounts] = useState<Account[]>([])
  const [rtSel, setRtSel] = useState<number[]>([])
  const [rtDelayMin, setRtDelayMin] = useState(5)
  const [rtDelayMax, setRtDelayMax] = useState(120)
  const [rtBusy, setRtBusy] = useState(false)

  async function load() {
    setLoading(true)
    try {
      setItems(await api.queue())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function loadRetweets() {
    try {
      setRetweets(await api.retweets())
    } catch (err) {
      setError((err as Error).message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  useEffect(() => {
    if (platform === 'x') loadRetweets()
  }, [platform])

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn()
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function openRetweet(item: QueueItem) {
    // Abre o modal já com as contas da plataforma carregadas, sem a conta
    // autora (retweetar a si mesma é filtrado também no backend).
    setRtTarget(item)
    setRtSel([])
    setRtDelayMin(5)
    setRtDelayMax(120)
    try {
      const accounts = await api.xAccounts('x')
      setRtAccounts(accounts.filter((a) => a.is_active && a.id !== item.x_account_id))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  function toggleAccount(id: number) {
    setRtSel((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  async function confirmRetweet() {
    if (!rtTarget || !rtSel.length) return
    setRtBusy(true)
    setError('')
    try {
      const res = await api.createRetweets({
        source_tweet_id: rtTarget.published_post_id,
        origin_x_account_id: rtTarget.x_account_id,
        target_account_ids: rtSel,
        delay_min_minutes: rtDelayMin,
        delay_max_minutes: rtDelayMax,
      })
      setNotice(
        `${res.created} retweet(s) agendado(s)${res.created < rtSel.length ? ` (${rtSel.length - res.created} conta(s) pulada(s))` : ''}. Veja abaixo.`,
      )
      setRtTarget(null)
      loadRetweets()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setRtBusy(false)
    }
  }

  async function cancelRetweetJob(id: number) {
    try {
      await api.cancelRetweet(id)
      loadRetweets()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const visible = items.filter((item) => item.platform === platform)

  return (
    <>
      <TopBar title="Fila" />

      <PlatformTabs value={platform} onChange={setPlatform} />

      {error && <ErrorBanner message={error} />}
      {notice && <div className="banner info">{notice}</div>}

      {loading ? (
        <Loading />
      ) : visible.length === 0 ? (
        <Empty title="Fila vazia" hint="Aprove um conteúdo e agende para vê-lo aqui." />
      ) : (
        visible.map((item) => (
          <div className="card" key={item.id}>
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="bold">{formatDate(item.scheduled_at)}</span>
              <span className="muted">@{item.account_username}</span>
              <span style={{ marginLeft: 'auto' }}>
                <Pill status={item.status}>{item.status}</Pill>
              </span>
            </div>

            <p className="post-text">{item.text}</p>
            {item.media
              .filter((m) => m.kind === 'video')
              .map((m) => (
                <div className="queue-video-wrap" key={m.id}>
                  <MediaThumb item={m} controls fill />
                </div>
              ))}
            {item.media.filter((m) => m.kind !== 'video').length > 0 && (
              <div className="row wrap" style={{ gap: 6, margin: '8px 0' }}>
                {item.media
                  .filter((m) => m.kind !== 'video')
                  .map((m) => (
                    <MediaThumb key={m.id} item={m} size={180} />
                  ))}
              </div>
            )}

            {item.last_error && (
              <div className="banner error small">
                {item.last_error} (tentativas: {item.attempts})
              </div>
            )}

            <div className="row wrap" style={{ gap: 8 }}>
              {item.status === 'queued' && (
                <>
                  <button className="btn sm" onClick={() => act(() => api.publishNow(item.id))}>
                    Publicar agora
                  </button>
                  <button
                    className="btn danger sm"
                    onClick={() => act(() => api.cancelScheduled(item.id))}
                  >
                    Cancelar
                  </button>
                </>
              )}

              {item.status === 'published' && item.post_url && (
                <>
                  <a className="btn ghost sm" href={item.post_url} target="_blank" rel="noreferrer">
                    Ver no {item.platform === 'threads' ? 'Threads' : 'X'}
                  </a>
                  {item.platform === 'x' && (
                    <button className="btn sm" onClick={() => openRetweet(item)}>
                      Retweetar nas outras contas
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        ))
      )}

      {platform === 'x' && (
        <>
          <div className="row" style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
            <span className="small muted">{retweets.length} retweet(s) agendado(s)</span>
          </div>

          {retweets.length === 0 ? (
            <Empty
              title="Nenhum retweet agendado"
              hint="Publique um post no X e use “Retweetar nas outras contas” para espalhar entre suas contas."
            />
          ) : (
            retweets.map((job) => (
              <div className="card" key={job.id}>
                <div className="row" style={{ marginBottom: 8 }}>
                  <span className="bold">Retweet por @{job.target_username ?? '—'}</span>
                  <span className="muted small">{formatDate(job.scheduled_at)}</span>
                  <span style={{ marginLeft: 'auto' }}>
                    <Pill status={job.status}>{job.status}</Pill>
                  </span>
                </div>
                <div className="small muted" style={{ marginBottom: 8 }}>
                  Post original: {job.source_tweet_id}
                </div>
                {job.last_error && (
                  <div className="banner error small" style={{ marginBottom: 8 }}>
                    {job.last_error}
                  </div>
                )}
                {job.status === 'queued' && (
                  <button className="btn danger sm" onClick={() => cancelRetweetJob(job.id)}>
                    Cancelar retweet
                  </button>
                )}
              </div>
            ))
          )}
        </>
      )}

      {rtTarget && (
        <Modal title="Retweetar nas outras contas" onClose={() => setRtTarget(null)}>
          <div className="small muted" style={{ marginBottom: 12 }}>
            Post de @{rtTarget.account_username} — será retweetado pelas contas escolhidas,
            com um intervalo sorteado entre cada uma (para não parecer mecânico).
          </div>

          {rtAccounts.length === 0 ? (
            <div className="banner">Nenhuma outra conta do X ativa para retweetar.</div>
          ) : (
            rtAccounts.map((a) => (
              <label className="checkline" key={a.id}>
                <input
                  type="checkbox"
                  checked={rtSel.includes(a.id)}
                  onChange={() => toggleAccount(a.id)}
                />
                <span>
                  @{a.username}
                  {a.display_name ? ` — ${a.display_name}` : ''}
                </span>
              </label>
            ))
          )}

          <label className="label" style={{ marginTop: 16 }}>Intervalo entre retweets (minutos)</label>
          <div className="row" style={{ gap: 12, marginBottom: 16 }}>
            <div style={{ flex: 1 }}>
              <input
                className="input"
                type="number"
                min={5}
                max={120}
                value={rtDelayMin}
                onChange={(e) => setRtDelayMin(Number(e.target.value))}
              />
              <div className="small muted" style={{ marginTop: 4 }}>mínimo</div>
            </div>
            <div style={{ flex: 1 }}>
              <input
                className="input"
                type="number"
                min={5}
                max={120}
                value={rtDelayMax}
                onChange={(e) => setRtDelayMax(Number(e.target.value))}
              />
              <div className="small muted" style={{ marginTop: 4 }}>máximo</div>
            </div>
          </div>

          <button
            className="btn block"
            disabled={rtBusy || rtSel.length === 0}
            onClick={confirmRetweet}
          >
            {rtBusy ? 'Agendando...' : `Agendar ${rtSel.length} retweet(s)`}
          </button>
        </Modal>
      )}
    </>
  )
}
