using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Client.ViewModels.Settings;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>翻訳設定(取得頻度)の編集。読込・条件付き保存・競合・失敗時の保持・二重送信の抑止。</summary>
[Trait("Category", "SettingsApi")]
public sealed class SettingsViewModelTests
{
	private readonly FakeSettingsApi api = new();

	private async Task<TranslationSettingsViewModel> LoadedAsync()
	{
		var model = new TranslationSettingsViewModel(api);
		Assert.Equal(EditorOutcome.Completed, await model.LoadAsync());
		return model;
	}

	[Fact]
	public void BeforeLoad_NothingCanBeEditedOrSaved_AndNoRequestIsSent()
	{
		var model = new TranslationSettingsViewModel(api);

		Assert.False(model.SetCaptureFps(3));
		Assert.Equal(EditorPhase.NotLoaded, model.Snapshot.Phase);
		Assert.False(model.Snapshot.CanEdit);
		Assert.Equal(EditorOutcome.Ignored, model.SaveAsync().GetAwaiter().GetResult());
		Assert.Empty(api.Calls);
	}

	[Fact]
	public async Task Load_ShowsTheServerValueAndRevision()
	{
		using var model = await LoadedAsync();

		var snapshot = model.Snapshot;
		Assert.Equal((EditorPhase.Ready, 2, 2ul, false), (snapshot.Phase, snapshot.Draft, snapshot.Revision, snapshot.HasUnsavedChanges));
	}

	[Fact]
	public async Task Save_SendsTheLoadedRevisionAndEditedValue_ThenAdoptsTheNewRevision_AndStatesWhenItTakesEffect()
	{
		using var model = await LoadedAsync();
		model.SetCaptureFps(4);
		Assert.True(model.Snapshot.HasUnsavedChanges);

		Assert.Equal(EditorOutcome.Completed, await model.SaveAsync());

		Assert.Equal([2ul], api.SentRevisions);
		Assert.Equal([4], api.SentFps);
		var snapshot = model.Snapshot;
		Assert.Equal((3ul, 4, false, false), (snapshot.Revision, snapshot.Draft, snapshot.HasUnsavedChanges, snapshot.Conflicted));
		Assert.Contains("新しいフレームから", snapshot.Message);
		Assert.Equal(NoticeSeverity.Info, snapshot.Severity);
	}

	[Fact]
	public async Task Save_WithoutChanges_DoesNotCallTheServer()
	{
		using var model = await LoadedAsync();

		Assert.Equal(EditorOutcome.Ignored, await model.SaveAsync());

		Assert.Equal(0, api.Count("put-settings"));
		Assert.Equal("変更がありません。", model.Snapshot.Message);
	}

	[Theory]
	[InlineData(0)]
	[InlineData(6)]
	[InlineData(-1)]
	public async Task OutOfRangeValue_IsRejectedAndTheEditInProgressIsKept(int value)
	{
		using var model = await LoadedAsync();
		model.SetCaptureFps(3);

		Assert.False(model.SetCaptureFps(value));

		Assert.Equal(3, model.Snapshot.Draft);
		Assert.Equal(NoticeSeverity.Error, model.Snapshot.Severity);
		Assert.Contains("1～5", model.Snapshot.Message);
	}

	[Fact]
	public async Task RevisionConflict_KeepsTheEditAndRevision_AndTellsTheUserToReload()
	{
		api.OnUpdateFps = FakeSettingsApi.FailUpdate(ControlApiFailure.RevisionConflict);
		using var model = await LoadedAsync();
		model.SetCaptureFps(5);

		Assert.Equal(EditorOutcome.Failed, await model.SaveAsync());

		var snapshot = model.Snapshot;
		Assert.True(snapshot.Conflicted);
		Assert.Equal((5, 2ul, true), (snapshot.Draft, snapshot.Revision, snapshot.HasUnsavedChanges));
		Assert.Contains("再読込", snapshot.Message);
		Assert.Contains("先に更新", snapshot.Message);
		Assert.Equal(1, api.Count("put-settings"));
	}

	[Fact]
	public async Task ReloadAfterConflict_NeedsConfirmationWhileEditsExist_ThenAdoptsTheLatestServerValue()
	{
		api.OnUpdateFps = FakeSettingsApi.FailUpdate(ControlApiFailure.RevisionConflict);
		using var model = await LoadedAsync();
		model.SetCaptureFps(5);
		await model.SaveAsync();
		api.OnGetFps = _ => Task.FromResult(new Revisioned<int>(9, 1));

		Assert.Equal(EditorOutcome.NeedsConfirmation, await model.LoadAsync());
		Assert.Equal((5, 2ul), (model.Snapshot.Draft, model.Snapshot.Revision));
		Assert.Equal(1, api.Count("get-settings"));

		Assert.Equal(EditorOutcome.Completed, await model.LoadAsync(discardEdits: true));
		var snapshot = model.Snapshot;
		Assert.Equal((1, 9ul, false, false), (snapshot.Draft, snapshot.Revision, snapshot.Conflicted, snapshot.HasUnsavedChanges));
	}

