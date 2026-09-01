import { useEffect, useState } from 'react'
import { api, type XAccount } from '../api/client'
import { Avatar, Empty, ErrorBanner, Loading, Modal, Pill, TopBar } from '../components/ui'

export default function Accounts() {
  const [accounts, setAccounts] = useState<XAccount[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [editing, setEditing] = useState<XAccount | null>(null)
  const [form, setForm] = useState<Partial<XAccount>>({})
  const [importing, setImporting] = useState<{ accountId: number | null } | null>(null)
  const [cookiesText, setCookiesText] = useState('')
  const [importBusy, setImportBusy] = useState(false)

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

  /** Importa cookies exportados do navegador LOCAL do usuario — metodo padrao
      de conexao, porque o X bloqueia login a partir do IP do servidor. O backend
      valida a sessao abrindo o x.com headless com os cookies recem-importados. */
  async function submitImport() {
    if (!importing || !cookiesText.trim()) return
    setImportBusy(true)
    setError('')
    try {
      const res =
        importing.accountId == null
          ? await api.importCookies(cookiesText)
          : await api.importCookiesInto(importing.accountId, cookiesText)
      setImporting(null)
      setCookiesText('')
      if (res.session_valid) {
        setNotice(`Sessão de @${res.username || res.account.username} importada e validada.`)
      } else {
        setError(
          'Cookies salvos, mas o X não validou a sessão (cookies expirados?). ' +
            'Exporte de novo estando logado no X e tente outra vez.',
        )
      }
      load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setImportBusy(false)
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
        <button
          className="btn sm"
          title="Cole os cookies exportados do seu navegador"
          onClick={() => {
            setImporting({ accountId: null })
            setCookiesText('')
          }}
        >
          Importar cookies
        </button>
      </TopBar>

      {error && <ErrorBanner message={error} />}
      {notice && <div className="banner info">{notice}</div>}

      <div className="banner">
        Conecte suas contas importando os <b>cookies do X</b> exportados do navegador da sua
        máquina (extensão "Get cookies.txt LOCALLY", só o site x.com). A sessão fica salva
        criptografada e o painel não usa a API oficial (paga). Nunca guardamos sua senha.
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
                <div className="small muted">
                  {a.has_proxy ? `Proxy: ${a.proxy_host || 'configurado'}` : 'Sem proxy — sai pelo IP do servidor'}
                </div>
                {a.auto_pilot && (
                  <div className="small" style={{ color: 'var(--accent)' }}>
                    ⚡ Piloto automático ligado ({a.content_mode === 'fast' ? 'reescrita rápida' : 'IA'})
                  </div>
                )}
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
                max={30}
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

          {(form.posts_per_day ?? 8) > 20 && (
            <div className="banner warning" style={{ margin: '10px 0 0' }}>
              {form.posts_per_day}/dia é volume alto. Sem proxy dedicado pra essa conta, isso
              aumenta o risco de ela ser sinalizada/suspensa pelo X — considere configurar um
              proxy (mais abaixo) ou baixar o valor se a conta for nova.
            </div>
          )}

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

          <div className="field" style={{ marginTop: 12 }}>
            <label className="label">
              Proxy dedicado desta conta {editing.has_proxy && '(configurado)'}
            </label>
            <input
              className="input"
              type="text"
              value={form.proxy_url ?? ''}
              onChange={(e) => setForm({ ...form, proxy_url: e.target.value })}
              placeholder={
                editing.has_proxy
                  ? `atual: ${editing.proxy_host || '(oculto)'} — cole outro pra trocar`
                  : 'http://usuario:senha@host:porta (opcional)'
              }
            />
            <div className="small muted" style={{ marginTop: 6 }}>
              Sem proxy, todas as contas saem pelo mesmo IP do servidor — o X pode
              correlacionar contas por isso. Preencha para essa conta navegar pelo seu
              próprio IP. Deixe vazio e salve para remover um proxy já configurado.
            </div>
          </div>

          <div className="field" style={{ marginTop: 16 }}>
            <label className="checkline">
              <input
                type="checkbox"
                checked={form.auto_pilot ?? false}
                onChange={(e) => setForm({ ...form, auto_pilot: e.target.checked })}
              />
              <span>Piloto automático</span>
            </label>
            <div className="small muted" style={{ marginTop: 4 }}>
              Gera rascunhos sozinho quando a fila de hoje está abaixo do teto ({form.posts_per_day ?? 8}
              /dia) e, ao você aprovar, já agenda no próximo horário livre (a cada 1-2h, respeitando o
              intervalo mínimo e a janela desta conta) — sem escolher data/hora na mão. Continua exigindo
              sua aprovação manual em Conteúdo; nunca publica nada sozinho.
            </div>

            {(form.auto_pilot ?? false) && (
              <div className="row" style={{ gap: 12, marginTop: 10 }}>
                <label className="checkline">
                  <input
                    type="radio"
                    name="content_mode"
                    checked={(form.content_mode ?? 'ai') === 'ai'}
                    onChange={() => setForm({ ...form, content_mode: 'ai' })}
                  />
                  <span>Texto por IA (mais lento, melhor qualidade)</span>
                </label>
                <label className="checkline">
                  <input
                    type="radio"
                    name="content_mode"
                    checked={form.content_mode === 'fast'}
                    onChange={() => setForm({ ...form, content_mode: 'fast' })}
                  />
                  <span>Reescrita rápida (sem IA, instantânea, mais mecânica)</span>
                </label>
              </div>
            )}
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
              className="btn ghost sm"
              onClick={() => {
                setEditing(null)
                setImporting({ accountId: editing.id })
                setCookiesText('')
              }}
            >
              Importar cookies
            </button>
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

      {importing && (
        <Modal
          title={importing.accountId == null ? 'Importar cookies' : 'Importar cookies nesta conta'}
          onClose={() => {
            setImporting(null)
            setCookiesText('')
          }}
        >
          <div className="banner info">
            Exporte os cookies do X no navegador <b>da sua máquina</b> — estando logado na
            conta — com a extensão &quot;Get cookies.txt LOCALLY&quot; (ou equivalente) e cole
            aqui. Na extensão, escolha exportar <b>só o site x.com</b> (não &quot;all
            cookies&quot;). Aceita cookies.txt (Netscape), lista JSON ou storage_state do
            Playwright. Funciona mesmo quando o X bloqueia o login pelo IP do servidor.
          </div>
          <textarea
            className="textarea"
            style={{ marginTop: 12, minHeight: 180, fontFamily: 'monospace', fontSize: 12 }}
            placeholder={
              '# Netscape HTTP Cookie File\n.x.com\tTRUE\t/\tTRUE\t1777777777\tauth_token\t...'
            }
            value={cookiesText}
            onChange={(e) => setCookiesText(e.target.value)}
          />
          <p className="small muted" style={{ marginTop: 8, marginBottom: 0 }}>
            Não importa se o arquivo tem milhares de linhas: só os cookies de
            x.com/twitter.com são aproveitados; o resto é descartado. Ficam criptografados
            no servidor e nunca mais aparecem nesta tela.
          </p>
          <div className="row" style={{ marginTop: 10, gap: 8 }}>
            <label className="btn ghost sm" style={{ cursor: 'pointer' }}>
              Escolher arquivo .txt/.json
              <input
                type="file"
                accept=".txt,.json,text/plain,application/json"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (!file) return
                  const reader = new FileReader()
                  reader.onload = () => setCookiesText(String(reader.result ?? ''))
                  reader.onerror = () =>
                    setError('Não consegui ler o arquivo. Cole o conteúdo no campo acima.')
                  reader.readAsText(file)
                }}
              />
            </label>
            <span className="small muted" style={{ alignSelf: 'center' }}>
              ou cole o conteúdo no campo acima
            </span>
          </div>
          <div className="row" style={{ marginTop: 16, gap: 8 }}>
            <button
              className="btn"
              disabled={importBusy || !cookiesText.trim()}
              onClick={submitImport}
            >
              {importBusy ? 'Importando e validando…' : 'Importar e validar'}
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}
