import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type SourcePost, type Stats } from '../api/client'
import { IconSparkle } from '../components/Icons'
import { Avatar, Empty, Loading, MediaThumb, Metrics, Pill, TopBar, formatDate } from '../components/ui'

const CARDS: [string, string][] = [
  ['connected_accounts', 'Contas conectadas'],
  ['posts_today', 'Posts hoje'],
  ['pending_review', 'Aguardando revisão'],
  ['approved', 'Aprovados'],
  ['queued', 'Na fila'],
  ['published', 'Publicados'],
  ['blocked', 'Bloqueados'],
  ['failed', 'Falhas'],
]

export default function Dashboard() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [posts, setPosts] = useState<SourcePost[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([api.stats(), api.sourcePosts('score')])
      .then(([s, p]) => {
        setStats(s)
        setPosts(p)
      })
      .finally(() => setLoading(false))
  }, [])

  return (
    <>
      <TopBar title="Início" />

      <div className="stats">
        {CARDS.map(([key, label]) => (
          <div className="stat" key={key}>
            <div className="value">{stats?.[key] ?? '—'}</div>
            <div className="name">{label}</div>
          </div>
        ))}
      </div>

      <div className="card" style={{ background: 'var(--bg-elev)' }}>
        <div className="bold">Conteúdos com maior potencial</div>
        <div className="small muted" style={{ marginTop: 4 }}>
          Ranking relativo à média de cada fonte — contas grandes não dominam só por volume.
        </div>
      </div>

      {loading ? (
        <Loading />
      ) : posts.length === 0 ? (
        <Empty
          title="Nenhum post coletado ainda"
          hint="Adicione textos ao seu pool em Monitoramento e rode uma coleta."
        />
      ) : (
        posts.map((post) => (
          <article
            key={post.id}
            className="card hoverable"
            onClick={() => navigate(`/compose/${post.id}`)}
          >
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <Avatar name={post.author_username} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="row" style={{ gap: 6 }}>
                  <span className="bold">@{post.author_username}</span>
                  <span className="muted small">· {formatDate(post.posted_at)}</span>
                  <span style={{ marginLeft: 'auto' }}>
                    <Pill status="score">{post.score.toFixed(1)}</Pill>
                  </span>
                </div>
                <p className="post-text">{post.text}</p>
                {post.media.length > 0 && (
                  <div className="row wrap" style={{ gap: 6, marginTop: 8 }}>
                    {post.media.slice(0, 3).map((m) => (
                      <MediaThumb key={m.id} item={m} size={56} />
                    ))}
                    {post.media.length > 3 && (
                      <span className="small muted">+{post.media.length - 3}</span>
                    )}
                  </div>
                )}
                <Metrics post={post} />
                <div style={{ marginTop: 8 }}>
                  <button
                    className="btn ghost sm"
                    onClick={(e) => {
                      e.stopPropagation()
                      navigate(`/compose/${post.id}?generate=ai`)
                    }}
                  >
                    <IconSparkle size={16} />
                    Gerar versão com IA{post.has_media ? ' + mídia' : ''}
                  </button>
                </div>
              </div>
            </div>
          </article>
        ))
      )}
    </>
  )
}
