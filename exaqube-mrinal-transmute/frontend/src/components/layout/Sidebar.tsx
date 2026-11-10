import { useState } from 'react'
import { Box, ChevronDown, ChevronLeft, CircleHelp, Clock3, Command, FilePlus2, FolderKanban, Settings2, Sparkles } from 'lucide-react'

interface SidebarProps { onNew: () => void }

export function Sidebar({ onNew }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false)
  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="brand-row"><div className="brand-mark"><Box size={17} strokeWidth={2.1} /></div>{!collapsed && <><span className="brand-name">transmute</span><button className="collapse-button" onClick={() => setCollapsed(true)} aria-label="Collapse sidebar"><ChevronLeft size={16} /></button></>}</div>
      {collapsed && <button className="collapse-button expand" onClick={() => setCollapsed(false)} aria-label="Expand sidebar"><ChevronLeft size={16} /></button>}
      <button className="new-workflow" onClick={onNew}><FilePlus2 size={16} />{!collapsed && <><span>New workflow</span><kbd>⌘ K</kbd></>}</button>
      {!collapsed && <>
        <div className="side-section"><div className="side-label">WORKSPACE <ChevronDown size={13} /></div><a className="side-link active"><FolderKanban size={16} /><span>All workflows</span><b>3</b></a><a className="side-link"><Clock3 size={16} /><span>Recent</span></a></div>
        <div className="side-section recents"><div className="side-label">SAMPLE WORKFLOWS</div><button className="recent-item"><i className="recent-dot teal" />Quarterly review deck</button><button className="recent-item"><i className="recent-dot purple" />Product launch brief</button><button className="recent-item"><i className="recent-dot orange" />Customer research</button></div>
        <div className="sidebar-bottom"><div className="usage-card"><div className="usage-title"><Sparkles size={13} /> Local preview</div><div className="usage-line"><span>Workflow runs</span><span>Not enabled</span></div><div className="usage-bar"><i /></div><button>Usage details <span>↗</span></button></div><a className="side-link"><Settings2 size={16} /><span>Settings</span></a><a className="side-link"><CircleHelp size={16} /><span>Help center</span></a><div className="profile"><div className="avatar">M</div><div className="profile-copy"><strong>Mrinal Sharma</strong><span>Personal workspace</span></div><button className="icon-button"><Command size={15} /></button></div></div>
      </>}
      {collapsed && <div className="collapsed-icons"><FolderKanban size={18} /><Clock3 size={18} /><Settings2 size={18} /></div>}
    </aside>
  )
}


