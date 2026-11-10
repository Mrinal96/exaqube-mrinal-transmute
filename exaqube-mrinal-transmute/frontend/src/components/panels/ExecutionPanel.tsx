import { ChevronDown, ChevronUp, Circle, Clock3, Coins, TerminalSquare } from 'lucide-react'

interface ExecutionPanelProps { expanded: boolean; onToggle: () => void }

export function ExecutionPanel({ expanded, onToggle }: ExecutionPanelProps) {
  return <section className={`execution-panel ${expanded ? 'expanded' : ''}`}><button className="execution-toggle" onClick={onToggle}><div className="execution-title"><TerminalSquare size={15} /><strong>Execution</strong><span className="idle-pill"><Circle size={7} /> Idle</span></div><div className="execution-summary"><span><Clock3 size={13} /> —</span><span><Coins size={13} /> $0.00</span>{expanded ? <ChevronDown size={15} /> : <ChevronUp size={15} />}</div></button>{expanded && <div className="execution-body"><div className="log-tabs"><button className="selected">Activity log</button><button>Run history <span>0</span></button></div><div className="log-empty"><div className="terminal-glyph">$</div><span>Execution events will appear here</span><small>Run a workflow to see progress and output details.</small></div></div>}</section>
}

