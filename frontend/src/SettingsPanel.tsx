import { ConfigEditor } from './ConfigEditor'
import { GlossaryEditor } from './GlossaryEditor'
import './SettingsPanel.css'

export function SettingsPanel() {
  return (
    <div className="settings-panel">
      <ConfigEditor />
      <GlossaryEditor />
    </div>
  )
}
