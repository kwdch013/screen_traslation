using ScreenTranslation.Client.Api;

namespace ScreenTranslation.Client.ViewModels.Settings;

/// <summary>サーバーの値とそのrevision(GETの応答、PUT成功後の応答)。</summary>
public sealed record Revisioned<T>(ulong Revision, T Value);

/// <summary>用語辞書の1件。原文(source)は大文字小文字を区別せず一意。</summary>
public sealed record GlossaryEntry(string Source, string Target);

/// <summary>
/// サーバーの設定・用語辞書API(<c>/api/v1/settings</c>・<c>/api/v1/glossary</c>)の抽象。
/// 失敗は<see cref="ControlApiException"/>で伝える(分類のみ。サーバーの文言・トークン・URLは持たない)。
/// 実装は<see cref="Api.ServerSettingsApiClient"/>、試験では通信に依存しない代替を使う。
/// </summary>
public interface IServerSettingsApi
{
	Task<Revisioned<int>> GetCaptureFpsAsync(CancellationToken cancellationToken);

	/// <summary>取得したrevisionを条件に更新する。他者が先に更新していれば<see cref="ControlApiFailure.RevisionConflict"/>。</summary>
	Task<Revisioned<int>> UpdateCaptureFpsAsync(ulong revision, int captureFps, CancellationToken cancellationToken);

	Task<Revisioned<IReadOnlyList<GlossaryEntry>>> GetGlossaryAsync(CancellationToken cancellationToken);

	Task<Revisioned<IReadOnlyList<GlossaryEntry>>> UpdateGlossaryAsync(ulong revision, IReadOnlyList<GlossaryEntry> entries, CancellationToken cancellationToken);
}
