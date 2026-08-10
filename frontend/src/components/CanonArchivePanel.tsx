import { useMemo, useState } from 'react'
import {
  novelAiApi,
  type CanonArchive,
  type CanonArchiveSection,
  type CanonRecord,
} from '../services/api/novelAiApi'

type TabKey = 'people' | 'assets' | 'transactions' | 'items' | 'facts' | 'timeline' | 'threads' | 'events'

interface Props {
  novelId: number
  archive: CanonArchive
  onChange: (archive: CanonArchive) => void
}

interface EditorState {
  section: CanonArchiveSection
  index: number | null
  title: string
  value: string
  wholeObject?: boolean
}

const sectionNames: Record<CanonArchiveSection, string> = {
  protagonist: '主角状态',
  characters: '人物图谱',
  events: '关键事件',
  supporting_characters: '配角档案',
  relationship_states: '人物关系',
  dialogue_profiles: '称呼与语言规则',
  asset_accounts: '资产账本',
  transaction_ledger: '交易流水',
  item_custody: '物品流转',
  timeline: '时间线',
  knowledge_boundaries: '信息边界',
  commitments: '承诺事项',
  plot_threads: '剧情线索',
  canon_facts: '不可逆事实',
}

const fieldNames: Record<string, string> = {
  chapter: '章节', as_of_chapter: '截至章节', effective_chapter: '生效章节',
  name: '名称', canonical_name: '标准姓名', owner: '所有人', entity: '主体',
  type: '类型', status: '状态', description: '说明', evidence: '正文依据',
  fact: '事实', cause: '原因', importance: '重要程度', cash: '现金',
  total_assets: '总资产', amount: '金额', cash_change: '现金变化',
  asset_change: '资产变化', counterparty: '交易对方', item: '物品',
  holder: '当前持有人', new_holder: '新持有人', location: '位置',
  origin: '出发地', destination: '目的地', transport: '交通方式', time: '时间',
  event: '事件', content: '内容', promise: '承诺', deadline: '期限',
  relationship_to_protagonist: '与主角关系', character_a: '人物A', character_b: '人物B',
  relation: '关系', role: '角色', title: '标题', current_goal: '当前目标',
}

function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function recordTitle(section: CanonArchiveSection, record: CanonRecord, index: number): string {
  const chapter = record.chapter ?? record.as_of_chapter ?? record.effective_chapter
  const prefix = chapter !== undefined && chapter !== '' ? `第${chapter}章 · ` : ''
  const candidates: Record<CanonArchiveSection, unknown[]> = {
    protagonist: [record.name, record.canonical_name, '主角'],
    characters: [record.name, record.role],
    events: [record.title, record.event],
    supporting_characters: [record.canonical_name, record.name],
    relationship_states: [record.character_a && record.character_b ? `${record.character_a} ↔ ${record.character_b}` : '', record.status],
    dialogue_profiles: [record.canonical_name, record.name],
    asset_accounts: [record.account, record.name, record.type, record.owner],
    transaction_ledger: [record.description, record.type, record.counterparty],
    item_custody: [record.item, record.name, record.description],
    timeline: [record.event, record.location, record.destination],
    knowledge_boundaries: [record.character, record.fact, record.knowledge],
    commitments: [record.content, record.promise, record.owner],
    plot_threads: [record.thread, record.content, record.id],
    canon_facts: [record.fact, record.type],
  }
  const found = candidates[section].find(value => text(value).trim())
  const value = text(found).replace(/\s+/g, ' ').trim()
  return prefix + (value ? (value.length > 60 ? `${value.slice(0, 60)}…` : value) : `${sectionNames[section]} ${index + 1}`)
}

function summaryText(record: CanonRecord): string {
  const keys = ['description', 'fact', 'evidence', 'event', 'content', 'promise', 'relationship_to_protagonist', 'current_goal', 'identity']
  for (const key of keys) {
    const value = text(record[key]).replace(/\s+/g, ' ').trim()
    if (value) return value.length > 180 ? `${value.slice(0, 180)}…` : value
  }
  return ''
}

