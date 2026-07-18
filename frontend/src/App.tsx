import { useState } from 'react'

import './App.css'
import { SubtitleList } from './SubtitleList'
import { TranslationPreview } from './TranslationPreview'
import { useScreenCapture } from './useScreenCapture'
import { useTranslationEvents } from './useTranslationEvents'

type Tab = 'preview' | 'subtitles' | 'settings'

const tabs: { id: Tab; label: string }[] = [
  { id: 'preview', label: 'プレビュー' },
  { id: 'subtitles', label: '字幕リスト' },
  { id: 'settings', label: '設定' },
]

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('preview')
  const capture = useScreenCapture()
  const translation = useTranslationEvents()

  const startSharing = () => {
    translation.clearForSessionChange()
    void capture.startSharing()
  }

  const reselectSharing = () => {
    translation.clearForSessionChange()
    void capture.reselectSharing()
  }

  const stopSharing = () => {
    translation.clearForSessionChange()
    void capture.stopByUser()
  }

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

      {translation.connection === 'reconnecting' && (
        <p className="event-connection" aria-live="polite">翻訳結果を再接続中です。</p>
      )}

      <section
        id="preview-panel"
        className="panel preview-panel"
        role="tabpanel"
        hidden={activeTab !== 'preview'}
      >
        <div className="controls">
          <button type="button" onClick={startSharing} disabled={capture.startDisabled}>
            画面を選択して開始
          </button>
          <button
            type="button"
            className="secondary"
            onClick={reselectSharing}
            disabled={capture.reselectDisabled}
          >
            画面を選び直す
          </button>
          <button
            type="button"
            className="danger"
            onClick={stopSharing}
            disabled={capture.stopDisabled}
          >
            共有を停止
          </button>
        </div>
        <p className="status" role="status" aria-live="polite">
          {capture.statusText}
        </p>
        <TranslationPreview videoRef={capture.videoRef} result={translation.currentResult} />
      </section>

      <section id="subtitles-panel" className="panel" role="tabpanel" hidden={activeTab !== 'subtitles'}>
        <SubtitleList history={translation.history} />
      </section>

      <section id="settings-panel" className="panel placeholder" role="tabpanel" hidden={activeTab !== 'settings'}>
        <h2>設定</h2>
        <p>翻訳設定と辞書の編集は段階7で追加します。</p>
      </section>
    </main>
  )
}

export default App
