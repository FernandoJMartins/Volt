import { useEffect, useState } from 'react'
import { api, type QueueItem, type XAccount } from '../api/client'
import { IconRepost } from '../components/Icons'
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

export default function Queue() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [accounts, setAccounts] = useState<XAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [retweetOf, setRetweetOf] = useState<QueueItem | null>(null)
  const [targets, setTargets] = useState<number[]>([])
  const [delayMin, setDelayMin] = useState(5)
  const [delayMax, setDelayMax] = useState(120)
  const [done, setDone] = useState('')

  async function load() {
    setLoading(true)
    try {
      const [q, a] = await Promise.all([api.queue(), api.xAccounts()])
      setItems(q)
      setAccounts(a)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn()
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function submitRetweets() {
    if (!retweetOf || !targets.length) return
    try {
      const res = await api.createRetweets({
        source_tweet_id: retweetOf.published_post_id,
        target_account_ids: targets,
        origin_x_account_id: retweetOf.x_account_id,
        delay_min_minutes: delayMin,
        delay_max_minutes: delayMax,
      })
      setDone(`${res.created} retweets agendados.`)
      setRetweetOf(null)
      setTargets([])
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <>
      <TopBar title="Fila" />

      {error && <ErrorBanner message={error} />}
      {done && <div className="banner info">{done}</div>}

      {loading ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty title="Fila vazia" hint="Aprove um conteúdo e agende para vê-lo aqui." />
      ) : (
        items.map((item) => (
          <div className="card" key={item.id}>
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="bold">{formatDate(item.scheduled_at)}</span>
              <span className="muted">@{item.account_username}</span>
              <span style={{ marginLeft: 'auto' }}>
                <Pill status={item.status}>{item.status}</Pill>
              </span>
            </div>

            <p className="post-text">{item.text}</p>
            <MediaStrip media={item.media} size={56} />

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

              {item.status === 'published' && item.published_post_id && (
                <>
                  <a
                    className="btn ghost sm"
                    href={`https://x.com/${item.account_username}/status/${item.published_post_id}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Ver no X
                  </a>
                  <button
                    className="btn ghost sm"
                    onClick={() => {
                      setRetweetOf(item)
                      setDone('')
                    }}
                  >
                    <IconRepost size={16} /> Retweetar com outras contas
                  </button>
                </>
              )}
            </div>
          </div>
        ))
      )}

      {retweetOf && (
        <Modal title="Retweet escalonado" onClose={() => setRetweetOf(null)}>
          <div className="banner">
            Os retweets serão feitos aos poucos, com intervalo sorteado dentro da faixa escolhida.
            Amplificação coordenada entre várias contas pode ser vista como manipulação pelo X —
            use com critério.
          </div>

          <label className="label" style={{ marginTop: 12 }}>
            Contas que vão retweetar
          </label>
          {accounts
            .filter((a) => a.id !== retweetOf.x_account_id && a.connected)
            .map((a) => (
              <label className="checkline" key={a.id}>
                <input
                  type="checkbox"
                  checked={targets.includes(a.id)}
                  onChange={(e) =>
                    setTargets((prev) =>
                      e.target.checked ? [...prev, a.id] : prev.filter((id) => id !== a.id),
                    )
                  }
                />
                <span>@{a.username}</span>
              </label>
            ))}

          <div className="row" style={{ marginTop: 16, gap: 12 }}>
            <div style={{ flex: 1 }}>
              <label className="label">Intervalo mín. (min)</label>
              <input
                className="input"
                type="number"
                min={5}
                max={120}
                value={delayMin}
                onChange={(e) => setDelayMin(Number(e.target.value))}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label className="label">Intervalo máx. (min)</label>
              <input
                className="input"
                type="number"
                min={5}
                max={120}
                value={delayMax}
                onChange={(e) => setDelayMax(Number(e.target.value))}
              />
            </div>
          </div>

          <button
            className="btn block"
            style={{ marginTop: 16 }}
            onClick={submitRetweets}
            disabled={!targets.length}
          >
            Agendar {targets.length} retweets
          </button>
        </Modal>
      )}
    </>
  )
}
