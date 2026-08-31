import { useEffect, useState } from 'react'
import { api, type QueueItem } from '../api/client'
import { Empty, ErrorBanner, Loading, MediaStrip, Pill, TopBar, formatDate } from '../components/ui'

export default function Queue() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

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

  return (
    <>
      <TopBar title="Fila" />

      {error && <ErrorBanner message={error} />}

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
                <a
                  className="btn ghost sm"
                  href={`https://x.com/${item.account_username}/status/${item.published_post_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Ver no X
                </a>
              )}
            </div>
          </div>
        ))
      )}
    </>
  )
}
