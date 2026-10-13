export default function Sidebar({collapsed,search,onSearchChange,currentPage,onSelectPage,regularChats,currentChatId,onNewChat,onChatOpen,onChatContext,onOpenSettings,projects=[],onProjectOpen,onNewProject}) {
 const shown=regularChats.filter(c=>currentPage!=='favorites'||c.pinned);
 return <aside className={`sidebar ${collapsed?'is-collapsed':''}`}>
 <button className="new-chat-button" onClick={onNewChat} title="Nová konverzace">＋ <span>Nová konverzace</span></button>
 <input className="sidebar-search" aria-label="Hledat konverzace" placeholder="Hledat konverzace…" value={search} onChange={e=>onSearchChange(e.target.value)}/>
 <span className="sidebar-label">Konverzace</span>
 <button className={`sidebar-nav-item ${currentPage==='history'?'is-active':''}`} onClick={()=>onSelectPage('history')}>☰ <span>Všechny konverzace</span></button>
 <button className={`sidebar-nav-item ${currentPage==='favorites'?'is-active':''}`} onClick={()=>onSelectPage('favorites')}>☆ <span>Oblíbené</span></button>
 <button className={`sidebar-nav-item ${currentPage==='trash'?'is-active':''}`} onClick={()=>onSelectPage('trash')}>♲ <span>Koš</span></button>
 <div className="sidebar-chat-list">{shown.map(c=><button key={c.id} className={`chat-list-item ${currentChatId===c.id?'is-active':''}`} onClick={()=>onChatOpen(c.id)} onContextMenu={e=>onChatContext(e,c)}>{c.title}</button>)}{!shown.length&&<p className="sidebar-empty">Žádné konverzace</p>}</div>
 <div className="project-heading"><button onClick={()=>onSelectPage('projects')}>Projekty</button><button onClick={onNewProject} aria-label="Nový projekt">＋</button></div>
 <div className="sidebar-projects">{projects.map(p=><button className="chat-list-item" key={p.id} onClick={()=>onProjectOpen(p)}>▱ {p.title}</button>)}</div>
 <div className="sidebar-footer"><button className="sidebar-nav-item" onClick={onOpenSettings}>⚙ <span>Nastavení</span></button></div>
 </aside>;
}
