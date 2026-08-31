import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, type MediaAsset, type SourcePost, type XAccount } from '../api/client'
import { IconBack, IconImage, IconSparkle } from '../components/Icons'
import { Avatar, ErrorBanner, Loading, MediaThumb, Metrics, TopBar } from '../components/ui'

const LIMIT = 280

export default function Compose() {
  const { postId } = useParams()
  const [params] = useSearchParams()
  const textId = params.get('text_id')
  const navigate = useNavigate()

  const [post, setPost] = useState<SourcePost | null>(null)
  const [accounts, setAccounts] = useState<XAccount[]>([])
  const [aiAvailable, setAiAvailable] = useState(false)
  // Botao "Gerar versao com IA" no card do tweet vem com ?generate=ai.
  const autoGenRan = useRef(false)
  const [pendingAutoGen, setPendingAutoGen] = useState(params.get('generate') === 'ai')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [target, setTarget] = useState<number | ''>('')
  const [angles, setAngles] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const [sourceMode, setSourceMode] = useState<'post' | 'text'>('post')
  const [sourceMedia, setSourceMedia] = useState<MediaAsset[]>([])
  const [selectedSourceMedia, setSelectedSourceMedia] = useState<number[]>([])
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [media, setMedia] = useState<MediaAsset[]>([])
  const [uploading, setUploading] = useState(false)

  async function onPickFiles(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    setError('')
    try {
      for (const file of Array.from(files).slice(0, 4)) {
        const asset = await api.uploadMedia(file, 'owned')
        setMedia((prev) => [...prev, asset])
      }
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(false)
    }
  }

  useEffect(() => {
    async function boot() {
      const [accs, ai] = await Promise.all([api.xAccounts(), api.aiStatus()])
      setAccounts(accs)
      setAiAvailable(ai.available)
      if (accs.length) setTarget(accs[0].id)
      // Padrao: angulos do tweet. Sem tweet (ex.: "Meus Textos"), so "meu texto".
      setSourceMode(postId ? 'post' : 'text')

      if (textId) {
        // Veio de "Meus Textos": ja entra editavel na caixa final.
        const t = await api.manualText(Number(textId))
        setDraft(t.text)
      } else if (postId) {
        // Busca direta por id: o post pode ser antigo e estar fora da lista recente.
        const p = await api.sourcePost(Number(postId))
        setPost(p)
        // Midia do proprio tweet: baixada sem metadados na coleta.
        const sm = await api.sourcePostMedia(Number(postId))
        setSourceMedia(sm)
        setSelectedSourceMedia(sm.map((m) => m.id))
      }
    }
    boot()
      .catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false))
  }, [postId, textId])

  // Origem da geracao conforme a opcao escolhida: o tweet ou o texto da caixa.
  const usePost = sourceMode === 'post' && !!post
  const aiSource = usePost && post ? post.text : draft.trim()

  // Dispara automaticamente a geracao quando o usuario veio do card do tweet.
  useEffect(() => {
    if (
      pendingAutoGen &&
      !autoGenRan.current &&
      aiAvailable &&
      post &&
      target !== ''
    ) {
      autoGenRan.current = true
      setPendingAutoGen(false)
      void generate()
    }
  })

  async function generate() {
    if (!target || !aiSource) return
    setGenerating(true)
    setError('')
    try {
      const res = await api.generate({
        target_x_account_id: Number(target),
        source_post_id: usePost && post ? post.id : null,
        source_text: usePost ? undefined : aiSource,
        count: 3,
      })
      setAngles(res.angles)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setGenerating(false)
    }
  }

  async function save(approve: boolean) {
    if (!draft.trim() || !target) return
    setSaving(true)
    setError('')
    try {
      const candidate = await api.createCandidate({
        text: draft.trim(),
        target_x_account_id: Number(target),
        source_post_id: post?.id ?? null,
        origin: angles.includes(draft.trim()) ? 'ai' : 'manual',
        media_ids: [...selectedSourceMedia, ...media.map((m) => m.id)],
      })
      if (approve) await api.approve(candidate.id)
      navigate('/inbox')
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Loading />

  const over = draft.length > LIMIT

  return (
    <>
      <TopBar title="Criar conteúdo">
        <button className="btn ghost sm" onClick={() => navigate(-1)}>
          <IconBack size={18} />
        </button>
      </TopBar>

      {error && <ErrorBanner message={error} />}

      {post && (
        <div className="card">
          <div className="small muted bold" style={{ marginBottom: 10 }}>
            POST ORIGINAL — referência, não copie
          </div>
          <div className="row" style={{ alignItems: 'flex-start' }}>
            <Avatar name={post.author_username} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="bold">@{post.author_username}</div>
              <p className="post-text">{post.text}</p>
              <Metrics post={post} />
            {sourceMedia.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div className="small muted bold" style={{ marginBottom: 6 }}>
                  MÍDIA DO TWEET — sem metadados, toque para usar
                </div>
                <div className="row wrap" style={{ gap: 8 }}>
                  {sourceMedia.map((m) => {
                    const on = selectedSourceMedia.includes(m.id)
                    return (
                      <button
                        key={m.id}
                        type="button"
                        className={`media-tog${on ? ' on' : ''}`}
                        title={on ? 'Será publicada com o post' : 'Não usar esta mídia'}
                        onClick={() =>
                          setSelectedSourceMedia((prev) =>
                            on ? prev.filter((id) => id !== m.id) : [...prev, m.id],
                          )
                        }
                      >
                        <MediaThumb item={m} size={84} />
                        {on && <span className="media-tog-check">✓</span>}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
            </div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="field">
          <label className="label">Conta destino</label>
          {accounts.length === 0 ? (
            <div className="banner error" style={{ margin: 0 }}>
              Nenhuma conta do X conectada. Conecte uma em Contas.
            </div>
          ) : (
            <select
              className="select"
              value={target}
              onChange={(e) => setTarget(Number(e.target.value))}
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  @{a.username}
                </option>
              ))}
            </select>
          )}
        </div>

        {aiAvailable ? (
          <>
            {post && (
              <div className="field" style={{ marginTop: 14 }}>
                <label className="label">Origem dos ângulos</label>
                <div className="segmented">
                  <button
                    type="button"
                    className={sourceMode === 'post' ? 'active' : ''}
                    onClick={() => setSourceMode('post')}
                  >
                    Texto do tweet
                  </button>
                  <button
                    type="button"
                    className={sourceMode === 'text' ? 'active' : ''}
                    onClick={() => setSourceMode('text')}
                  >
                    Meu texto
                  </button>
                </div>
              </div>
            )}
            <button
              className="btn ghost block"
              style={{ marginTop: post ? 12 : 0 }}
              onClick={generate}
              disabled={generating || !target || !aiSource}
            >
              <IconSparkle size={18} />
              {generating
                ? 'Gerando...'
                : aiSource
                  ? usePost
                    ? 'Gerar 3 ângulos do tweet com IA'
                    : 'Gerar 3 ângulos do meu texto com IA'
                  : 'Escreva um texto abaixo para gerar ângulos'}
            </button>
          </>
        ) : (
          <div className="banner" style={{ margin: 0 }}>
            IA desativada — escreva o texto você mesmo. Para ativar, configure{' '}
            <code>AI_PROVIDER=ollama</code> e <code>AI_ENABLED=true</code> no .env.
          </div>
        )}
      </div>

      {angles.length > 0 && (
        <>
          <div className="card" style={{ background: 'var(--bg-elev)' }}>
            <div className="bold">Sugestões</div>
            <div className="small muted">Toque para usar como base — você pode editar depois.</div>
          </div>
          {angles.map((angle, i) => (
            <div className="card hoverable" key={i} onClick={() => setDraft(angle)}>
              <div className="small muted bold" style={{ marginBottom: 4 }}>
                ÂNGULO {i + 1}
              </div>
              <p className="post-text" style={{ margin: 0 }}>
                {angle}
              </p>
            </div>
          ))}
        </>
      )}

      <div className="card">
        <label className="label">Texto final</label>
        <textarea
          className="textarea"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Escreva ou escolha um ângulo acima..."
        />
        {media.length > 0 && (
          <div className="row wrap" style={{ gap: 8, marginTop: 12 }}>
            {media.map((m) => (
              <div key={m.id} style={{ position: 'relative' }}>
                <MediaThumb item={m} size={84} />
                <button
                  className="btn danger sm"
                  style={{ position: 'absolute', top: -6, right: -6, padding: '2px 8px' }}
                  onClick={() => setMedia((prev) => prev.filter((x) => x.id !== m.id))}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="row" style={{ marginTop: 12 }}>
          <label className="btn ghost sm" style={{ cursor: 'pointer' }}>
            <IconImage size={18} />
            {uploading ? 'Enviando...' : 'Foto / vídeo'}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime"
              multiple
              hidden
              onChange={(e) => onPickFiles(e.target.files)}
            />
          </label>
          <span className="small muted">Foto / vídeo próprios (opcional)</span>
        </div>

        <div className="row" style={{ marginTop: 10 }}>
          <span className={`counter${over ? ' over' : ''}`}>
            {draft.length}/{LIMIT}
          </span>
          <div style={{ marginLeft: 'auto' }} className="row">
            <button
              className="btn ghost sm"
              onClick={() => save(false)}
              disabled={saving || over || !draft.trim() || !target}
            >
              Salvar rascunho
            </button>
            <button
              className="btn sm"
              onClick={() => save(true)}
              disabled={saving || over || !draft.trim() || !target}
            >
              Aprovar
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
