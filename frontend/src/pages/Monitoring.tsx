import { useEffect, useState } from 'react'
import { api, type MonitoredAccount } from '../api/client'
import { IconPlus, IconRefresh, IconTrash } from '../components/Icons'
import { Empty, ErrorBanner, Loading, Modal, TopBar, formatDate } from '../components/ui'

export default function Monitoring() {
  const [sources, setSources] = useState<MonitoredAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const [username, setUsername] = useState('')

  async function load() {
    setLoading(true)
    try {
      setSources(await api.monitored())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function addSource() {
    try {
      await api.addMonitored({ username: username.replace('@', ''), source_type: 'x_api' })
      setUsername('')
      setOpen(false)
      load()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <>
      <TopBar title="Monitoramento">
        <button className="btn sm" onClick={() => setOpen(true)}>
          <IconPlus size={18} /> Nova fonte
        </button>
      </TopBar>

      <div className="banner">
        Coleta posts reais de contas do X. <strong>Cada post lido é cobrado</strong> pela API
        (~US$0,005). Para publicar seus próprios textos sem custo, use <strong>Meus Textos</strong>.
      </div>

      {error && <ErrorBanner message={error} />}

      {loading ? (
        <Loading />
      ) : sources.length === 0 ? (
        <Empty
          title="Nenhuma fonte monitorada"
          hint="Adicione uma conta do X para acompanhar o que ela publica."
        />
      ) : (
        sources.map((s) => (
          <div className="card" key={s.id}>
            <div className="row">
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="bold">@{s.username}</div>
                <div className="small muted">
                  {s.posts_found} posts · última coleta {formatDate(s.last_collected_at)}
                </div>
              </div>
              <button
                className="btn ghost sm"
                title="Coletar agora"
                onClick={async () => {
                  await api.collectNow(s.id)
                  setTimeout(load, 2000)
                }}
              >
                <IconRefresh />
              </button>
              <button
                className="btn danger sm"
                onClick={async () => {
                  await api.deleteMonitored(s.id)
                  load()
                }}
              >
                <IconTrash />
              </button>
            </div>
          </div>
        ))
      )}

      {open && (
        <Modal title="Nova fonte monitorada" onClose={() => setOpen(false)}>
          <div className="field">
            <label className="label">Username no X</label>
            <input
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="@perfil"
            />
          </div>
          <div className="banner" style={{ margin: '0 0 16px' }}>
            Exige acesso de leitura pago na API do X. No tier gratuito a coleta retorna erro 403.
          </div>
          <button className="btn block" onClick={addSource} disabled={!username.trim()}>
            Adicionar
          </button>
        </Modal>
      )}
    </>
  )
}