function templateFor(section: CanonArchiveSection, chapter: number): CanonRecord {
  const templates: Partial<Record<CanonArchiveSection, CanonRecord>> = {
    characters: { name: '', role: '', description: '', relations: [] },
    events: { chapter, title: '', description: '', related_characters: [] },
    supporting_characters: { name: '', canonical_name: '', identity: '', relationship_to_protagonist: '', status: 'active', last_seen_chapter: chapter },
    relationship_states: { character_a: '', character_b: '', status: '', effective_chapter: chapter, reason: '' },
    asset_accounts: { chapter, as_of_chapter: chapter, owner: '', type: 'cash_snapshot', cash: 0, assets: [], debts: [], reconciled: true },
    transaction_ledger: { chapter, type: '', amount: 0, cash_change: 0, counterparty: '', description: '', evidence: '', personal_cash_effect: true, reconciled: true },
    item_custody: { chapter, item: '', holder: '', new_holder: '', location: '', status: '', evidence: '' },
    timeline: { chapter, time: '', origin: '', destination: '', transport: '', location: '', event: '' },
    knowledge_boundaries: { chapter, character: '', knowledge: '', status: 'known', evidence: '' },
    commitments: { chapter, owner: '', content: '', deadline: '', status: 'open', evidence: '' },
    plot_threads: { chapter, id: '', thread: '', content: '', status: 'open' },
    canon_facts: { chapter, type: 'event', fact: '', cause: '', importance: 'normal', status: 'active' },
  }
  return templates[section] || {}
}

function metric(record: CanonRecord, key: string) {
  const value = record[key]
  if (value === undefined || value === null || value === '' || typeof value === 'object') return null
  return (
    <span key={key} style={{ padding: '3px 8px', borderRadius: 999, background: 'var(--accent-dim)', color: 'var(--accent-hover)', fontSize: 11 }}>
      {fieldNames[key] || key}：{String(value)}
    </span>
  )
}

