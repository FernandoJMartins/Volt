import { useEffect, useState } from 'react'
import { api, type XAccount } from '../api/client'
import { IconPlus } from '../components/Icons'
import { Avatar, Empty, ErrorBanner, Loading, Modal, Pill, TopBar } from '../components/ui'

export default function Accounts() {
  const [accounts, setAccounts] = useState<XAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState<XAccount | null>(null)
  const [form, setForm] = useState<Partial<XAccount>>({})

  async function load() {
    setLoading(true)
    try {
      setAccounts(await api.xAccounts())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('connected')) setNotice(`@${params.get('connected')} conectada com sucesso.`)
    if (params.get('error')) setError(`Falha ao conectar: ${params.get('error')}`)
    load()
  }, [])

  async function connect() {
    try {
      const { authorize_url } = await api.connectX()
      window.location.href = authorize_url
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function save() {
    if (!editing) return
    try {
      await api.updateXAccount(editing.id, form)
      setEditing(null)
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <>
      <TopBar title="Contas">
        <button className="btn sm" onClick={connect}>
          <IconPlus size={18} /> Conectar
        </button>
      </TopBar>

      {error && <ErrorBanner message={error} />}
      {notice && <div className="banner info">{notice}</div>}

      <div className="banner">
        A conexão usa OAuth oficial do X. Nunca guardamos sua senha, e os tokens ficam
        criptografados — não são exibidos aqui nem enviados ao navegador.
      </div>

      {loading ? (
        <Loading />
      ) : accounts.length === 0 ? (
        <Empty
          title="Nenhuma conta conectada"
          hint="Conecte sua primeira conta do X para publicar."
        />
      ) : (
        accounts.map((a) => (
          <div className="card" key={a.id}>
            <div className="row">
              <Avatar name={a.username} url={a.avatar_url} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="row" style={{ gap: 6 }}>
                  <span className="bold">{a.display_name || a.username}</span>
                  <Pill status={a.connected ? 'approved' : 'failed'}>
                    {a.connected ? 'conectada' : 'sem token'}
                  </Pill>
                </div>
                <div className="small muted">
                  @{a.username} · {a.posts_per_day}/dia · {a.window_start}–{a.window_end}
                </div>
              </div>
              <button
                className="btn ghost sm"
                onClick={() => {
                  setEditing(a)
                  setForm(a)
                }}
              >
                Configurar
              </button>
            </div>

            {a.persona_prompt && (
              <p className="small muted" style={{ marginTop: 10, marginBottom: 0 }}>
                {a.persona_prompt.slice(0, 140)}
                {a.persona_prompt.length > 140 && '...'}
              </p>
            )}
          </div>
        ))
      )}

      {editing && (
        <Modal title={`@${editing.username}`} onClose={() => setEditing(null)}>
          <div className="field">
            <label className="label">Personalidade / instruções próprias desta conta</label>
            <textarea
              className="textarea"
              value={form.persona_prompt ?? ''}
              onChange={(e) => setForm({ ...form, persona_prompt: e.target.value })}
              placeholder={'Tom:\n- informal\n- provocativo\n- frases curtas\n- linguagem brasileira'}
            />
            <div className="small muted" style={{ marginTop: 6 }}>
              Cada conta tem identidade própria — isso evita que virem cópias umas das outras.
            </div>
          </div>

          <div className="row" style={{ gap: 12 }}>
            <div style={{ flex: 1 }}>
              <label className="label">Posts por dia</label>
              <input
                className="input"
                type="number"
                min={1}
                max={24}
                value={form.posts_per_day ?? 8}
                onChange={(e) => setForm({ ...form, posts_per_day: Number(e.target.value) })}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label className="label">Intervalo mín. (min)</label>
              <input
                className="input"
                type="number"
                min={15}
                value={form.min_interval_minutes ?? 30}
                onChange={(e) =>
                  setForm({ ...form, min_interval_minutes: Number(e.target.value) })
                }
              />
            </div>
          </div>

          <div className="row" style={{ gap: 12, marginTop: 12 }}>
            <div style={{ flex: 1 }}>
              <label className="label">Início</label>
              <input
                className="input"
                type="time"
                value={form.window_start ?? '08:00'}
                onChange={(e) => setForm({ ...form, window_start: e.target.value })}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label className="label">Fim</label>
              <input
                className="input"
                type="time"
                value={form.window_end ?? '23:00'}
                onChange={(e) => setForm({ ...form, window_end: e.target.value })}
              />
            </div>
          </div>

          <label className="checkline" style={{ marginTop: 16 }}>
            <input
              type="checkbox"
              checked={form.is_sensitive ?? false}
              onChange={(e) => setForm({ ...form, is_sensitive: e.target.checked })}
            />
            <span>Conta marca conteúdo como sensível (+18)</span>
          </label>

          <label className="checkline">
            <input
              type="checkbox"
              checked={form.is_active ?? true}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
            />
            <span>Conta ativa</span>
          </label>

          <div className="row" style={{ marginTop: 20, gap: 8 }}>
            <button
              className="btn danger sm"
              onClick={async () => {
                await api.deleteXAccount(editing.id)
                setEditing(null)
                load()
              }}
            >
              Desconectar
            </button>
            <button className="btn" style={{ marginLeft: 'auto' }} onClick={save}>
              Salvar
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}
