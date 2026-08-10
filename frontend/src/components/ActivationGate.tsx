import { useEffect, useState } from 'react'
import { licenseApi, type LicenseStatus } from '../services/api/licenseApi'

export default function ActivationGate({ children }: { children: React.ReactNode }) {
  const [license, setLicense] = useState<LicenseStatus | null>(null)
  const [activationCode, setActivationCode] = useState('')
  const [loading, setLoading] = useState(true)
  const [activating, setActivating] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    licenseApi.status()
      .then(response => setLicense(response.data))
      .catch(error => setError('无法检查授权状态：' + String(error)))
      .finally(() => setLoading(false))
  }, [])

  const handleActivate = async () => {
    if (!activationCode.trim()) return
    setActivating(true)
    setError('')
    try {
      const response = await licenseApi.activate(activationCode.trim())
      setLicense(response.data)
    } catch (error: any) {
      setError(error?.response?.data?.detail || error?.message || '激活失败')
    } finally {
      setActivating(false)
    }
  }

  if (loading) {
    return <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-2)' }}>正在检查软件授权…</div>
  }
  if (license?.activated) return <>{children}</>

  const machineCode = license?.machine_code || ''
  return (
    <div style={{ height: '100%', display: 'grid', placeItems: 'center', padding: 24, background: 'radial-gradient(circle at 50% 18%, rgba(0,104,214,.18) 0, var(--bg) 48%)' }}>
      <div className="card" style={{ width: 560, maxWidth: '96vw', padding: 28, boxShadow: '0 28px 90px rgba(43,67,92,.20)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 22 }}>
          <div style={{ width: 48, height: 48, borderRadius: 14, display: 'grid', placeItems: 'center', background: 'linear-gradient(145deg, #53b6ff, var(--accent) 55%, #0067d8)', boxShadow: '0 8px 24px rgba(10,132,255,.28)', fontWeight: 800, fontSize: 22 }}>M</div>
          <div>
            <div style={{ fontSize: 20, fontWeight: 800 }}>激活 Mintext</div>
            <div style={{ color: 'var(--text-2)', fontSize: 13 }}>本软件采用一机一码限时离线授权</div>
          </div>
        </div>

        <label className="label">本机机器码</label>
        <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
          <input className="input mono" value={machineCode} readOnly />
          <button className="btn btn-ghost" onClick={() => navigator.clipboard.writeText(machineCode)}>复制机器码</button>
        </div>

        <div style={{ padding: 12, borderRadius: 12, background: 'var(--bg-3)', color: 'var(--text-2)', fontSize: 12, marginBottom: 18 }}>
          将机器码发送给卖家购买限时激活码。激活码仅限当前电脑使用，到期后需要续费并输入新的激活码。
        </div>

        <label className="label">激活码</label>
        <textarea
          className="textarea mono"
          rows={5}
          value={activationCode}
          onChange={event => setActivationCode(event.target.value)}
          placeholder="请粘贴卖家发送的激活码…"
        />
        {(error || license?.message) && <div style={{ color: 'var(--danger)', marginTop: 10, fontSize: 13 }}>{error || license?.message}</div>}
        <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center', marginTop: 16 }} onClick={handleActivate} disabled={activating || !activationCode.trim()}>
          {activating ? '正在激活…' : '立即激活'}
        </button>
      </div>
    </div>
  )
}
