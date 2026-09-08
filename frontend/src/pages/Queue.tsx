import { useEffect, useState } from 'react'
import { api, type QueueItem } from '../api/client'
import {
  Empty,
  ErrorBanner,
  Loading,
  MediaThumb,
  Pill,
  PlatformTabs,
  TopBar,
  formatDate,
  usePlatformTab,
} from '../components/ui'

export default function Queue() {
  const [items, setItems] = useState<QueueItem[]>([])
  const [platform, setPlatform] = usePlatformTab()
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

  const visible = items.filter((item) => item.platform === platform)

  return (
    <>
      <TopBar title="Fila" />

      <PlatformTabs value={platform} onChange={setPlatform} />

      {error && <ErrorBanner message={error} />}

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
                <a className="btn ghost sm" href={item.post_url} target="_blank" rel="noreferrer">
                  Ver no {item.platform === 'threads' ? 'Threads' : 'X'}
                </a>
              )}
            </div>
          </div>
        ))
      )}
    </>
  )
}
