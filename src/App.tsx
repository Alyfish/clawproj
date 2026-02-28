import React, { useState } from 'react'
import TextBubble from './components/TextBubble'
import { SCOPES, getScope } from './lib/permissions'

function PermissionRequest({scope}:{scope:typeof SCOPES[number]}){
  return (
    <div className="card">
      <strong>Permission Required:</strong> {scope.label} <span>({scope.risk})</span>
      <div className="hint">{scope.description}</div>
      <button>Allow</button>
      <button>Not now</button>
    </div>
  )
}

export default function App(){
  const [perm, setPerm] = useState<string[]>([])
  const [yaml, setYaml] = useState<string>(`agent:
  name: Morning Email Triage
  schedule: "0 8 * * *"
  steps:
    - tool: gmail.list_urgent
      params: { max: 5 }`)
  const grant = (id:string)=>{
    setPerm([...perm, id])
  }
  return (
    <div className="app">
      <TextBubble text="Welcome to Kelp AI Web MVP"/>
      <div className="card"><pre style={{margin:0}}>{yaml}</pre></div>
      { /* Demo: show a permission card for gmail if not granted */ }
      { perm.includes('gmail.read')? null : <PermissionRequest scope={SCOPES.find(s=>s.id==='gmail.read')!} /> }
      <div className="card"><div className="hint">Mock UI: 3 demo flows would render here as JSON-driven cards.</div></div>
    </div>
  )
}
