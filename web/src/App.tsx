import { NavLink, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from './lib/api'

// Các trang theo spec mục 10 - hiện thực dần từ M3
const PAGES = [
  { path: '/', label: 'Tổng quan' },
  { path: '/devices', label: 'Thiết bị' },
  { path: '/crop-profiles', label: 'Crop profile' },
  { path: '/alerts', label: 'Cảnh báo' },
  { path: '/models', label: 'Model & Thí nghiệm' },
  { path: '/settings/notifications', label: 'Thông báo' },
]

function Placeholder({ title }: { title: string }) {
  return (
    <section>
      <h2>{title}</h2>
      <p className="muted">Đang xây dựng.</p>
    </section>
  )
}

function HealthBadge() {
  const { data, isError } = useQuery({
    queryKey: ['health'],
    queryFn: () => api<{ status: string; db: boolean }>('/health'),
    refetchInterval: 15_000,
  })
  const ok = !isError && data?.status === 'ok'
  return <span className={`badge ${ok ? 'ok' : 'bad'}`}>{ok ? 'API online' : 'API offline'}</span>
}

export default function App() {
  return (
    <div className="layout">
      <header>
        <h1>🌱 GreenHub</h1>
        <HealthBadge />
      </header>
      <nav>
        {PAGES.map((p) => (
          <NavLink key={p.path} to={p.path} end>
            {p.label}
          </NavLink>
        ))}
      </nav>
      <main>
        <Routes>
          {PAGES.map((p) => (
            <Route key={p.path} path={p.path} element={<Placeholder title={p.label} />} />
          ))}
          <Route path="/zones/:id" element={<Placeholder title="Zone" />} />
          <Route path="/login" element={<Placeholder title="Đăng nhập" />} />
          <Route path="*" element={<Placeholder title="Không tìm thấy trang" />} />
        </Routes>
      </main>
    </div>
  )
}

