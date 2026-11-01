using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.ViewModels.Settings;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>用語辞書の一覧・追加・削除と、空値・重複・上限・競合・保存失敗の扱い。</summary>
[Trait("Category", "SettingsApi")]
public sealed class GlossaryViewModelTests
{
	private readonly FakeSettingsApi api = new();

	private async Task<GlossaryViewModel> LoadedAsync()
	{
		var model = new GlossaryViewModel(api);
		Assert.Equal(EditorOutcome.Completed, await model.LoadAsync());
		return model;
	}

	[Fact]
	public async Task Load_ListsTheServerEntriesWithTheirRevision()
	{
		using var model = await LoadedAsync();

		Assert.Equal([new GlossaryEntry("Start", "開始")], model.Snapshot.Draft);
		Assert.Equal(7ul, model.Snapshot.Revision);
	}

	[Fact]
	public async Task AddThenSave_SendsTrimmedEntriesWithTheLoadedRevision()
	{
		using var model = await LoadedAsync();

		Assert.True(model.Add("  Save ", " 保存  "));
		Assert.True(model.Snapshot.HasUnsavedChanges);
		Assert.Equal(EditorOutcome.Completed, await model.SaveAsync());

		Assert.Equal([7ul], api.SentRevisions);
		Assert.Equal(["Start", "Save"], api.SentEntries[0].Select(entry => entry.Source));
		Assert.Equal("保存", api.SentEntries[0][1].Target);
		Assert.Equal((8ul, false), (model.Snapshot.Revision, model.Snapshot.HasUnsavedChanges));
		Assert.Contains("新しいフレームから", model.Snapshot.Message);
	}

	[Theory]
	[InlineData("", "x")]
	[InlineData("x", "")]
	[InlineData("   ", "x")]
	[InlineData("x", "  \t")]
	[InlineData(null, "x")]
	public async Task EmptyOrBlank_IsRejectedAndNothingChanges(string? source, string? target)
	{
		using var model = await LoadedAsync();

		Assert.False(model.Add(source, target));

		Assert.Single(model.Snapshot.Draft);
		Assert.False(model.Snapshot.HasUnsavedChanges);
		Assert.Contains("両方を入力", model.Snapshot.Message);
		Assert.Equal(0, api.Count("put-glossary"));
	}

	[Theory]
	[InlineData("Start")]
	[InlineData("start")]
	[InlineData("  START ")]
	public async Task DuplicateSource_IsRejectedIgnoringCaseAndSpaces(string source)
	{
		using var model = await LoadedAsync();

		Assert.False(model.Add(source, "別の訳"));

		Assert.Single(model.Snapshot.Draft);
		Assert.Contains("すでに登録", model.Snapshot.Message);
	}

	[Fact]
	public async Task LengthLimit_Counts128CodePoints_NotUtf16Units()
	{
		using var model = await LoadedAsync();
		var emoji128 = string.Concat(Enumerable.Repeat("😀", 128));

		Assert.True(model.Add(emoji128, new string('あ', 128)));
		Assert.False(model.Add("long", new string('a', 129)));
		Assert.False(model.Add(emoji128 + "😀", "x"));

		Assert.Equal(2, model.Snapshot.Draft.Count);
		Assert.Contains("128文字", model.Snapshot.Message);
	}

	[Fact]
	public async Task EntryLimit_IsEnforcedAt1000()
	{
		api.OnGetGlossary = _ => Task.FromResult(new Revisioned<IReadOnlyList<GlossaryEntry>>(
			1, Enumerable.Range(0, 999).Select(index => new GlossaryEntry($"s{index}", "t")).ToArray()));
		using var model = await LoadedAsync();

		Assert.True(model.Add("last", "最後"));
		Assert.False(model.Add("over", "超過"));

		Assert.Equal(1000, model.Snapshot.Draft.Count);
		Assert.Contains("1000件", model.Snapshot.Message);
	}

	[Fact]
	public async Task Remove_DeletesBySource_AndRejectsUnknown()
	{
		using var model = await LoadedAsync();

		Assert.False(model.Remove("missing"));
		Assert.True(model.Remove("start"));

		Assert.Empty(model.Snapshot.Draft);
		Assert.True(model.Snapshot.HasUnsavedChanges);
		Assert.Equal(EditorOutcome.Completed, await model.SaveAsync());
		Assert.Empty(api.SentEntries[0]);
	}

	[Fact]
	public async Task RemoveAndReAddTheSameEntry_IsNotAChange()
	{
		using var model = await LoadedAsync();

		model.Remove("Start");
		model.Add("Start", "開始");

		Assert.False(model.Snapshot.HasUnsavedChanges);
		Assert.Equal(EditorOutcome.Ignored, await model.SaveAsync());
		Assert.Equal(0, api.Count("put-glossary"));
	}

