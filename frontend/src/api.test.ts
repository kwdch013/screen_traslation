import { describe, expect, it, vi } from 'vitest'

import { deleteGlossaryTerm, registerGlossaryTerm } from './api'

describe('辞書API', () => {
  it.each(['.', '..'])('URL正規化で削除不能になる原文「%s」を400として拒否する', async (source) => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await expect(registerGlossaryTerm(source, '訳')).rejects.toMatchObject({
      message: '原文に「.」または「..」は登録できません。',
      responseStatus: 400,
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each(['.', '..'])('削除APIでも原文「%s」を400として通信前に拒否する', async (source) => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await expect(deleteGlossaryTerm(source)).rejects.toMatchObject({ responseStatus: 400 })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
