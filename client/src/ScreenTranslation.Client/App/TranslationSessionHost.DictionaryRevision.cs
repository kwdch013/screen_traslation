using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Client.App;

public sealed partial class TranslationSessionHost
{
	// 保存成功で知らされた最新の辞書revision(単調)。sessionの取得から有効化までの間の保存を、開始時に取りこぼさないために持つ
	private ulong knownDictionaryRevision;

	/// <summary>
	/// 辞書の保存成功(サーバーが返した新revision)を、実行中のsessionへ反映する。契約: 保存成功で新revisionを即時activeにし、
	/// 次に取得するフレームから新revisionを付ける。generationとframe_idは変えない。
	/// 待機中の画像は破棄しない(まだ送っていないため、新revisionで送ればよい。静止画面の再送もしない)。
	/// 送信済みの旧revisionのフレームの結果は、以降採用しない。更新の直前に旧revisionで組み立てたフレームは、通信部品の照合で取り下げられる(送信失敗として扱わない)。
	/// 停止中・破棄後・現在以下のrevisionでは何もせずfalse(逆行しない)。反映に失敗したら、旧revisionを送り続けないよう停止する。
	/// 設定(取得頻度)の保存は別系列のrevisionでsessionのrevisionを動かさないため、ここへ渡してはならない。
	/// </summary>
	public bool ApplyDictionaryRevision(ulong newDictionaryRevision)
	{
		if (newDictionaryRevision == 0) return false;
		lock (sync)
		{
			if (newDictionaryRevision > knownDictionaryRevision) knownDictionaryRevision = newDictionaryRevision;
			if (disposeTask is not null || !active || newDictionaryRevision <= dictionaryRevision) return false;
			try
			{
				// 下位部品へは、ロックを保持したまま短い同期呼び出しだけを行う(世代切替と同じ順序: sync→下位)
				pipeline.UpdateDictionaryRevision(newDictionaryRevision);
				transport.UpdateDictionaryRevision(newDictionaryRevision);
				overlayTracker.ChangeDictionaryRevision(newDictionaryRevision);
				dictionaryRevision = newDictionaryRevision;
				return true;
			}
			catch (InvalidOperationException)
			{
			}
		}
		Fail(OverlayClearReason.Disconnected, "辞書の更新を翻訳へ反映できなかったため停止しました。開始し直してください。");
		return false;
	}
}
