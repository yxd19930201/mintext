import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { useState } from 'react'
import feedbackWechat from '../assets/feedback-wechat.jpg'

const NAV = [
  {
    to: '/',
    label: '作品中心',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
      </svg>
    ),
  },
  {
    to: '/novels',
    label: '小说书架',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
      </svg>
    ),
  },
  {
    to: '/projects',
    label: '短剧工坊',
    icon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
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
  const [showFeedback, setShowFeedback] = useState(false)

  // Derive breadcrumb label from path
  const crumbs: string[] = []
  if (location.pathname === '/') crumbs.push('作品中心')
  else if (location.pathname === '/projects') crumbs.push('作品中心', '短剧工坊')
  else if (location.pathname.includes('/episodes/')) crumbs.push('短剧项目', '分集', '剧本编辑器')
  else if (location.pathname.includes('/projects/')) crumbs.push('短剧项目', '分集列表')
  else if (location.pathname === '/novels') crumbs.push('作品中心', '小说书架')
  else if (location.pathname.includes('/chapters/')) crumbs.push('小说', '章节', '章节编辑器')
  else if (location.pathname.includes('/novels/')) crumbs.push('小说', '章节列表')
  else if (location.pathname === '/conversion') crumbs.push('小说转短剧')
  else if (location.pathname === '/ai') crumbs.push('AI 助手', '小说体检')

  return (
    <div className="ios-shell">
      {/* Sidebar */}
      <aside className="ios-sidebar">
        {/* Logo */}
        <div className="ios-brand">
          <div className="ios-brand-row">
            <div className="ios-brand-mark">玉</div>
            <div><div className="ios-brand-name">青玉书房</div><div className="ios-brand-subtitle">MINITEXT STUDIO</div></div>
          </div>
        </div>

        {/* Nav */}
        <nav className="ios-nav">
          <div className="ios-nav-section-label">
            作品
          </div>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `ios-nav-item${isActive ? ' active' : ''}${item.to === '/novels' || item.to === '/projects' ? ' is-child' : ''}`}
            >
              {item.icon}
              {item.label}
            </NavLink>
          ))}

          <div className="ios-nav-section-label ios-nav-section-spaced">
            智能工具
          </div>
          <NavLink
            to="/ai"
            className={({ isActive }) => `ios-nav-item${isActive ? ' active' : ''}`}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 8v4l3 3"/><circle cx="18" cy="6" r="3"/>
            </svg>
            AI 助手
            <span className="ios-nav-badge">新</span>
          </NavLink>
          <NavLink
            to="/settings"
            className={({ isActive }) => `ios-nav-item${isActive ? ' active' : ''}`}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/>
            </svg>
            设置
          </NavLink>
        </nav>

        {/* Footer */}
        <div className="ios-sidebar-footer">
          v0.1.0 · 开发模式
        </div>
      </aside>

      {/* Main */}
      <div className="ios-main-column">
        {/* Topbar */}
        <header className="ios-topbar">
          {crumbs.map((c, i) => (
            <span key={i} className="ios-crumb-group">
              {i > 0 && <span className="ios-crumb-separator">›</span>}
              <span className={i === crumbs.length - 1 ? 'ios-crumb current' : 'ios-crumb'}>{c}</span>
            </span>
          ))}
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setShowFeedback(true)}
            style={{ marginLeft: 'auto' }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/>
              <path d="M8 9h8M8 13h5"/>
            </svg>
            联系作者 / 问题反馈
          </button>
        </header>

        {/* Page content */}
        <main className="ios-page-content">
          <Outlet />
        </main>
      </div>

      {showFeedback && (
        <div
          className="ios-modal-overlay"
          role="dialog"
          aria-modal="true"
          onClick={() => setShowFeedback(false)}
        >
          <div
            className="card ios-feedback-dialog"
            onClick={event => event.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 16 }}>联系作者 / 问题反馈</div>
                <div style={{ color: 'var(--text-2)', fontSize: 12, marginTop: 4 }}>微信扫码添加好友，请备注“Mintext反馈”</div>
              </div>
              <button className="btn btn-ghost btn-sm ios-close-button" onClick={() => setShowFeedback(false)} aria-label="关闭">×</button>
            </div>
            <img
              src={feedbackWechat}
              alt="作者微信二维码"
              className="ios-feedback-image"
            />
          </div>
        </div>
      )}
    </div>
  )
}