	[Fact]
	public async Task Reload_WithoutEdits_NeedsNoConfirmation()
	{
		using var model = await LoadedAsync();
		api.OnGetFps = _ => Task.FromResult(new Revisioned<int>(4, 3));

		Assert.Equal(EditorOutcome.Completed, await model.LoadAsync());

		Assert.Equal((3, 4ul), (model.Snapshot.Draft, model.Snapshot.Revision));
	}

	[Theory]
	[InlineData(ControlApiFailure.Unauthenticated, "認証")]
	[InlineData(ControlApiFailure.Forbidden, "管理権限")]
	[InlineData(ControlApiFailure.CredentialMissing, "資格情報")]
	[InlineData(ControlApiFailure.InvalidRequest, "制限")]
	[InlineData(ControlApiFailure.ModelNotReady, "準備中")]
	[InlineData(ControlApiFailure.Timeout, "確認できません")]
	[InlineData(ControlApiFailure.Unreachable, "接続できません")]
	[InlineData(ControlApiFailure.CertificateRejected, "証明書")]
	[InlineData(ControlApiFailure.InvalidResponse, "解釈できません")]
	[InlineData(ControlApiFailure.ServerError, "サーバー側の問題")]
	[InlineData(ControlApiFailure.NotFound, "サーバー側の問題")]
	public async Task EverySaveFailure_KeepsTheEditAndExplainsItInJapanese(ControlApiFailure failure, string expected)
	{
		api.OnUpdateFps = FakeSettingsApi.FailUpdate(failure);
		using var model = await LoadedAsync();
		model.SetCaptureFps(4);

		Assert.Equal(EditorOutcome.Failed, await model.SaveAsync());

		var snapshot = model.Snapshot;
		Assert.Equal((EditorPhase.Ready, 4, 2ul, true), (snapshot.Phase, snapshot.Draft, snapshot.Revision, snapshot.HasUnsavedChanges));
		Assert.Contains(expected, snapshot.Message);
		Assert.Contains("保持", snapshot.Message);
		Assert.Equal(NoticeSeverity.Error, snapshot.Severity);
		Assert.True(model.Snapshot.CanSave);
	}

	[Fact]
	public async Task UnexpectedException_NeverLeaksItsTextToTheMessage()
	{
		api.OnUpdateFps = (_, _, _) => throw new InvalidOperationException("Bearer secret-token https://internal.example/api/v1/settings session 11111111-1111-4111-8111-111111111111");
		using var model = await LoadedAsync();
		model.SetCaptureFps(4);

		await model.SaveAsync();

		var message = model.Snapshot.Message;
		Assert.DoesNotContain("secret-token", message);
		Assert.DoesNotContain("internal.example", message);
		Assert.DoesNotContain("11111111", message);
		Assert.Equal(4, model.Snapshot.Draft);
	}

	[Fact]
	public async Task LoadFailure_BeforeAnyLoad_StaysNotLoaded_AndAfterALoad_KeepsTheEdit()
	{
		api.OnGetFps = _ => Task.FromException<Revisioned<int>>(new ControlApiException(ControlApiFailure.Unreachable));
		using var fresh = new TranslationSettingsViewModel(api);
		Assert.Equal(EditorOutcome.Failed, await fresh.LoadAsync());
		Assert.Equal(EditorPhase.NotLoaded, fresh.Snapshot.Phase);
		Assert.Contains("接続できません", fresh.Snapshot.Message);

		api.OnGetFps = _ => Task.FromResult(new Revisioned<int>(2, 2));
		using var loaded = await LoadedAsync();
		loaded.SetCaptureFps(5);
		api.OnGetFps = _ => Task.FromException<Revisioned<int>>(new ControlApiException(ControlApiFailure.Unreachable));
		Assert.Equal(EditorOutcome.Failed, await loaded.LoadAsync(discardEdits: true));
		Assert.Equal((EditorPhase.Ready, 5, true), (loaded.Snapshot.Phase, loaded.Snapshot.Draft, loaded.Snapshot.HasUnsavedChanges));
	}

