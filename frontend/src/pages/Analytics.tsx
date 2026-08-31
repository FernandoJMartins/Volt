import { useEffect, useMemo, useState } from 'react'
import { api, type AccountAnalytics, type HourlyBucket, type SourceAnalytics } from '../api/client'
import { Empty, ErrorBanner, Loading, TopBar, formatDate } from '../components/ui'

function hourLabel(h: number) {
  return `${String(h).padStart(2, '0')}:00`
}

function HourChart({ hourly, bestHours }: { hourly: HourlyBucket[]; bestHours: number[] }) {
  const maxScore = Math.max(0.01, ...hourly.map((b) => b.score))
  return (
    <>
      <div className="chart" style={{ marginTop: 12 }}>
        {hourly.map((b) => {
          const isBest = bestHours.includes(b.hour)
          const height = Math.max(3, Math.round((b.score / maxScore) * 100))
          return (
            <div
              key={b.hour}
              className={`chart-bar${isBest ? ' best' : ''}`}
              style={{ height: `${height}%` }}
              title={`${hourLabel(b.hour)} — ${b.posts} post(s), score ${b.score}`}
            />
          )
        })}
      </div>
      <div className="chart-axis">
        <span>0h</span>
        <span>6h</span>
        <span>12h</span>
        <span>18h</span>
        <span>23h</span>
      </div>
    </>
  )
}