export default function CanonArchivePanel({ novelId, archive, onChange }: Props) {
  const [tab, setTab] = useState<TabKey>('people')
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [saving, setSaving] = useState(false)

  const tabs = useMemo(() => [
    { key: 'people' as const, label: '人物状态', count: archive.supporting_characters.length + archive.relationship_states.length },
    { key: 'assets' as const, label: '资产账本', count: archive.asset_accounts.length },
    { key: 'transactions' as const, label: '交易流水', count: archive.transaction_ledger.length },
    { key: 'items' as const, label: '物品流转', count: archive.item_custody.length },
    { key: 'facts' as const, label: '不可逆事实', count: archive.canon_facts.length },
    { key: 'timeline' as const, label: '时间线', count: archive.timeline.length },
    { key: 'threads' as const, label: '承诺与线索', count: archive.commitments.length + archive.plot_threads.length },
    { key: 'events' as const, label: '事件图谱', count: archive.events.length },
  ], [archive])

  const listFor = (section: CanonArchiveSection): CanonRecord[] => {
    const value = archive[section]
    return Array.isArray(value) ? value as CanonRecord[] : []
  }

  const startEdit = (section: CanonArchiveSection, record: CanonRecord, index: number | null) => {
    setEditor({
      section,
      index,
      title: `${index === null ? '新增' : '编辑'}${sectionNames[section]}`,
      value: JSON.stringify(record, null, 2),
    })
  }

  const startObjectEdit = (section: 'protagonist' | 'dialogue_profiles') => {
    setEditor({
      section,
      index: null,
      title: `编辑${sectionNames[section]}`,
      value: JSON.stringify(archive[section] || {}, null, 2),
      wholeObject: true,
    })
  }

  const saveEditor = async () => {
    if (!editor) return
    let parsed: unknown
    try {
      parsed = JSON.parse(editor.value)
    } catch (error) {
      alert(`JSON格式错误：${String(error)}`)
      return
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      alert('单条档案必须是一个 JSON 对象')
      return
    }
    setSaving(true)
    try {
      let payload: CanonRecord | CanonRecord[] | Record<string, CanonRecord>
      if (editor.wholeObject) {
        payload = parsed as CanonRecord
      } else {
        const current = [...listFor(editor.section)]
        if (editor.index === null) current.push(parsed as CanonRecord)
        else current[editor.index] = parsed as CanonRecord
        payload = current
      }
      const response = await novelAiApi.updateArchiveSection(novelId, editor.section, payload)
      if (response.data) onChange(response.data)
      setEditor(null)
    } catch (error: any) {
      const detail = error?.response?.data?.detail
      alert(`保存失败：${typeof detail === 'string' ? detail : error?.message || String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const removeRecord = async (section: CanonArchiveSection, index: number) => {
    if (!confirm(`确定删除这条${sectionNames[section]}吗？删除后会影响后续章节生成参考。`)) return
    setSaving(true)
    try {
      const next = listFor(section).filter((_, itemIndex) => itemIndex !== index)
      const response = await novelAiApi.updateArchiveSection(novelId, section, next)
      if (response.data) onChange(response.data)
    } catch (error: any) {
      alert(`删除失败：${error?.response?.data?.detail || error?.message || String(error)}`)
    } finally {
      setSaving(false)
    }
  }

  const Section = ({ section, title, description, allowAdd = true }: { section: CanonArchiveSection; title?: string; description?: string; allowAdd?: boolean }) => {
    const allItems = listFor(section)
    const keyword = search.trim().toLowerCase()
    const items = allItems
      .map((record, originalIndex) => ({ record, originalIndex }))
      .filter(({ record }) => !keyword || JSON.stringify(record).toLowerCase().includes(keyword))
    return (
      <div style={{ marginTop: 18 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 10 }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700 }}>{title || sectionNames[section]} <span style={{ color: 'var(--text-3)', fontWeight: 500 }}>({allItems.length})</span></div>
            {description && <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>{description}</div>}
          </div>
          {allowAdd && <button className="btn btn-sm" disabled={saving} onClick={() => startEdit(section, templateFor(section, archive.current_chapter), null)}>＋ 新增</button>}
        </div>
        {items.length === 0 ? (
          <div style={{ padding: '26px 14px', textAlign: 'center', color: 'var(--text-3)', border: '1px dashed var(--border)', borderRadius: 8 }}>
            {keyword ? '没有匹配的档案' : `暂无${title || sectionNames[section]}`}
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 8 }}>
            {items.map(({ record, originalIndex }) => {
              const key = `${section}:${originalIndex}`
              const isExpanded = expanded === key
              const summary = summaryText(record)
              return (
                <div key={key} style={{ background: 'rgba(255,255,255,.90)', border: '.5px solid var(--border)', borderRadius: 12, padding: '12px 14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div style={{ fontWeight: 650, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{recordTitle(section, record, originalIndex)}</div>
                      {summary && <div style={{ marginTop: 5, color: 'var(--text-2)', fontSize: 12, lineHeight: 1.65 }}>{summary}</div>}
                      <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                        {['chapter', 'type', 'status', 'cash', 'total_assets', 'amount', 'cash_change', 'holder', 'new_holder', 'location'].map(field => metric(record, field))}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button className="btn btn-sm" onClick={() => setExpanded(isExpanded ? null : key)}>{isExpanded ? '收起' : '详情'}</button>
                      <button className="btn btn-sm" disabled={saving} onClick={() => startEdit(section, record, originalIndex)}>编辑</button>
                      <button className="btn btn-sm btn-danger" disabled={saving} onClick={() => removeRecord(section, originalIndex)}>删除</button>
                    </div>
                  </div>
                  {isExpanded && (
                    <pre style={{ marginTop: 12, padding: 12, borderRadius: 10, background: 'rgba(247,250,254,.90)', color: 'var(--text-2)', font: '12px/1.65 var(--mono)', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', border: '.5px solid var(--border-soft)' }}>
                      {JSON.stringify(record, null, 2)}
                    </pre>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  const protagonist = archive.protagonist || {}
  const statCards = [
    ['当前章节', `第 ${archive.current_chapter || 0} 章`],
    ['当前时空', archive.time_place || '未记录'],
    ['主角现金', text(protagonist.cash) || '未记录'],
    ['总资产', text(protagonist.total_assets) || text(protagonist.wealth) || '未记录'],
  ]

  return (
    <div style={{ marginTop: 16, border: '.5px solid var(--border)', borderRadius: 16, overflow: 'hidden', background: 'rgba(255,255,255,.90)', backdropFilter: 'blur(26px) saturate(165%)' }}>
      <div style={{ padding: 18, borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 10 }}>
          {statCards.map(([label, value]) => (
            <div key={label} style={{ padding: '11px 12px', background: 'rgba(10,132,255,.08)', border: '.5px solid rgba(10,132,255,.2)', borderRadius: 12, minWidth: 0 }}>
              <div style={{ color: 'var(--text-3)', fontSize: 11 }}>{label}</div>
              <div title={value} style={{ marginTop: 3, color: 'var(--text)', fontWeight: 650, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{value}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '12px 16px 0', display: 'flex', flexWrap: 'wrap', gap: 7 }}>
        {tabs.map(item => (
          <button
            key={item.key}
            onClick={() => setTab(item.key)}
            style={{ border: `.5px solid ${tab === item.key ? 'var(--accent)' : 'var(--border)'}`, background: tab === item.key ? 'var(--accent-dim)' : 'var(--bg-3)', color: tab === item.key ? 'var(--accent-hover)' : 'var(--text-2)', borderRadius: 10, padding: '7px 10px', cursor: 'pointer', fontSize: 12 }}
          >
            {item.label} <span style={{ opacity: .7 }}>({item.count})</span>
          </button>
        ))}
      </div>

      <div style={{ padding: 16 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input className="input" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索姓名、章节、金额、物品或事实内容…" />
          {search && <button className="btn btn-sm" onClick={() => setSearch('')}>清除</button>}
        </div>

        {tab === 'people' && <>
          <div style={{ marginTop: 18, padding: 14, border: '.5px solid rgba(10,132,255,.28)', borderRadius: 12, background: 'rgba(10,132,255,.07)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
              <div>
                <div style={{ fontWeight: 700 }}>{text(protagonist.name || protagonist.canonical_name) || '主角状态'}</div>
                <div style={{ color: 'var(--text-2)', fontSize: 12, marginTop: 4 }}>{text(protagonist.identity) || '身份未记录'} · {text(protagonist.location) || '位置未记录'}</div>
                <div style={{ color: 'var(--text-2)', fontSize: 12, marginTop: 4 }}>{text(protagonist.current_goal)}</div>
              </div>
              <button className="btn btn-sm" onClick={() => startObjectEdit('protagonist')}>编辑主角状态</button>
            </div>
          </div>
          <Section section="supporting_characters" description="身份、位置、目标、知识边界和与主角的关系" />
          <Section section="relationship_states" description="双向关系、关系状态、生效章节与变化原因" />
          <Section section="characters" title="人物关系图节点" description="用于图谱展示的人物、角色说明和关系边" />
          <div style={{ marginTop: 18, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 14, border: '1px solid var(--border)', borderRadius: 8 }}>
            <div><div style={{ fontWeight: 700 }}>称呼与语言规则</div><div style={{ color: 'var(--text-2)', fontSize: 12 }}>记录每个角色的语言能力、口吻以及对其他人物的称呼</div></div>
            <button className="btn btn-sm" onClick={() => startObjectEdit('dialogue_profiles')}>编辑全部规则</button>
          </div>
        </>}
        {tab === 'assets' && <Section section="asset_accounts" description="现金、存款、持仓、库存、负债以及每章资产快照" />}
        {tab === 'transactions' && <Section section="transaction_ledger" description="主角本人逐笔收入、支出、借还、买卖和费用；公司资金应标记为不影响个人现金" />}
        {tab === 'items' && <Section section="item_custody" description="关键物品的持有人、取得或移交章节、位置和状态" />}
        {tab === 'facts' && <Section section="canon_facts" description="后续章节不得无故推翻的正式正史事实；修改会直接影响AI续写" />}
        {tab === 'timeline' && <>
          <Section section="timeline" description="时间、地点、交通和行动顺序" />
          <Section section="knowledge_boundaries" description="谁在什么章节知道或不知道什么，防止角色获得不应知道的信息" />
        </>}
        {tab === 'threads' && <>
          <Section section="commitments" description="承诺、债务、期限和履约状态" />
          <Section section="plot_threads" description="正在推进、等待回收或已经结清的剧情线索" />
        </>}
        {tab === 'events' && <Section section="events" description="传统图谱中的关键事件，可用于浏览故事发展" />}
      </div>

      {editor && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(49,61,76,.28)', backdropFilter: 'blur(12px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
          <div style={{ width: 'min(760px,92vw)', maxHeight: '88vh', display: 'flex', flexDirection: 'column', background: 'rgba(255,255,255,.90)', backdropFilter: 'blur(30px) saturate(170%)', border: '.5px solid var(--border)', borderRadius: 18, boxShadow: 'var(--shadow)' }}>
            <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div><div style={{ fontWeight: 750, fontSize: 16 }}>{editor.title}</div><div style={{ color: 'var(--text-2)', fontSize: 12, marginTop: 2 }}>保存后立即成为后续大纲和正文生成的正式参考</div></div>
              <button className="btn btn-sm" onClick={() => setEditor(null)} disabled={saving}>关闭</button>
            </div>
            <div style={{ padding: 18, overflow: 'auto' }}>
              <textarea className="textarea mono" value={editor.value} onChange={event => setEditor({ ...editor, value: event.target.value })} style={{ minHeight: 430, resize: 'vertical', lineHeight: 1.55 }} spellCheck={false} />
              <div style={{ marginTop: 8, color: 'var(--text-3)', fontSize: 12 }}>可修改已有字段，也可添加新字段；必须保持合法 JSON，对象的键和字符串需要使用双引号。</div>
            </div>
            <div style={{ padding: '13px 18px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <button className="btn" onClick={() => setEditor(null)} disabled={saving}>取消</button>
              <button className="btn btn-primary" onClick={saveEditor} disabled={saving}>{saving ? '保存中…' : '保存到正史档案'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
