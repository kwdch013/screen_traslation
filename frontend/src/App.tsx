import { useState } from 'react'

import './App.css'
import { useScreenCapture } from './useScreenCapture'

type Tab = 'preview' | 'subtitles' | 'settings'

const tabs: { id: Tab; label: string }[] = [
  { id: 'preview', label: 'プレビュー' },
  { id: 'subtitles', label: '字幕リスト' },
  { id: 'settings', label: '設定' },
]

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('preview')
  const capture = useScreenCapture()

  return (
    <main className="app-shell">
      <header className="app-header">
        <p className="eyebrow">SCREEN TRANSLATION</p>
        <h1>リアルタイム画面翻訳</h1>
        <p className="lead">翻訳する画面、ウィンドウ、またはブラウザタブを選択します。</p>
      </header>

      <nav className="tabs" aria-label="表示内容" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-controls={`${tab.id}-panel`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <section
        id="preview-panel"
        className="panel preview-panel"
        role="tabpanel"
        hidden={activeTab !== 'preview'}
      >
        <div className="controls">
          <button type="button" onClick={() => void capture.startSharing()} disabled={capture.startDisabled}>
            画面を選択して開始
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => void capture.reselectSharing()}
            disabled={capture.reselectDisabled}
          >
            画面を選び直す
          </button>
          <button
            type="button"
            className="danger"
            onClick={() => void capture.stopByUser()}
            disabled={capture.stopDisabled}
          >
            共有を停止
          </button>
        </div>
        <p className="status" role="status" aria-live="polite">
          {capture.statusText}
        </p>
        <video ref={capture.videoRef} autoPlay muted playsInline aria-label="共有画面のプレビュー" />
      </section>

      <section id="subtitles-panel" className="panel placeholder" role="tabpanel" hidden={activeTab !== 'subtitles'}>
        <h2>字幕リスト</h2>
        <p>翻訳結果の表示は段階6で追加します。</p>
      </section>

      <section id="settings-panel" className="panel placeholder" role="tabpanel" hidden={activeTab !== 'settings'}>
        <h2>設定</h2>
        <p>翻訳設定と辞書の編集は段階7で追加します。</p>
      </section>
    </main>
  )
}

export default App
