import { useEffect, useRef, useState, type ReactNode } from 'react'
import { IconHeart, IconPlatformThreads, IconPlatformX, IconRepost, IconReply, IconViews } from './Icons'
import type { Platform, SourcePost } from '../api/client'

export function TopBar({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <header className="topbar">
      <h1>{title}</h1>
      <div className="spacer" />
      {children}
    </header>
  )
}

export function Avatar({ name, url, sm }: { name: string; url?: string; sm?: boolean }) {
  const cls = `avatar${sm ? ' sm' : ''}`
  if (url) return <img className={cls} src={url} alt="" />
  return <div className={cls}>{(name || '?').slice(0, 1).toUpperCase()}</div>
}

export function Pill({ status, children }: { status?: string; children: ReactNode }) {
  return <span className={`pill${status ? ` ${status}` : ''}`}>{children}</span>
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty">
      <div className="bold" style={{ fontSize: 17, color: 'var(--text)' }}>
        {title}
      </div>
      {hint && <div style={{ marginTop: 6 }}>{hint}</div>}
    </div>
  )
}

const PLATFORM_TAB_KEY = 'volt.platformTab'

/** Aba X/Threads lembrada entre paginas (Dashboard, Meus Textos, Conteúdo, Fila). */
export function usePlatformTab(): [Platform, (p: Platform) => void] {
  const [tab, setTab] = useState<Platform>(
    () => (localStorage.getItem(PLATFORM_TAB_KEY) as Platform) || 'x',
  )
  useEffect(() => {
    localStorage.setItem(PLATFORM_TAB_KEY, tab)
  }, [tab])
  return [tab, setTab]
}

export function PlatformTabs({ value, onChange }: { value: Platform; onChange: (p: Platform) => void }) {
  return (
    <div className="tabs">
      <div className={`tab${value === 'x' ? ' active' : ''}`} onClick={() => onChange('x')}>
        <span className="row" style={{ gap: 6, justifyContent: 'center' }}>
          <IconPlatformX size={13} /> X
        </span>
      </div>
      <div
        className={`tab${value === 'threads' ? ' active' : ''}`}
        onClick={() => onChange('threads')}
      >
        <span className="row" style={{ gap: 6, justifyContent: 'center' }}>
          <IconPlatformThreads size={13} /> Threads
        </span>
      </div>
    </div>
  )
}

export function Loading() {
  return (
    <div className="empty">
      <div className="spinner" style={{ margin: '0 auto' }} />
    </div>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  return <div className="banner error">{message}</div>
}

export function Modal({
  title,
  onClose,
  children,
  maxWidth,
}: {
  title: ReactNode
  onClose: () => void
  children: ReactNode
  /** Sobrescreve o max-width padrao (560px) — usado por formularios maiores. */
  maxWidth?: number
}) {
  // Fecha so' quando o CLIQUE INTEIRO (mousedown + mouseup) acontece no
  // backdrop. Sem isso, selecionar texto dentro do modal e soltar o mouse
  // fora dele (comum ao arrastar a selecao ate' a borda) fechava o modal —
  // o `click` resultante nasce no ancestral comum (o backdrop) mesmo quando
  // o gesto comecou dentro do conteudo.
  const downOnBackdrop = useRef(false)
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        downOnBackdrop.current = e.target === e.currentTarget
      }}
      onClick={(e) => {
        if (downOnBackdrop.current && e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="modal"
        style={maxWidth ? { maxWidth } : undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="row" style={{ marginBottom: 16 }}>
          <h2 style={{ margin: 0, fontSize: 19 }}>{title}</h2>
          <div className="spacer" style={{ marginLeft: 'auto' }} />
          <button className="btn ghost sm" onClick={onClose}>
            Fechar
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Metrics({ post }: { post: SourcePost }) {
  return (
    <div className="metrics">
      <span>
        <IconReply /> {post.replies}
      </span>
      <span>
        <IconRepost /> {post.reposts}
      </span>
      <span>
        <IconHeart /> {post.likes}
      </span>
      <span>
        <IconViews /> {post.views}
      </span>
    </div>
  )
}

export function formatDate(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleString('pt-BR', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Preview de midia — usado em conteudo, fila e criacao.

Video usa <video> com o fragmento #t=0.1 para o navegador pintar um frame
em vez de um retangulo preto. */
export function MediaStrip({
  media,
  size = 64,
}: {
  media: { id: number; kind: string; url: string; filename: string }[]
  size?: number
}) {
  if (!media?.length) return null
  return (
    <div className="row wrap" style={{ gap: 6, margin: '8px 0' }}>
      {media.map((m) => (
        <MediaThumb key={m.id} item={m} size={size} />
      ))}
    </div>
  )
}

export function MediaThumb({
  item,
  size,
  fill,
}: {
  item: { kind: string; url: string; filename: string }
  size?: number
  fill?: boolean
}) {
  const style = fill
    ? { width: '100%', height: '100%' }
    : { width: size ?? 64, height: size ?? 64 }

  if (item.kind === 'video') {
    return (
      <div className="media-thumb video-wrap" style={style} title={item.filename}>
        <video
          src={`${item.url}#t=0.1`}
          muted
          playsInline
          preload="metadata"
          onMouseEnter={(e) => void e.currentTarget.play().catch(() => {})}
          onMouseLeave={(e) => {
            e.currentTarget.pause()
            e.currentTarget.currentTime = 0.1
          }}
        />
        <span className="play-badge">&#9654;</span>
      </div>
    )
  }

  return (
    <img
      className="media-thumb"
      src={item.url}
      alt={item.filename}
      title={item.filename}
      style={style}
      loading="lazy"
    />
  )
}
