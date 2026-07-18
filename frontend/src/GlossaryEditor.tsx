import { useEffect, useState } from 'react'

import {
  deleteGlossaryTerm,
  getGlossary,
  type GlossaryTerm,
  registerGlossaryTerm,
} from './api'

export function GlossaryEditor() {
  const [terms, setTerms] = useState<GlossaryTerm[] | null>(null)
  const [source, setSource] = useState('')
  const [target, setTarget] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    void getGlossary()
      .then((loaded) => {
        if (active) setTerms(loaded)
      })
      .catch((reason: unknown) => {
        if (active) setError(messageOf(reason, '辞書を取得できませんでした。'))
      })
    return () => {
      active = false
    }
  }, [])

  const register = async () => {
    if (busy) return
    setError('')
    setNotice('')
    if (!source.trim() || !target.trim()) {
      setError('原文と訳文を入力してください。')
      return
    }
    setBusy(true)
    try {
      await registerGlossaryTerm(source, target)
      setTerms(await getGlossary())
      setSource('')
      setTarget('')
      setNotice('用語を登録しました。')
    } catch (reason) {
      setError(messageOf(reason, '用語を登録できませんでした。'))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (term: GlossaryTerm) => {
    if (busy || !window.confirm(`「${term.source}」を辞書から削除しますか？`)) return
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await deleteGlossaryTerm(term.source)
      setTerms(await getGlossary())
      setNotice('用語を削除しました。')
    } catch (reason) {
      setError(messageOf(reason, '用語を削除できませんでした。'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="settings-section glossary-section" aria-labelledby="glossary-heading" aria-label="辞書">
      <div className="section-heading">
        <div>
          <h2 id="glossary-heading">辞書</h2>
          <p>完全一致する原文と訳文を登録します。登録・削除は実行中の翻訳にも反映されます。</p>
        </div>
      </div>

      {error && <p className="form-message error" role="alert">{error}</p>}
      {notice && <p className="form-message success" role="status">{notice}</p>}

      <form className="glossary-form" onSubmit={(event) => { event.preventDefault(); void register() }}>
        <label>原文<input type="text" value={source} onChange={(event) => setSource(event.target.value)} /></label>
        <label>訳文<input type="text" value={target} onChange={(event) => setTarget(event.target.value)} /></label>
        <button type="submit" disabled={busy}>用語を登録</button>
      </form>

      {terms === null ? (
        <p className="settings-loading">辞書を読み込んでいます…</p>
      ) : terms.length === 0 ? (
        <p className="empty-glossary">登録済みの用語はありません。</p>
      ) : (
        <ul className="glossary-list">
          {terms.map((term) => (
            <li key={term.source}>
              <div><strong>{term.source}</strong><span>{term.target}</span></div>
              <button type="button" className="danger" aria-label={`${term.source} を削除`} disabled={busy} onClick={() => void remove(term)}>削除</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback
}
