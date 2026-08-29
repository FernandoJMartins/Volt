import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type SourcePost, type Stats } from '../api/client'
import { Avatar, Empty, Loading, Metrics, Pill, TopBar, formatDate } from '../components/ui'

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
                <Metrics post={post} />
              </div>
            </div>
          </article>
        ))
      )}
    </>
  )
}
