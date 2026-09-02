import { useEffect, useState } from 'react'
import { api, type Me } from '../api/client'
import { ErrorBanner, Pill, TopBar } from '../components/ui'

export default function Settings() {
  const [ai, setAi] = useState<{ available: boolean; model: string | null } | null>(null)
  const [theme, setTheme] = useState(
    () => localStorage.getItem('theme') ?? 'dark',
  )
  const [me, setMe] = useState<Me | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.aiStatus().then(setAi).catch(() => setAi({ available: false, model: null }))
    api.me().then(setMe).catch(() => {})
  }, [])

  async function toggleCrossPosting(enabled: boolean) {
    if (!me) return
    setMe({ ...me, cross_posting_check_enabled: enabled }) // otimista
    try {
      await api.updateSettings({ cross_posting_check_enabled: enabled })
    } catch (err) {
      setMe(me) // desfaz se falhar
      setError((err as Error).message)
    }
  }

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  return (
    <>
      <TopBar title="Configurações" />

      <div className="card">
        <div className="bold" style={{ marginBottom: 10 }}>
          Aparência
        </div>
        <select className="select" value={theme} onChange={(e) => setTheme(e.target.value)}>
          <option value="dark">Escuro</option>
          <option value="light">Claro</option>
        </select>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: 8 }}>
          <span className="bold">Inteligência Artificial</span>
          <Pill status={ai?.available ? 'approved' : 'pending'}>
            {ai?.available ? 'ativa' : 'desativada'}
          </Pill>
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          {ai?.available ? (
            <>
              Modelo: <code>{ai.model}</code>. A geração é sempre opcional — você decide quando usar.
            </>
          ) : (
            <>
              Para ativar, defina <code>AI_ENABLED=true</code> e <code>ANTHROPIC_API_KEY</code> no
              .env. Atenção: o plano Claude Pro não inclui acesso à API — é cobrança separada, por
              token (centavos por geração).
            </>
          )}
        </p>
      </div>

      <div className="card">
        <div className="bold" style={{ marginBottom: 8 }}>
          Como o Volt publica
        </div>
        <p className="small muted" style={{ margin: 0 }}>
          O painel <b>não usa a API oficial do X</b> (paga por post). A publicação e a coleta
          rodam num navegador no servidor, com a sessão da sua conta (importada por cookies) —
          cada conta num contexto isolado. A IA de geração de ângulos é opcional e custa
          centavos por uso (billing próprio).
        </p>
      </div>

      {error && <ErrorBanner message={error} />}

      <div className="card">
        <label className="checkline">
          <input
            type="checkbox"
            checked={me?.cross_posting_check_enabled ?? true}
            onChange={(e) => toggleCrossPosting(e.target.checked)}
          />
          <span>Bloquear conteúdo similar entre contas ao aprovar</span>
        </label>
        <div className="small muted" style={{ marginTop: 6 }}>
          Compara o texto com o que já foi aprovado/agendado/publicado nas SUAS outras contas.
          Acima do limiar de similaridade, a aprovação é recusada até você editar o texto.
          Desative se preferir aprovar sem essa checagem (ex: contas que compartilham conteúdo de
          propósito).
        </div>
      </div>

      <div className="card">
        <div className="bold" style={{ marginBottom: 8 }}>
          Proteções ativas
        </div>
        <ul className="small muted" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9 }}>
          <li>
            Bloqueio de conteúdo idêntico ou substancialmente similar entre contas —{' '}
            {me?.cross_posting_check_enabled ?? true ? 'ligado' : 'desligado (opcional acima)'}
          </li>
          <li>Aprovação humana obrigatória antes de agendar</li>
          <li>Limite de frequência por conta (anti-spam)</li>
          <li>Rate limit do X sempre respeitado — nunca contornado</li>
          <li>Automação de navegador com sessão isolada por conta (sem API oficial)</li>
          <li>Tokens criptografados em repouso</li>
        </ul>
      </div>
    </>
  )
}
