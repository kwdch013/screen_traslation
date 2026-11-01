using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.ViewModels.Settings;
using Xunit;

namespace ScreenTranslation.Client.IntegrationTests;

/// <summary>
/// 本物のサーバーアプリに対する、設定・用語辞書の編集の往復(GET→編集→If-Match付きPUT→再GET)とrevision競合・権限不足。
/// 製品と同じ通信部品(ServerSettingsApiClient)と編集モデルを使う。端末の見た目・保護保存は範囲外(Owner実機手順)。
/// </summary>
[Trait("Category", "RealServerIntegration")]
public sealed class RealServerSettingsTests
{
	private static readonly TimeSpan Watchdog = TimeSpan.FromSeconds(60);

	private static RealServerEnvironment Env => RealServerEnvironment.FromEnvironment()!;

	private static RealServerClient Client(string owner) => new(Env.SettingsUrl ?? Env.ReadyUrl, Env.Token(owner), Env.CaPem);

	[RealServerFact]
	public async Task CaptureFps_IsSavedWithTheLoadedRevision_AndAStaleEditorIsToldToReloadWithoutLosingItsEdit()
	{
		using var admin = Client("admin");
		using var first = new TranslationSettingsViewModel(admin.ServerSettings);
		using var second = new TranslationSettingsViewModel(admin.ServerSettings);
		Assert.Equal(EditorOutcome.Completed, await first.LoadAsync().WaitAsync(Watchdog));
		Assert.Equal(EditorOutcome.Completed, await second.LoadAsync().WaitAsync(Watchdog));
		var loaded = first.Snapshot;
		var changed = loaded.Draft == 5 ? 4 : 5;

		// 1つ目の保存は成功し、revisionが進む
		Assert.True(first.SetCaptureFps(changed));
		Assert.Equal(EditorOutcome.Completed, await first.SaveAsync().WaitAsync(Watchdog));
		Assert.True(first.Snapshot.Revision > loaded.Revision);
		Assert.Contains("新しいフレームから", first.Snapshot.Message);

		// 古いrevisionのまま保存した2つ目は、上書きされず競合になり、編集内容を保持する
		var other = changed == 3 ? 2 : 3;
		Assert.True(second.SetCaptureFps(other));
		Assert.Equal(EditorOutcome.Failed, await second.SaveAsync().WaitAsync(Watchdog));
		Assert.True(second.Snapshot.Conflicted);
		Assert.Equal(other, second.Snapshot.Draft);
		Assert.Contains("再読込", second.Snapshot.Message);
		var current = await admin.ServerSettings.GetCaptureFpsAsync(CancellationToken.None);
		Assert.Equal(changed, current.Value);

		// 確認して再読込すると最新の値になり、競合表示が消える
		Assert.Equal(EditorOutcome.NeedsConfirmation, await second.LoadAsync().WaitAsync(Watchdog));
		Assert.Equal(EditorOutcome.Completed, await second.LoadAsync(discardEdits: true).WaitAsync(Watchdog));
		Assert.Equal((changed, current.Revision, false), (second.Snapshot.Draft, second.Snapshot.Revision, second.Snapshot.Conflicted));
	}

	[RealServerFact]
	public async Task Glossary_RoundTripsAddAndRemove_AndTheServerRejectsDuplicatesThatBypassTheClientCheck()
	{
		using var admin = Client("admin");
		using var model = new GlossaryViewModel(admin.ServerSettings);
		Assert.Equal(EditorOutcome.Completed, await model.LoadAsync().WaitAsync(Watchdog));
		var term = $"Term{Guid.NewGuid():N}";

		Assert.True(model.Add($"  {term} ", " 用語 "));
		Assert.Equal(EditorOutcome.Completed, await model.SaveAsync().WaitAsync(Watchdog));
		var stored = await admin.ServerSettings.GetGlossaryAsync(CancellationToken.None);
		Assert.Contains(new GlossaryEntry(term, "用語"), stored.Value);
		Assert.Equal(stored.Revision, model.Snapshot.Revision);

		// クライアントの確認を迂回した大小違いの重複は、サーバーが拒否する(保存されない)
		var duplicate = await Assert.ThrowsAsync<ControlApiException>(() => admin.ServerSettings.UpdateGlossaryAsync(
			stored.Revision, [.. stored.Value, new GlossaryEntry(term.ToLowerInvariant(), "別")], CancellationToken.None));
		Assert.Equal(ControlApiFailure.InvalidRequest, duplicate.Failure);
		Assert.Equal(stored.Revision, (await admin.ServerSettings.GetGlossaryAsync(CancellationToken.None)).Revision);

		Assert.True(model.Remove(term));
		Assert.Equal(EditorOutcome.Completed, await model.SaveAsync().WaitAsync(Watchdog));
		Assert.DoesNotContain((await admin.ServerSettings.GetGlossaryAsync(CancellationToken.None)).Value, entry => entry.Source == term);
	}

	[RealServerFact]
	public async Task DeviceCredential_CanReadButSavingIsExplainedAsMissingAdminRights_AndKeepsTheEdit()
	{
		using var device = Client("device-a");
		using var model = new TranslationSettingsViewModel(device.ServerSettings);
		Assert.Equal(EditorOutcome.Completed, await model.LoadAsync().WaitAsync(Watchdog));
		var original = model.Snapshot.Draft;
		var edited = original == 5 ? 4 : 5;

		Assert.True(model.SetCaptureFps(edited));
		Assert.Equal(EditorOutcome.Failed, await model.SaveAsync().WaitAsync(Watchdog));

		Assert.Equal(edited, model.Snapshot.Draft);
		Assert.Contains("管理権限", model.Snapshot.Message);
		Assert.Equal(original, (await device.ServerSettings.GetCaptureFpsAsync(CancellationToken.None)).Value);
	}
}
