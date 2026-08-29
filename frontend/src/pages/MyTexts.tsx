import { useEffect, useState } from 'react'
import { api, type ManualText, type MediaAsset, type XAccount } from '../api/client'
import { IconImage, IconPlus, IconTrash } from '../components/Icons'
import { Empty, ErrorBanner, Loading, MediaThumb, Modal, TopBar } from '../components/ui'

/** Passos do assistente de criacao em massa. */
type Step = 1 | 2 | 3

const STEP_TITLES = ['', 'Escolher mídias', 'Escolher contas', 'Confirmar']

export default function MyTexts() {
  const [texts, setTexts] = useState<ManualText[]>([])
  const [media, setMedia] = useState<MediaAsset[]>([])
  const [accounts, setAccounts] = useState<XAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)

  // Assistente de criacao em massa
  const [wizard, setWizard] = useState(false)
  const [step, setStep] = useState<Step>(1)
  const [pickedTexts, setPickedTexts] = useState<number[]>([])
  const [pickedMedia, setPickedMedia] = useState<number[]>([])
  const [pickedAccounts, setPickedAccounts] = useState<number[]>([])
  const [count, setCount] = useState(0)
  const [working, setWorking] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const [t, m, a] = await Promise.all([api.manualTexts(), api.media(), api.xAccounts()])
      setTexts(t)
      setMedia(m)
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

  const blocks = draft
    .split(';')
    .map((b) => b.trim())
    .filter(Boolean)

  async function saveTexts() {
    if (!blocks.length) return
    setSaving(true)
    setError('')
    try {
      await api.addManualTexts(blocks)
      setDraft('')
      load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  async function onUpload(files: FileList | null) {
    if (!files?.length) return
    setUploading(true)
    setError('')
    try {
      for (const file of Array.from(files)) {
        await api.uploadMedia(file, 'owned')
      }
      load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(false)
    }
  }

  function toggle(list: number[], set: (v: number[]) => void, id: number) {
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id])
  }

  function openWizard() {
    setStep(1)
    setPickedMedia([])
    setPickedAccounts([])
    setCount(0)
    setWizard(true)
  }

  async function createPosts() {
    setWorking(true)
    setError('')
    try {
      const res = await api.createBulk({
        text_ids: pickedTexts,
        account_ids: pickedAccounts,
        media_ids: pickedMedia,
        count: count || undefined,
        attach_media: pickedMedia.length > 0,
      })
      const dist = Object.entries(res.per_account)
        .map(([user, n]) => `@${user}: ${n}`)
        .join(' · ')
      setNotice(`${res.created} posts criados, aguardando aprovação em Conteúdo. ${dist}`)
      setWizard(false)
      setPickedTexts([])
      load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setWorking(false)
    }
  }

  const maxPosts = Math.min(pickedTexts.length, 200)
  const connected = accounts.filter((a) => a.connected)

  return (
    <>
      <TopBar title="Meus Textos" />

      <div className="card">
        <label className="label">Escreva ou cole seus textos</label>
        <textarea
          className="textarea"
          style={{ minHeight: 140 }}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Primeiro texto; Segundo texto; Terceiro texto"
        />
        <div className="row" style={{ marginTop: 10 }}>
          <span className="small muted">
            {blocks.length > 0
              ? `${blocks.length} texto(s) a salvar`
              : 'Separe por ponto e vírgula (;)'}
          </span>
          <button
            className="btn sm"
            style={{ marginLeft: 'auto' }}
            onClick={saveTexts}
            disabled={saving || !blocks.length}
          >
            <IconPlus size={16} /> {saving ? 'Salvando...' : 'Salvar'}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="row">
          <label className="btn ghost sm" style={{ cursor: 'pointer' }}>
            <IconImage size={18} />
            {uploading ? 'Enviando...' : 'Adicionar mídia'}
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime"
              multiple
              hidden
              onChange={(e) => onUpload(e.target.files)}
            />
          </label>
          <span className="small muted">{media.length} na biblioteca</span>
        </div>
        {media.length > 0 && (
          <div className="media-grid" style={{ marginTop: 12 }}>
            {media.slice(0, 12).map((m) => (
              <div key={m.id} className="media-pick" style={{ cursor: 'default' }}>
                <MediaThumb item={m} fill />
              </div>
            ))}
          </div>
        )}
      </div>

      {error && <ErrorBanner message={error} />}
      {notice && <div className="banner info">{notice}</div>}

      {texts.length > 0 && (
        <div
          className="row"
          style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)' }}
        >
          <button
            className="btn ghost sm"
            onClick={() =>
              setPickedTexts(pickedTexts.length === texts.length ? [] : texts.map((t) => t.id))
            }
          >
            {pickedTexts.length === texts.length ? 'Limpar' : 'Selecionar tudo'}
          </button>
          <span className="small muted">{pickedTexts.length} selecionado(s)</span>
          <button
            className="btn sm"
            style={{ marginLeft: 'auto' }}
            disabled={!pickedTexts.length}
            onClick={openWizard}
          >
            Criar posts
          </button>
        </div>
      )}

      {loading ? (
        <Loading />
      ) : texts.length === 0 ? (
        <Empty title="Nenhum texto ainda" hint="Escreva acima, separando por ponto e vírgula." />
      ) : (
        texts.map((t) => (
          <article className="card" key={t.id}>
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <input
                type="checkbox"
                checked={pickedTexts.includes(t.id)}
                onChange={() => toggle(pickedTexts, setPickedTexts, t.id)}
                style={{ marginTop: 4, width: 18, height: 18, flexShrink: 0 }}
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <p className="post-text" style={{ marginTop: 0 }}>
                  {t.text}
                </p>
                <div className="row">
                  <span className="small muted">usado {t.used_count}x</span>
                  <button
                    className="btn danger sm"
                    style={{ marginLeft: 'auto' }}
                    onClick={async () => {
                      await api.deleteManualText(t.id)
                      load()
                    }}
                  >
                    <IconTrash />
                  </button>
                </div>
              </div>
            </div>
          </article>
        ))
      )}

      {wizard && (
        <Modal title={STEP_TITLES[step]} onClose={() => setWizard(false)}>
          <div className="steps">
            {[1, 2, 3].map((n) => (
              <div key={n} className={`step-dot${step >= n ? ' on' : ''}`} />
            ))}
          </div>

          {step === 1 && (
            <>
              <p className="small muted" style={{ marginTop: 0 }}>
                As mídias são distribuídas <strong>aleatoriamente</strong> entre os posts. Deixe
                vazio para criar posts só com texto.
              </p>
              {media.length === 0 ? (
                <div className="banner">Nenhuma mídia na biblioteca. Você pode seguir sem.</div>
              ) : (
                <div className="media-grid">
                  {media.map((m) => (
                    <button
                      key={m.id}
                      className={`media-pick${pickedMedia.includes(m.id) ? ' on' : ''}`}
                      onClick={() => toggle(pickedMedia, setPickedMedia, m.id)}
                    >
                      <MediaThumb item={m} fill />
                      {pickedMedia.includes(m.id) && <span className="tick">&#10003;</span>}
                    </button>
                  ))}
                </div>
              )}
              <button className="btn block" style={{ marginTop: 16 }} onClick={() => setStep(2)}>
                Continuar {pickedMedia.length > 0 ? `(${pickedMedia.length} mídias)` : ''}
              </button>
            </>
          )}

          {step === 2 && (
            <>
              <p className="small muted" style={{ marginTop: 0 }}>
                Os posts serão distribuídos aleatoriamente entre as contas escolhidas.
              </p>
              {connected.length === 0 ? (
                <div className="banner error">Nenhuma conta do X conectada.</div>
              ) : (
                <div className="pick-grid">
                  {connected.map((a) => (
                    <button
                      key={a.id}
                      className={`pick-card${pickedAccounts.includes(a.id) ? ' on' : ''}`}
                      onClick={() => toggle(pickedAccounts, setPickedAccounts, a.id)}
                    >
                      {a.avatar_url ? (
                        <img className="avatar sm" src={a.avatar_url} alt="" />
                      ) : (
                        <div className="avatar sm">{a.username.slice(0, 1).toUpperCase()}</div>
                      )}
                      <span className="name">@{a.username}</span>
                    </button>
                  ))}
                </div>
              )}
              <div className="row" style={{ marginTop: 16, gap: 8 }}>
                <button className="btn ghost sm" onClick={() => setStep(1)}>
                  Voltar
                </button>
                <button
                  className="btn sm"
                  style={{ marginLeft: 'auto' }}
                  disabled={!pickedAccounts.length}
                  onClick={() => setStep(3)}
                >
                  Continuar
                </button>
              </div>
            </>
          )}

          {step === 3 && (
            <>
              <div className="field">
                <label className="label">Quantos posts criar? (máx. {maxPosts})</label>
                <input
                  className="input"
                  type="number"
                  min={1}
                  max={maxPosts}
                  value={count || maxPosts}
                  onChange={(e) => setCount(Math.min(Number(e.target.value), maxPosts))}
                />
                <div className="small muted" style={{ marginTop: 6 }}>
                  Cada texto é usado uma única vez — por isso o máximo é o número de textos
                  selecionados.
                </div>
              </div>

              <div className="banner">
                <strong>{count || maxPosts} posts</strong> entre{' '}
                <strong>{pickedAccounts.length} conta(s)</strong>
                {pickedMedia.length > 0 ? `, com ${pickedMedia.length} mídia(s) sorteadas` : ''}.
                <br />
                <br />
                Todos entram como <strong>pendentes</strong> — nada vai para o X sem você aprovar.
              </div>

              <div className="row" style={{ marginTop: 16, gap: 8 }}>
                <button className="btn ghost sm" onClick={() => setStep(2)}>
                  Voltar
                </button>
                <button
                  className="btn"
                  style={{ marginLeft: 'auto' }}
                  onClick={createPosts}
                  disabled={working}
                >
                  {working ? 'Criando...' : 'Criar posts'}
                </button>
              </div>
            </>
          )}
        </Modal>
      )}
    </>
  )
}
