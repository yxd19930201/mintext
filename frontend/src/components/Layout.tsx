import { Outlet, NavLink, useLocation } from 'react-router-dom'

const NAV = [
  {
    to: '/',
    label: '短剧项目',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
      </svg>
    ),
  },
  {
    to: '/novels',
    label: '小说创作',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
      </svg>
    ),
  },
  {
    to: '/conversion',
    label: '小说转短剧',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/>
      </svg>
    ),
  },
]

export default function Layout() {
  const location = useLocation()

  // Derive breadcrumb label from path
  const crumbs: string[] = []
  if (location.pathname === '/') crumbs.push('短剧项目列表')
  else if (location.pathname.includes('/episodes/')) crumbs.push('短剧项目', '分集', '剧本编辑器')
  else if (location.pathname.includes('/projects/')) crumbs.push('短剧项目', '分集列表')
  else if (location.pathname === '/novels') crumbs.push('小说列表')
  else if (location.pathname.includes('/chapters/')) crumbs.push('小说', '章节', '章节编辑器')
  else if (location.pathname.includes('/novels/')) crumbs.push('小说', '章节列表')
  else if (location.pathname === '/conversion') crumbs.push('小说转短剧')

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* Sidebar */}
      <aside style={{
        width: 220,
        background: 'var(--bg-2)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
      }}>
        {/* Logo */}
        <div style={{ padding: '20px 20px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 8,
              background: 'linear-gradient(135deg, var(--accent), #a78bfa)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 15, fontWeight: 800, color: '#fff', letterSpacing: '-0.05em',
            }}>M</div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 15, letterSpacing: '-0.02em' }}>minitext</div>
              <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 1 }}>短剧剧本生成</div>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ padding: '12px 10px', flex: 1 }}>
          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '0 10px', marginBottom: 6 }}>
            工作区
          </div>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '8px 10px',
                borderRadius: 'var(--radius-sm)',
                color: isActive ? 'var(--accent)' : 'var(--text-2)',
                background: isActive ? 'var(--accent-dim)' : 'transparent',
                fontWeight: isActive ? 600 : 400,
                fontSize: 13,
                transition: 'all 0.15s',
                marginBottom: 2,
              })}
            >
              {item.icon}
              {item.label}
            </NavLink>
          ))}

          <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-3)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '0 10px', marginBottom: 6, marginTop: 20 }}>
            工具
          </div>
          <NavLink
            to="/ai"
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 10px',
              borderRadius: 'var(--radius-sm)',
              color: isActive ? 'var(--accent)' : 'var(--text-2)',
              background: isActive ? 'var(--accent-dim)' : 'transparent',
              fontWeight: isActive ? 600 : 400,
              fontSize: 13,
              transition: 'all 0.15s',
              marginBottom: 2,
            })}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 8v4l3 3"/><circle cx="18" cy="6" r="3"/>
            </svg>
            AI 助手
            <span style={{ marginLeft: 'auto', fontSize: 10, background: 'var(--accent-dim)', color: 'var(--accent)', padding: '1px 6px', borderRadius: 10, fontWeight: 600 }}>预留</span>
          </NavLink>
          <NavLink
            to="/settings"
            style={({ isActive }) => ({
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 10px',
              borderRadius: 'var(--radius-sm)',
              color: isActive ? 'var(--accent)' : 'var(--text-2)',
              background: isActive ? 'var(--accent-dim)' : 'transparent',
              fontWeight: isActive ? 600 : 400,
              fontSize: 13,
              transition: 'all 0.15s',
            })}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/>
            </svg>
            设置
          </NavLink>
        </nav>

        {/* Footer */}
        <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)', fontSize: 11, color: 'var(--text-3)' }}>
          v0.1.0 · 开发模式
        </div>
      </aside>

      {/* Main */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Topbar */}
        <header style={{
          height: 52,
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          padding: '0 24px',
          gap: 8,
          background: 'var(--bg)',
          flexShrink: 0,
        }}>
          {crumbs.map((c, i) => (
            <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {i > 0 && <span style={{ color: 'var(--text-3)' }}>/</span>}
              <span style={{ color: i === crumbs.length - 1 ? 'var(--text)' : 'var(--text-3)', fontSize: 13 }}>{c}</span>
            </span>
          ))}
        </header>

        {/* Page content */}
        <main style={{ flex: 1, overflow: 'auto', padding: '28px 32px' }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