export default function Analytics() {
  const [tab, setTab] = useState<'mine' | 'sources'>('mine')
  const [items, setItems] = useState<AccountAnalytics[]>([])
  const [sources, setSources] = useState<SourceAnalytics[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [selectedSource, setSelectedSource] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function loadMine() {
    setLoading(true)
    setError('')
    try {
      const data = await api.analyticsOverview()
      setItems(data)
      if (!selected && data.length) setSelected(data[0].account_id)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function loadSources() {
    setLoading(true)
    setError('')
    try {
      const data = await api.analyticsSources()
      setSources(data)
      if (!selectedSource && data.length) setSelectedSource(data[0].id)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadMine()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function switchTab(t: 'mine' | 'sources') {
    setTab(t)
    if (t === 'sources') loadSources()
  }

  const account = useMemo(
    () => items.find((a) => a.account_id === selected) ?? null,
    [items, selected],
  )
  const source = useMemo(
    () => sources.find((s) => s.id === selectedSource) ?? null,
    [sources, selectedSource],
  )

  async function refreshNow() {
    if (!account) return
    try {
      await api.refreshAnalytics(account.account_id)
      setNotice('Coleta disparada. As métricas chegam em ~1 minuto — atualize a página.')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  const bestSlots = useMemo(() => {
    if (!account || !account.best_hours.length) return []
    return account.best_hours.map((h) => hourLabel(h))
  }, [account])

  return (
    <>
      <TopBar title="Analytics" />

      <div className="row" style={{ gap: 8, marginBottom: 14 }}>
        <button
          className={`btn sm${tab === 'mine' ? '' : ' ghost'}`}
          onClick={() => switchTab('mine')}
        >
          Minhas contas
        </button>
        <button
          className={`btn sm${tab === 'sources' ? '' : ' ghost'}`}
          onClick={() => switchTab('sources')}
        >
          Contas clonadas
        </button>
      </div>

      {error && <ErrorBanner message={error} />}
      {notice && <div className="banner info">{notice}</div>}

      {loading ? (
        <Loading />
      ) : tab === 'mine' ? (
        !account ? (
          <Empty
            title="Nenhuma conta com métricas ainda"
            hint="Conecte uma conta em Contas e publique (ou aguarde a coleta automática, a cada hora)."
          />
        ) : (
          <>
            <div className="row" style={{ marginBottom: 12 }}>
              <select
                className="select"
                style={{ maxWidth: 260 }}
                value={selected ?? ''}
                onChange={(e) => setSelected(Number(e.target.value))}
              >
                {items.map((a) => (
                  <option key={a.account_id} value={a.account_id}>
                    @{a.username}
                  </option>
                ))}
              </select>
            </div>

            <div className="stats">
              <div className="stat">
                <div className="value">{account.published}</div>
                <div className="name">Publicados</div>
              </div>
              <div className="stat">
                <div className="value">{account.with_stats}</div>
                <div className="name">Com métricas</div>
              </div>
              <div className="stat">
                <div className="value">{account.engagement_per_post}</div>
                <div className="name">Engajamento/post</div>
              </div>
              <div className="stat">
                <div className="value">
                  {bestSlots[0] ?? '—'}
                  {account.best_hours.length > 1 ? '…' : ''}
                </div>
                <div className="name">Melhor horário</div>
              </div>
            </div>

            <div className="card">
              <div className="row">
                <div className="bold">Engajamento por hora do dia (fuso da conta)</div>
                <div style={{ marginLeft: 'auto' }}>
                  <button className="btn sm ghost" onClick={refreshNow}>
                    Coletar agora
                  </button>
                </div>
              </div>
              {account.with_stats === 0 && (
                <div className="small muted" style={{ marginTop: 4 }}>
                  Sem dados ainda — enquanto não há histórico, o agendamento otimizado usa
                  espalhamento uniforme na janela da conta.
                </div>
              )}
              <HourChart hourly={account.hourly} bestHours={account.best_hours} />
              <div className="small muted" style={{ marginTop: 8 }}>
                Barras destacadas = melhores horários dentro da janela da conta. O score amortece
                horas com poucas amostras: um único post viral não domina o calendário.
              </div>
            </div>

            <div className="card">
              <div className="bold">Posts recentes</div>
              {account.recent.length === 0 ? (
                <div className="small muted" style={{ marginTop: 8 }}>
                  Nada por aqui — publique e a coleta automática trará as métricas.
                </div>
              ) : (
                account.recent.map((p) => (
                  <div key={p.id} className="row" style={{ marginTop: 10 }}>
                    <div style={{ minWidth: 0 }}>
                      <div
                        className="small"
                        style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      >
                        {p.text || '(sem texto)'}
                      </div>
                      <div className="small muted">
                        {formatDate(p.published_at)} ·{' '}
                        <a href={p.url} target="_blank" rel="noreferrer">
                          ver no X
                        </a>
                      </div>
                    </div>
                    <div className="small muted" style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>
                      ♥ {p.likes} · ⟳ {p.reposts} · ✉ {p.replies}
                    </div>
                  </div>
                ))
              )}
            </div>

            <div className="card">
              <div className="bold">Sobre estes números</div>
              <div className="small muted" style={{ marginTop: 6 }}>
                Coletados via navegador no perfil da própria conta (sem custo de API), de hora em
                hora e ~45min após cada publicação. Views ficam zeradas: o X não as expõe no
                timeline. A contagem é sempre a mais recente coletada.
                {account.last_collected_at && (
                  <> Última coleta: {formatDate(account.last_collected_at)}.</>
                )}
              </div>
            </div>
          </>
        )
      ) : !source ? (
        <Empty
          title="Nenhuma conta clonada"
          hint="Adicione perfis em Início → Contas para clonar e colete posts."
        />
      ) : (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <select
              className="select"
              style={{ maxWidth: 260 }}
              value={selectedSource ?? ''}
              onChange={(e) => setSelectedSource(Number(e.target.value))}
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>
                  @{s.username}
                </option>
              ))}
            </select>
          </div>

          <div className="stats">
            <div className="stat">
              <div className="value">{source.collected}</div>
              <div className="name">Posts coletados</div>
            </div>
            <div className="stat">
              <div className="value">{source.avg_likes}</div>
              <div className="name">Média likes</div>
            </div>
            <div className="stat">
              <div className="value">{source.avg_reposts}</div>
              <div className="name">Média reposts</div>
            </div>
            <div className="stat">
              <div className="value">
                {source.best_hours.length ? source.best_hours.map(hourLabel).join(' · ') : '—'}
              </div>
              <div className="name">Horários fortes (UTC)</div>
            </div>
          </div>

          <div className="card">
            <div className="bold">Engajamento dos posts por hora (UTC)</div>
            <div className="small muted" style={{ marginTop: 4 }}>
              Mostra quando o perfil @{source.username} costuma engajar — útil para entender o
              ritmo dele.
            </div>
            <HourChart hourly={source.hourly} bestHours={source.best_hours} />
          </div>

          <div className="card">
            <div className="bold">Sobre estes números</div>
            <div className="small muted" style={{ marginTop: 6 }}>
              Engajamento dos posts coletados deste perfil nos últimos 90 dias (curtidas,
              reposts e respostas). Views ficam zeradas: o X não as expõe no timeline.
              {source.last_collected_at && (
                <> Última coleta: {formatDate(source.last_collected_at)}.</>
              )}
            </div>
          </div>
        </>
      )}
    </>
  )
}
