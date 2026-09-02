import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type Account, type MonitoredAccount, type SourcePost } from '../api/client'
import { IconPlus, IconRefresh, IconSparkle, IconTrash } from '../components/Icons'
import {
  Avatar,
  Empty,
  ErrorBanner,
  Loading,
  MediaStrip,
  Metrics,
  Pill,
  PlatformTabs,
  TopBar,
  formatDate,
  usePlatformTab,
} from '../components/ui'

export default function Dashboard() {
  const navigate = useNavigate()
  const [posts, setPosts] = useState<SourcePost[]>([])
  const [sources, setSources] = useState<MonitoredAccount[]>([])
  const [platform, setPlatform] = usePlatformTab()
  const [filterSource, setFilterSource] = useState<number | null>(null)
  const [newUser, setNewUser] = useState('')
  const [newQty, setNewQty] = useState(15)
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)

  const [ai, setAi] = useState<{ available: boolean; model: string | null } | null>(null)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [genCount, setGenCount] = useState(10)
  const [genAccounts, setGenAccounts] = useState<number[]>([]) // vazio = todas as ativas
  const [genBusy, setGenBusy] = useState(false)

  async function loadPosts() {
    setPosts(await api.sourcePosts('score'))
  }

  async function loadAll() {
    setLoading(true)
    try {
      const [p, m, a] = await Promise.all([
        api.sourcePosts('score'),
        api.monitored(),
        api.xAccounts(),
      ])
      setPosts(p)
      setSources(m)
      setAccounts(a)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
    api.aiStatus().then(setAi).catch(() => setAi({ available: false, model: null }))
  }

  useEffect(() => {
    loadAll()
  }, [])

  async function addSource() {
    if (!newUser.trim()) return
    try {
      await api.addMonitored({
        username: newUser.trim(),
        source_type: 'web',
        posts_per_collect: newQty,
        platform,
      })
      setNewUser('')
      await loadAll()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function setQty(id: number, qty: number) {
    const clamped = Math.max(1, Math.min(qty, 100))
    setSources((prev) => prev.map((s) => (s.id === id ? { ...s, posts_per_collect: clamped } : s)))
    try {
      await api.updateMonitored(id, { posts_per_collect: clamped })
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function collect(s: MonitoredAccount) {
    setBusy(s.id)
    setError('')
    setNotice('')
    try {
      await api.collectNow(s.id, s.posts_per_collect)
      setNotice(`Coletando @${s.username} (até ${s.posts_per_collect} posts) — atualizando…`)
      await new Promise((r) => setTimeout(r, 9000))
      const [p, m] = await Promise.all([api.sourcePosts('score'), api.monitored()])
      setPosts(p)
      setSources(m)
      setNotice('')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function generateBulk() {
    setGenBusy(true)
    setError('')
    setNotice('')
    try {
      // vazio = todas as contas ativas DESSA plataforma (nunca mistura X com Threads).
      const targetIds = genAccounts.length ? genAccounts : platformAccounts.map((a) => a.id)
      const res = await api.bulkGenerate({
        count: genCount,
        account_ids: targetIds,
        attach_media: true,
      })
      const parts = Object.entries(res.per_account)
        .map(([u, n]) => `@${u}: ${n}`)
        .join(' · ')
      setNotice(
        `${res.created} rascunhos gerados com IA${parts ? ` (${parts})` : ''}. ` +
          'Revise e aprove em Conteúdo, depois agende (manual ou otimizado).',
      )
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setGenBusy(false)
    }
  }

  async function removeSource(id: number) {
    await api.deleteMonitored(id)
    if (filterSource === id) setFilterSource(null)
    await loadAll()
  }

  const platformSources = sources.filter((s) => s.platform === platform)
  const platformPosts = posts.filter((p) => p.platform === platform)
  const visible =
    filterSource == null
      ? platformPosts
      : platformPosts.filter((p) => p.monitored_account_id === filterSource)
  const platformAccounts = accounts.filter((a) => a.connected && a.platform === platform)

  return (
    <>
      <TopBar title="Início" />

      <PlatformTabs value={platform} onChange={setPlatform} />

      {error && <ErrorBanner message={error} />}
      {notice && <div className="banner info">{notice}</div>}

      {/* ---------- 1 · Contas para clonar ---------- */}
      <div className="card">
        <div className="section-title">1 · Contas para clonar</div>
        <div className="small muted">
          Perfis de inspiração. A coleta puxa texto + mídia (referência) sem repetir o que já
          entrou — pode coletar de novo à vontade.
        </div>

        <div className="row" style={{ gap: 8, marginTop: 12 }}>
          <input
            className="input"
            style={{ flex: 1, minWidth: 120 }}
            placeholder="@perfil"
            value={newUser}
            onChange={(e) => setNewUser(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && addSource()}
          />
          <input
            className="input"
            style={{ width: 88 }}
            type="number"
            min={1}
            max={100}
            title="Quantos posts puxar por coleta (1–100)"
            value={newQty}
            onChange={(e) => setNewQty(Math.max(1, Math.min(Number(e.target.value), 100)))}
          />
          <button className="btn sm" onClick={addSource} disabled={!newUser.trim()}>
            <IconPlus size={16} /> Adicionar
          </button>
        </div>

        {platformSources.length === 0 ? (
          <div className="small muted" style={{ marginTop: 12 }}>
            Nenhuma conta do {platform === 'threads' ? 'Threads' : 'X'} ainda — adicione um
            @perfil acima.
          </div>
        ) : (
          <div style={{ marginTop: 12 }}>
            {platformSources.map((s) => (
              <div key={s.id} className="source-row">
                <div className="source-row-info">
                  <span className="bold">@{s.username}</span>
                  <span className="small muted">
                    {s.posts_found} posts coletados · última: {formatDate(s.last_collected_at)}
                  </span>
                </div>
                <div className="row" style={{ gap: 6, alignItems: 'center' }}>
                  <span className="small muted">posts:</span>
                  <input
                    className="input"
                    style={{ width: 62 }}
                    type="number"
                    min={1}
                    max={100}
                    value={s.posts_per_collect}
                    onChange={(e) => setQty(s.id, Number(e.target.value))}
                    title="Quantos posts puxar por coleta (1–100)"
                  />
                  <button
                    className="btn sm"
                    title="Coletar agora"
                    disabled={busy === s.id}
                    onClick={() => collect(s)}
                  >
                    <IconRefresh size={15} />
                    {busy === s.id ? ' Coletando…' : ' Coletar'}
                  </button>
                  <button
                    className="btn ghost sm"
                    title="Remover"
                    onClick={() => removeSource(s.id)}
                  >
                    <IconTrash size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ---------- 2 · Refazer um post ---------- */}
      <div className="card">
        <div className="section-title">2 · Escolha um post para refazer</div>
        <div className="small muted">Clique num post para criar a sua versão (texto próprio).</div>

        {platformSources.length > 0 && (
          <div className="row wrap" style={{ gap: 8, marginTop: 12 }}>
            <button
              className={`btn ghost sm${filterSource === null ? ' active' : ''}`}
              onClick={() => setFilterSource(null)}
            >
              Todas
            </button>
            {platformSources.map((s) => (
              <button
                key={s.id}
                className={`btn ghost sm${filterSource === s.id ? ' active' : ''}`}
                onClick={() => setFilterSource(s.id)}
              >
                @{s.username}
              </button>
            ))}
          </div>
        )}

        {loading ? (
          <div style={{ marginTop: 12 }}>
            <Loading />
          </div>
        ) : visible.length === 0 ? (
          <div style={{ marginTop: 12 }}>
            <Empty
              title="Nenhum post ainda"
              hint={
                platformSources.length === 0
                  ? 'Adicione uma conta na seção 1 e clique em Coletar.'
                  : 'Clique em Coletar na seção 1 — os posts aparecem aqui com a mídia do perfil.'
              }
            />
          </div>
        ) : (
          <div style={{ marginTop: 12 }}>
            {visible.map((post) => (
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
                    <MediaStrip media={post.media} size={92} />
                    <Metrics post={post} />
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {/* ---------- 3 · Gerar rascunhos com IA ---------- */}
      <div className="card">
        <div className="section-title">3 · Gerar rascunhos com IA</div>
        {!ai?.available ? (
          <div className="small muted" style={{ marginTop: 4 }}>
            IA desativada. Para gerar textos automaticamente, ative{' '}
            <code>AI_ENABLED=true</code> no .env com o Ollama local (grátis) — veja o README —
            ou configure <code>ANTHROPIC_API_KEY</code>.
          </div>
        ) : (
          <>
            <div className="small muted">
              A IA reescreve os posts coletados (texto novo, sem cópia), divide{' '}
              <b>igualmente entre as contas</b> e anexa mídia da sua biblioteca. Tudo sai como
              rascunho para você aprovar. Modelo: <code>{ai.model}</code>.
            </div>

            <div className="row" style={{ gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              <span className="small muted">Quantos posts:</span>
              <input
                className="input"
                style={{ width: 76 }}
                type="number"
                min={1}
                max={100}
                value={genCount}
                onChange={(e) =>
                  setGenCount(Math.max(1, Math.min(Number(e.target.value), 100)))
                }
              />
              {platformAccounts.length > 0 && (
                <span className="small muted" style={{ marginLeft: 8 }}>
                  Contas (vazio = todas):
                </span>
              )}
              {platformAccounts.map((a) => {
                const on = genAccounts.includes(a.id)
                return (
                  <button
                    key={a.id}
                    className={`btn ghost sm${on ? ' active' : ''}`}
                    onClick={() =>
                      setGenAccounts((prev) =>
                        on ? prev.filter((id) => id !== a.id) : [...prev, a.id],
                      )
                    }
                  >
                    @{a.username}
                  </button>
                )
              })}
              <button
                className="btn sm"
                onClick={generateBulk}
                disabled={genBusy || platformPosts.length === 0 || platformAccounts.length === 0}
                title={
                  platformPosts.length === 0
                    ? 'Colete posts primeiro (seção 1)'
                    : platformAccounts.length === 0
                      ? 'Conecte uma conta em Contas'
                      : undefined
                }
              >
                <IconSparkle size={16} />
                {genBusy ? ' Gerando…' : ' Gerar rascunhos'}
              </button>
            </div>
            {platformPosts.length === 0 && (
              <div className="small muted" style={{ marginTop: 8 }}>
                Colete posts na seção 1 para a IA ter de onde reescrever.
              </div>
            )}
          </>
        )}
      </div>

      {/* ---------- Como funciona ---------- */}
      <div className="card" style={{ background: 'var(--bg-elev)' }}>
        <div className="section-title">Como funciona</div>
        <ol className="small muted" style={{ margin: '8px 0 0', paddingLeft: 18, lineHeight: 1.9 }}>
          <li>
            <b>Clonar:</b> adicione perfis e colete (seção 1).
          </li>
          <li>
            <b>Gerar:</b> opcional — a IA cria os rascunhos com mídia e divide igualmente
            entre as contas (seção 3).
          </li>
          <li>
            <b>Refazer manualmente:</b> ou clique num post da seção 2, escolha a conta destino
            e escreva o seu texto (IA opcional).
          </li>
          <li>
            <b>Aprovar:</b> revise e aprove em <b>Conteúdo</b> (todo post precisa de mídia).
          </li>
          <li>
            <b>Agendar:</b> em <b>Conteúdo → Agendar tudo automaticamente</b> (ou agende um a
            um) — com a estratégia otimizada, a IA escolhe os melhores horários pelo
            engajamento histórico.
          </li>
          <li>
            <b>Acompanhar:</b> na <b>Fila</b> (publicar agora/cancelar) e no <b>Analytics</b>{' '}
            (engajamento depois de publicado).
          </li>
        </ol>
      </div>
    </>
  )
}
