const BASE = '/api'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let message = `Erro ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') {
        message = body.detail
      } else if (Array.isArray(body.detail)) {
        // FastAPI 422 devolve uma lista de objetos {msg, ...}.
        message = body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join('; ')
      }
    } catch {
      /* resposta sem corpo JSON */
    }
    throw new Error(message)
  }
  return res.status === 204 ? (null as T) : res.json()
}

const get = <T,>(p: string) => request<T>(p)
const post = <T,>(p: string, body?: unknown) =>
  request<T>(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
const patch = <T,>(p: string, body: unknown) =>
  request<T>(p, { method: 'PATCH', body: JSON.stringify(body) })
const del = <T,>(p: string) => request<T>(p, { method: 'DELETE' })

// ---------- Tipos ----------

export type XAccount = {
  id: number
  username: string
  display_name: string
  avatar_url: string
  timezone: string
  is_active: boolean
  is_sensitive: boolean
  persona_prompt: string
  categories: string[]
  posts_per_day: number
  window_start: string
  window_end: string
  min_interval_minutes: number
  connected: boolean
}

export type MonitoredAccount = {
  id: number
  username: string
  display_name: string
  source_type: 'manual' | 'x_api'
  is_active: boolean
  last_collected_at: string | null
  posts_found: number
}

export type SourcePost = {
  id: number
  text: string
  author_username: string
  posted_at: string
  likes: number
  reposts: number
  replies: number
  views: number
  has_media: boolean
  original_url: string
  score: number
  score_breakdown: Record<string, number>
}

export type PostMedia = { id: number; kind: string; url: string; filename: string }

export type Candidate = {
  id: number
  media: PostMedia[]
  text: string
  status: string
  origin: string
  block_reason: string
  source_post_id: number | null
  target_x_account_id: number | null
  account_username: string | null
  created_at: string
}

export type QueueItem = {
  id: number
  media: PostMedia[]
  scheduled_at: string
  status: string
  attempts: number
  last_error: string
  published_post_id: string
  x_account_id: number
  account_username: string | null
  text: string
}

export type ManualText = {
  id: number
  text: string
  tags: string[]
  is_active: boolean
  used_count: number
}

export type MediaAsset = {
  id: number
  filename: string
  mime_type: string
  kind: 'image' | 'video' | 'gif'
  size_bytes: number
  origin: 'owned' | 'licensed' | 'source_reference'
  publishable: boolean
  is_sensitive: boolean
  url: string
}

export type Stats = Record<string, number>

// ---------- Endpoints ----------

export const api = {
  me: () => get<{ id: number; email: string }>('/auth/me'),
  login: (email: string, password: string) =>
    post<{ id: number }>('/auth/login', { email, password }),
  register: (email: string, password: string) =>
    post<{ id: number }>('/auth/register', { email, password }),
  logout: () => post('/auth/logout'),

  stats: () => get<Stats>('/dashboard/stats'),

  xAccounts: () => get<XAccount[]>('/x/accounts'),
  importCookies: (cookiesText: string) =>
    post<{ account: XAccount; session_valid: boolean; username: string }>(
      '/x/accounts/browser/import-cookies',
      { cookies_text: cookiesText },
    ),
  importCookiesInto: (id: number, cookiesText: string) =>
    post<{ account: XAccount; session_valid: boolean; username: string }>(
      `/x/accounts/${id}/browser/cookies`,
      { cookies_text: cookiesText },
    ),
  updateXAccount: (id: number, body: Partial<XAccount>) => patch<XAccount>(`/x/accounts/${id}`, body),
  deleteXAccount: (id: number) => del(`/x/accounts/${id}`),

  monitored: () => get<MonitoredAccount[]>('/monitoring/accounts'),
  addMonitored: (body: { username: string; source_type: string }) =>
    post('/monitoring/accounts', body),
  updateMonitored: (id: number, body: { source_type?: string; is_active?: boolean }) =>
    patch(`/monitoring/accounts/${id}`, body),
  deleteMonitored: (id: number) => del(`/monitoring/accounts/${id}`),
  collectNow: (id: number) => post(`/monitoring/accounts/${id}/collect`),

  manualTexts: () => get<ManualText[]>('/manual-texts'),
  manualText: (id: number) => get<ManualText>(`/manual-texts/${id}`),
  addManualTexts: (texts: string[]) =>
    post<{ created: number }>('/manual-texts', texts.map((text) => ({ text, tags: [] }))),
  deleteManualText: (id: number) => del(`/manual-texts/${id}`),

  sourcePosts: (order: 'score' | 'recent' = 'score') =>
    get<SourcePost[]>(`/source-posts?order=${order}`),

  aiStatus: () => get<{ available: boolean; model: string | null }>('/content/ai-status'),
  generate: (body: {
    target_x_account_id: number
    source_post_id?: number | null
    source_text?: string
    count: number
  }) => post<{ angles: string[] }>('/content/generate', body),
  candidates: (status?: string) =>
    get<Candidate[]>(`/content${status ? `?status=${status}` : ''}`),
  createCandidate: (body: {
    text: string
    target_x_account_id: number
    source_post_id?: number | null
    origin?: string
    media_ids?: number[]
  }) => post<Candidate>('/content', body),
  createBulk: (body: {
    text_ids: number[]
    account_ids: number[]
    media_ids?: number[]
    count?: number
    attach_media?: boolean
  }) =>
    post<{ created: number; per_account: Record<string, number>; skipped_texts: number }>(
      '/content/bulk',
      body,
    ),

  media: () => get<MediaAsset[]>('/media'),
  uploadMedia: async (file: File, origin: string) => {
    const form = new FormData()
    form.append('file', file)
    form.append('origin', origin)
    const res = await fetch('/api/media', { method: 'POST', credentials: 'include', body: form })
    if (!res.ok) throw new Error((await res.json()).detail ?? 'Falha no upload')
    return (await res.json()) as MediaAsset
  },
  deleteMedia: (id: number) => del(`/media/${id}`),

  autoSchedule: (body: {
    x_account_id: number
    candidate_ids?: number[]
    start_in_minutes?: number
    min_interval_minutes?: number
    max_interval_minutes?: number
    horizon_days?: number
    respect_window?: boolean
  }) =>
    post<{ scheduled: number; not_scheduled: number; first: string; last: string }>(
      '/scheduled-posts/auto',
      body,
    ),
  editCandidate: (id: number, text: string) => patch<Candidate>(`/content/${id}`, { text }),
  approve: (id: number) => post<Candidate>(`/content/${id}/approve`),
  reject: (id: number) => post<Candidate>(`/content/${id}/reject`),

  queue: (status?: string) => get<QueueItem[]>(`/scheduled-posts${status ? `?status=${status}` : ''}`),
  schedule: (body: { content_candidate_id: number; scheduled_at: string | null }) =>
    post('/scheduled-posts', body),
  reschedule: (id: number, body: { scheduled_at?: string; x_account_id?: number }) =>
    patch(`/scheduled-posts/${id}`, body),
  publishNow: (id: number) => post(`/scheduled-posts/${id}/publish-now`),
  cancelScheduled: (id: number) => del(`/scheduled-posts/${id}`),

  retweets: () => get<any[]>('/retweets'),
  createRetweets: (body: {
    source_tweet_id: string
    target_account_ids: number[]
    origin_x_account_id?: number | null
    delay_min_minutes: number
    delay_max_minutes: number
  }) => post<{ created: number }>('/retweets', body),
}