	[Fact]
	public async Task DoubleSubmit_WhileSaving_SendsOnlyOneRequest()
	{
		var gate = new Gate<Revisioned<int>>();
		api.OnUpdateFps = (_, _, token) => gate.Enter(token);
		using var model = await LoadedAsync();
		model.SetCaptureFps(4);

		var first = model.SaveAsync();
		await gate.WaitEnteredAsync();
		var others = await Task.WhenAll(Enumerable.Range(0, 20).Select(_ => Task.Run(() => model.SaveAsync())));

		Assert.All(others, outcome => Assert.Equal(EditorOutcome.Ignored, outcome));
		Assert.Equal(EditorPhase.Saving, model.Snapshot.Phase);
		Assert.False(model.Snapshot.CanSave);
		Assert.Equal(1, api.Count("put-settings"));
		gate.Complete(new Revisioned<int>(3, 4));
		Assert.Equal(EditorOutcome.Completed, await first);
		Assert.Equal(1, api.Count("put-settings"));
	}

	[Fact]
	public async Task EditMadeWhileSaving_IsKeptWhenTheSaveCompletes()
	{
		var gate = new Gate<Revisioned<int>>();
		api.OnUpdateFps = (_, _, token) => gate.Enter(token);
		using var model = await LoadedAsync();
		model.SetCaptureFps(3);
		var save = model.SaveAsync();
		await gate.WaitEnteredAsync();

		Assert.True(model.SetCaptureFps(5));
		gate.Complete(new Revisioned<int>(3, 3));
		await save;

		var snapshot = model.Snapshot;
		Assert.Equal((5, 3ul, true), (snapshot.Draft, snapshot.Revision, snapshot.HasUnsavedChanges));
		Assert.True(snapshot.CanSave);
	}

	[Fact]
	public async Task LoadAndCancel_AreIgnoredWhileSaving_AndSaveIsIgnoredWhileLoading()
	{
		var saveGate = new Gate<Revisioned<int>>();
		api.OnUpdateFps = (_, _, token) => saveGate.Enter(token);
		using var model = await LoadedAsync();
		model.SetCaptureFps(3);
		var save = model.SaveAsync();
		await saveGate.WaitEnteredAsync();

		Assert.Equal(EditorOutcome.Ignored, await model.LoadAsync(discardEdits: true));
		Assert.False(model.CancelEdits());
		Assert.Equal(1, api.Count("get-settings"));
		saveGate.Complete(new Revisioned<int>(3, 3));
		await save;

		var loadGate = new Gate<Revisioned<int>>();
		api.OnGetFps = token => loadGate.Enter(token);
		var load = model.LoadAsync();
		await loadGate.WaitEnteredAsync();
		model.SetCaptureFps(5);
		Assert.Equal(EditorOutcome.Ignored, await model.SaveAsync());
		Assert.Equal(1, api.Count("put-settings"));
		loadGate.Complete(new Revisioned<int>(4, 2));
		await load;
	}

	[Fact]
	public async Task DisposingWhileSaving_CancelsTheRequest_KeepsTheEdit_AndSaysTheResultIsUnknown()
	{
		var gate = new Gate<Revisioned<int>>();
		api.OnUpdateFps = (_, _, token) => gate.Enter(token);
		var model = await LoadedAsync();
		model.SetCaptureFps(4);
		var save = model.SaveAsync();
		await gate.WaitEnteredAsync();

		model.Dispose();

		Assert.Equal(EditorOutcome.Failed, await save);
		Assert.Equal(4, model.Snapshot.Draft);
		Assert.Contains("確認できません", model.Snapshot.Message);
		Assert.Equal(EditorOutcome.Ignored, await model.SaveAsync());
	}

	[Fact]
	public async Task CancelEdits_RestoresTheServerValueWithoutCallingTheServer()
	{
		using var model = await LoadedAsync();
		model.SetCaptureFps(5);

		Assert.True(model.CancelEdits());

		Assert.Equal((2, false), (model.Snapshot.Draft, model.Snapshot.HasUnsavedChanges));
		Assert.Equal(0, api.Count("put-settings"));
		Assert.Equal(1, api.Count("get-settings"));
		Assert.False(model.CancelEdits());
	}

	[Fact]
	public async Task Changed_IsRaisedForEveryTransition_AndNeverUnderTheLock()
	{
		using var model = await LoadedAsync();
		var raised = 0;
		model.Changed += () =>
		{
			Interlocked.Increment(ref raised);
			// 通知の中から別スレッドが状態を読めること(ロックを持ったまま通知していない)
			Assert.True(Task.Run(() => model.Snapshot).Wait(TimeSpan.FromSeconds(10)));
		};

		model.SetCaptureFps(4);
		await model.SaveAsync();

		Assert.True(raised >= 3);
	}
}
