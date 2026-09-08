import { useEffect, useState } from 'react'
import { api, type MediaAsset } from '../api/client'
import { Empty, ErrorBanner, Loading, MediaThumb, TopBar } from '../components/ui'
import { IconTrash } from '../components/Icons'

const ORIGIN_LABEL: Record<string, string> = {
  owned: 'Própria',
  licensed: 'Licenciada',
  source_reference: 'De terceiro',
}

type Filter = 'all' | 'video' | 'image'

function sizeLabel(bytes: number): string {
  const mb = bytes / (1024 * 1024)
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export default function Library() {
  const [media, setMedia] = useState<MediaAsset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  const [bulkDeleting, setBulkDeleting] = useState(false)

  async function load() {
    setLoading(true)
    try {
      setMedia(await api.media())
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function remove(id: number) {
    if (
      !confirm(
        'Excluir esta mídia? O arquivo é apagado do servidor e não pode mais ser usado em novos posts.',
      )
    ) {
      return
    }
    setDeletingId(id)
    setError('')
    try {
      await api.deleteMedia(id)
      setMedia((prev) => prev.filter((m) => m.id !== id))
      setSelected((prev) => prev.filter((x) => x !== id))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setDeletingId(null)
    }
  }

  function toggle(id: number) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  async function removeMany(ids: number[], confirmMsg: string) {
    if (!ids.length) return
    if (!confirm(confirmMsg)) return
    setBulkDeleting(true)
    setError('')
    const failed: number[] = []
    for (const id of ids) {
      try {
        await api.deleteMedia(id)
      } catch {
        failed.push(id)
      }
    }
    setMedia((prev) => prev.filter((m) => !ids.includes(m.id) || failed.includes(m.id)))
    setSelected((prev) => prev.filter((x) => !ids.includes(x) || failed.includes(x)))
    if (failed.length) {
      setError(`${failed.length} mídia(s) não puderam ser excluídas.`)
    }
    setBulkDeleting(false)
  }

  function exitSelectMode() {
    setSelectMode(false)
    setSelected([])
  }

  const shown = media.filter((m) => {
    if (filter === 'all') return true
    if (filter === 'video') return m.kind === 'video'
    return m.kind === 'image' || m.kind === 'gif'
  })

  const allVideoIds = media.filter((m) => m.kind === 'video').map((m) => m.id)
  const allPhotoIds = media.filter((m) => m.kind === 'image' || m.kind === 'gif').map((m) => m.id)

  return (
    <>
      <TopBar title="Biblioteca">
        <div className="segmented">
          <button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>
            Tudo
          </button>
          <button className={filter === 'video' ? 'active' : ''} onClick={() => setFilter('video')}>
            Vídeos
          </button>
          <button className={filter === 'image' ? 'active' : ''} onClick={() => setFilter('image')}>
            Imagens
          </button>
        </div>
      </TopBar>

      {error && <ErrorBanner message={error} />}

      <div className="row wrap" style={{ gap: 8, padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <button
          className="btn ghost sm"
          disabled={bulkDeleting}
          onClick={() => (selectMode ? exitSelectMode() : setSelectMode(true))}
        >
          {selectMode ? 'Cancelar seleção' : 'Selecionar'}
        </button>
        <button
          className="btn danger sm"
          disabled={bulkDeleting || !allPhotoIds.length}
          onClick={() =>
            removeMany(
              allPhotoIds,
              `Excluir todas as ${allPhotoIds.length} foto(s)? Os arquivos são apagados do servidor.`,
            )
          }
        >
          <IconTrash size={14} /> Excluir todas as fotos
        </button>
        <button
          className="btn danger sm"
          disabled={bulkDeleting || !allVideoIds.length}
          onClick={() =>
            removeMany(
              allVideoIds,
              `Excluir todos os ${allVideoIds.length} vídeo(s)? Os arquivos são apagados do servidor.`,
            )
          }
        >
          <IconTrash size={14} /> Excluir todos os vídeos
        </button>

        {selectMode && (
          <>
            <span className="small muted">{selected.length} selecionado(s)</span>
            <button
              className="btn ghost sm"
              onClick={() =>
                setSelected(selected.length === shown.length ? [] : shown.map((m) => m.id))
              }
            >
              {selected.length === shown.length ? 'Limpar' : 'Selecionar tudo'}
            </button>
            <button
              className="btn danger sm"
              style={{ marginLeft: 'auto' }}
              disabled={bulkDeleting || !selected.length}
              onClick={() =>
                removeMany(selected, `Excluir ${selected.length} mídia(s) selecionada(s)?`)
              }
            >
              <IconTrash size={14} /> {bulkDeleting ? 'Excluindo...' : 'Excluir selecionados'}
            </button>
          </>
        )}
      </div>

      {loading ? (
        <Loading />
      ) : shown.length === 0 ? (
        <Empty
          title="Nenhuma mídia salva"
          hint="Fotos e vídeos enviados ao criar conteúdo aparecem aqui."
        />
      ) : (
        <div className="library-grid">
          {shown.map((m) => (
            <div className="card library-item" key={m.id}>
              <div className="library-thumb-wrap" style={{ position: 'relative' }}>
                {selectMode && (
                  <input
                    type="checkbox"
                    checked={selected.includes(m.id)}
                    onChange={() => toggle(m.id)}
                    style={{
                      position: 'absolute',
                      top: 8,
                      left: 8,
                      zIndex: 1,
                      width: 20,
                      height: 20,
                    }}
                  />
                )}
                <MediaThumb item={m} controls={m.kind === 'video'} fill />
              </div>
              <div className="row" style={{ marginTop: 10, gap: 6 }}>
                <span
                  className="small muted"
                  style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                  title={m.filename}
                >
                  {m.filename}
                </span>
                <span className="pill">{ORIGIN_LABEL[m.origin] ?? m.origin}</span>
              </div>
              <div className="small muted" style={{ marginTop: 4 }}>
                {sizeLabel(m.size_bytes)}
                {!m.publishable && ' · não publicável'}
              </div>
              <button
                className="btn danger sm block"
                style={{ marginTop: 10 }}
                disabled={deletingId === m.id}
                onClick={() => remove(m.id)}
              >
                <IconTrash size={14} /> {deletingId === m.id ? 'Excluindo...' : 'Excluir'}
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  )
}
