/** Icones no estilo do X (24px, fill). Desenhados aqui — sem assets de marca de terceiros. */

type P = { size?: number; className?: string }
const base = (size = 24) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'currentColor',
  'aria-hidden': true,
})

export const IconHome = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 2.5 2.5 10v11.5h6.75v-6.5h5.5v6.5h6.75V10L12 2.5Zm7.5 8.44v9.06h-3.75v-6.5h-7.5v6.5H4.5v-9.06L12 4.6l7.5 6.34Z" />
  </svg>
)

export const IconSearch = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M10.25 3.5a6.75 6.75 0 1 0 4.29 11.96l4.5 4.5 1.42-1.42-4.5-4.5A6.75 6.75 0 0 0 10.25 3.5Zm-4.75 6.75a4.75 4.75 0 1 1 9.5 0 4.75 4.75 0 0 1-9.5 0Z" />
  </svg>
)

export const IconSparkle = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 2.5 13.8 8l5.7 1.8-5.7 1.9L12 17.5 10.2 11.7 4.5 9.8 10.2 8 12 2.5ZM18.5 15l.9 2.8 2.9.9-2.9.9-.9 2.9-.9-2.9-2.8-.9 2.8-.9.9-2.8ZM5 14l.7 2.2 2.3.8-2.3.7L5 20l-.7-2.3-2.3-.7 2.3-.8L5 14Z" />
  </svg>
)

export const IconCalendar = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M7 2v2H5.5A2.5 2.5 0 0 0 3 6.5v13A2.5 2.5 0 0 0 5.5 22h13a2.5 2.5 0 0 0 2.5-2.5v-13A2.5 2.5 0 0 0 18.5 4H17V2h-2v2H9V2H7Zm12 8v9.5a.5.5 0 0 1-.5.5h-13a.5.5 0 0 1-.5-.5V10h14Zm0-2H5V6.5a.5.5 0 0 1 .5-.5h13a.5.5 0 0 1 .5.5V8Z" />
  </svg>
)

export const IconProfile = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 3.5a4.25 4.25 0 1 0 0 8.5 4.25 4.25 0 0 0 0-8.5ZM9.75 7.75a2.25 2.25 0 1 1 4.5 0 2.25 2.25 0 0 1-4.5 0ZM12 13.5c-3.5 0-6.5 2.1-7.5 5.2L4.2 20h15.6l-.3-1.3c-1-3.1-4-5.2-7.5-5.2Zm-5 4.5c1-1.6 2.9-2.5 5-2.5s4 .9 5 2.5H7Z" />
  </svg>
)

export const IconChart = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M4 20V10.5h3.5V20H4Zm6.25 0V4h3.5v16h-3.5Zm6.25 0v-6.5H20V20h-3.5Z" />
  </svg>
)

export const IconSettings = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Zm-1.5 3.5a1.5 1.5 0 1 1 3 0 1.5 1.5 0 0 1-3 0Z" />
    <path d="m10.4 2-.5 2.2-1.3.5-1.9-1.2-2.6 2.6 1.2 1.9-.5 1.3L2.6 10v3.7l2.2.6.5 1.3-1.2 1.9 2.6 2.6 1.9-1.2 1.3.5.6 2.2h3.7l.5-2.2 1.3-.5 1.9 1.2 2.6-2.6-1.2-1.9.5-1.3 2.2-.5v-3.7l-2.2-.6-.5-1.3 1.2-1.9-2.6-2.6-1.9 1.2-1.3-.5L13.7 2h-3.3Zm1.2 2h1l.4 1.8 2.9 1.2 1.6-1 .7.7-1 1.6 1.2 2.9 1.8.4v1l-1.8.4-1.2 2.9 1 1.6-.7.7-1.6-1-2.9 1.2-.4 1.8h-1l-.4-1.8-2.9-1.2-1.6 1-.7-.7 1-1.6-1.2-2.9L4 12.5v-1l1.8-.4 1.2-2.9-1-1.6.7-.7 1.6 1 2.9-1.2.4-1.7Z" />
  </svg>
)

export const IconHeart = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 21s-7.5-4.7-7.5-9.75A4.25 4.25 0 0 1 12 8.4a4.25 4.25 0 0 1 7.5 2.85C19.5 16.3 12 21 12 21Z" />
  </svg>
)

export const IconRepost = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M4.5 9.5 8 6l1.4 1.4-1.6 1.6H16a2.5 2.5 0 0 1 2.5 2.5v2h-2v-2a.5.5 0 0 0-.5-.5H7.8l1.6 1.6L8 14.5l-3.5-3.5v-1.5Zm15 5L16 18l-1.4-1.4 1.6-1.6H8a2.5 2.5 0 0 1-2.5-2.5v-2h2v2c0 .3.2.5.5.5h8.2l-1.6-1.6L16 9.5l3.5 3.5v1.5Z" />
  </svg>
)

export const IconReply = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M3 5.5A2.5 2.5 0 0 1 5.5 3h13A2.5 2.5 0 0 1 21 5.5v9a2.5 2.5 0 0 1-2.5 2.5H11l-5 4v-4h-.5A2.5 2.5 0 0 1 3 14.5v-9Zm2.5-.5a.5.5 0 0 0-.5.5v9c0 .3.2.5.5.5H8v2l2.5-2h8a.5.5 0 0 0 .5-.5v-9a.5.5 0 0 0-.5-.5h-13Z" />
  </svg>
)

export const IconViews = ({ size = 16, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M4 20V9h3v11H4Zm6.5 0V4h3v16h-3ZM17 20v-7h3v7h-3Z" />
  </svg>
)

export const IconImage = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M3 5.5A2.5 2.5 0 0 1 5.5 3h13A2.5 2.5 0 0 1 21 5.5v13a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 18.5v-13ZM5.5 5a.5.5 0 0 0-.5.5v9.6l3.4-3.4 4 4 2.6-2.6 4 4V5.5a.5.5 0 0 0-.5-.5h-13Zm3 2a1.75 1.75 0 1 1 0 3.5 1.75 1.75 0 0 1 0-3.5Z" />
  </svg>
)

export const IconPencil = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M17.8 2.5 21.5 6.2 8.7 19H5v-3.7L17.8 2.5Zm0 2.8L7 16.1V17h.9L18.7 6.2l-.9-.9ZM3 21h18v2H3v-2Z" />
  </svg>
)

export const IconPlus = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M11 4h2v7h7v2h-7v7h-2v-7H4v-2h7V4Z" />
  </svg>
)

export const IconTrash = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-3 6h12l-1 12H7L6 9Zm2.2 2 .7 8h6.2l.7-8H8.2Z" />
  </svg>
)

export const IconBack = ({ size, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M20 11H7.8l5.6-5.6L12 4l-8 8 8 8 1.4-1.4L7.8 13H20v-2Z" />
  </svg>
)

export const IconRefresh = ({ size = 18, className }: P) => (
  <svg {...base(size)} className={className}>
    <path d="M12 4a8 8 0 0 1 7.4 5h-2.2A6 6 0 0 0 6 12H3l4-4 4 4H8a4 4 0 1 0 4-4V4Z" />
    <path d="M12 20a8 8 0 0 1-7.4-5h2.2A6 6 0 0 0 18 12h3l-4 4-4-4h3a4 4 0 1 1-4 4v4Z" />
  </svg>
)