	[Fact]
	public async Task Conflict_KeepsEveryUnsavedEntry_UntilTheUserConfirmsTheReload()
	{
		api.OnUpdateGlossary = (_, _, _) => Task.FromException<Revisioned<IReadOnlyList<GlossaryEntry>>>(new ControlApiException(ControlApiFailure.RevisionConflict));
		using var model = await LoadedAsync();
		model.Add("Save", "保存");
		model.Add("Load", "読込");

		Assert.Equal(EditorOutcome.Failed, await model.SaveAsync());

		Assert.True(model.Snapshot.Conflicted);
		Assert.Equal(3, model.Snapshot.Draft.Count);
		Assert.Contains("再読込", model.Snapshot.Message);
		Assert.Equal(7ul, model.Snapshot.Revision);

		api.OnGetGlossary = _ => Task.FromResult(new Revisioned<IReadOnlyList<GlossaryEntry>>(12, [new GlossaryEntry("Other", "他者")]));
		Assert.Equal(EditorOutcome.NeedsConfirmation, await model.LoadAsync());
		Assert.Equal(3, model.Snapshot.Draft.Count);
		Assert.Equal(EditorOutcome.Completed, await model.LoadAsync(discardEdits: true));
		Assert.Equal([new GlossaryEntry("Other", "他者")], model.Snapshot.Draft);
		Assert.Equal((12ul, false), (model.Snapshot.Revision, model.Snapshot.Conflicted));
	}

	[Theory]
	[InlineData(ControlApiFailure.InvalidRequest, "制限")]
	[InlineData(ControlApiFailure.Forbidden, "管理権限")]
	[InlineData(ControlApiFailure.Unreachable, "接続できません")]
	public async Task SaveFailure_KeepsTheEntries_AndNeverShowsServerInternals(ControlApiFailure failure, string expected)
	{
		api.OnUpdateGlossary = (_, _, _) => Task.FromException<Revisioned<IReadOnlyList<GlossaryEntry>>>(new ControlApiException(failure, System.Net.HttpStatusCode.InternalServerError, "INTERNAL_ERROR"));
		using var model = await LoadedAsync();
		model.Add("Save", "保存");

		await model.SaveAsync();

		Assert.Equal(2, model.Snapshot.Draft.Count);
		Assert.True(model.Snapshot.HasUnsavedChanges);
		Assert.Contains(expected, model.Snapshot.Message);
		Assert.DoesNotContain("INTERNAL_ERROR", model.Snapshot.Message);
		Assert.DoesNotContain("500", model.Snapshot.Message);
		Assert.DoesNotContain("Bearer", model.Snapshot.Message);
	}

	[Fact]
	public async Task EditMadeWhileSaving_SurvivesTheSaveResult()
	{
		var gate = new Gate<Revisioned<IReadOnlyList<GlossaryEntry>>>();
		api.OnUpdateGlossary = (_, _, token) => gate.Enter(token);
		using var model = await LoadedAsync();
		model.Add("Save", "保存");
		var save = model.SaveAsync();
		await gate.WaitEnteredAsync();

		Assert.True(model.Add("Load", "読込"));
		gate.Complete(new Revisioned<IReadOnlyList<GlossaryEntry>>(8, [new GlossaryEntry("Save", "保存"), new GlossaryEntry("Start", "開始")]));
		await save;

		Assert.Contains(model.Snapshot.Draft, entry => entry.Source == "Load");
		Assert.True(model.Snapshot.HasUnsavedChanges);
		Assert.Equal(8ul, model.Snapshot.Revision);
	}

	[Fact]
	public async Task CancelEdits_RestoresTheLoadedList()
	{
		using var model = await LoadedAsync();
		model.Add("Save", "保存");
		model.Remove("Start");

		Assert.True(model.CancelEdits());

		Assert.Equal([new GlossaryEntry("Start", "開始")], model.Snapshot.Draft);
		Assert.False(model.Snapshot.HasUnsavedChanges);
	}

	[Fact]
	public async Task ConcurrentAdds_NeverLoseOrDuplicateAnEntry()
	{
		using var model = await LoadedAsync();

		await Task.WhenAll(Enumerable.Range(0, 50).Select(index => Task.Run(() => model.Add($"term{index}", "訳"))));
		await Task.WhenAll(Enumerable.Range(0, 20).Select(_ => Task.Run(() => model.Add("term1", "重複"))));

		Assert.Equal(51, model.Snapshot.Draft.Count);
		Assert.Equal(51, model.Snapshot.Draft.Select(entry => entry.Source).Distinct(StringComparer.OrdinalIgnoreCase).Count());
	}
}
