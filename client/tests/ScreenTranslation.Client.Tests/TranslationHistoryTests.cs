using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.History;
using ScreenTranslation.Client.Overlay;
using Xunit;

namespace ScreenTranslation.Client.Tests;

/// <summary>原文/訳文の履歴(最新100件・停止後も保持・再選択/新セッション/終了で消去)の試験。</summary>
public sealed class TranslationHistoryTests
{
	private static readonly Rect2D Box = new(1, 2, 30, 40);

	private static OverlayRegion Placed(string source, string text) => new(Box, text, source);
	private static OverlayRegion Unplaced(string source, string text) => new(null, text, source);

	private static TranslationHistory Create() => new(TimeProvider.System);

	[Fact]
	public void Add_KeepsNewestFirst_AndKeepsReadingOrderInsideOneResult()
	{
		var history = Create();
		history.AddResult(1, [Placed("a1", "訳1"), Placed("a2", "訳2")]);
		history.AddResult(1, [Placed("b1", "訳3")]);

		Assert.Equal(["訳3", "訳1", "訳2"], history.Snapshot().Select(entry => entry.Translation));
		Assert.Equal(3, history.Count);
	}

	[Fact]
	public void Capacity_IsExactlyHundred_AndDropsOldest()
	{
		var history = Create();
		for (var i = 1; i <= TranslationHistory.Capacity; i++) history.AddResult(1, [Placed($"s{i}", $"t{i}")]);
		Assert.Equal(100, history.Count);

		history.AddResult(1, [Placed("s101", "t101")]);

		var snapshot = history.Snapshot();
		Assert.Equal(100, snapshot.Count);
		Assert.Equal("t101", snapshot[0].Translation);
		Assert.Equal("t2", snapshot[^1].Translation);
		Assert.DoesNotContain(snapshot, entry => entry.Translation == "t1");
	}

	[Fact]
	public void LargeResult_NeverExceedsCapacity()
	{
		var history = Create();
		history.AddResult(1, Enumerable.Range(0, 150).Select(i => Placed($"s{i}", $"t{i}")).ToArray());

		Assert.Equal(100, history.Count);
		Assert.Equal("t0", history.Snapshot()[0].Translation);
	}

	[Fact]
	public void UnplacedTranslation_IsKeptAndMarkedAsUnplaced()
	{
		var history = Create();
		history.AddResult(1, [Placed("a", "位置あり"), Unplaced("b", "位置不明")]);

		var entries = history.Snapshot();
		Assert.True(entries.Single(entry => entry.Translation == "位置あり").Positioned);
		Assert.False(entries.Single(entry => entry.Translation == "位置不明").Positioned);
	}

	[Fact]
	public void SameResultRepeated_DoesNotFloodHistory_ButReappearsAfterEmptyResult()
	{
		var history = Create();
		history.AddResult(1, [Placed("a", "訳")]);
		history.AddResult(1, [Placed("a", "訳")]);
		history.AddResult(1, [Placed("a", "訳")]);
		Assert.Equal(1, history.Count);

		history.AddResult(1, []);
		history.AddResult(1, [Placed("a", "訳")]);

		Assert.Equal(2, history.Count);
	}

	[Fact]
	public void ChangedText_IsAddedEvenIfOtherLinesRepeat()
	{
		var history = Create();
		history.AddResult(1, [Placed("a", "訳A"), Placed("b", "訳B")]);
		history.AddResult(1, [Placed("a", "訳A"), Placed("b2", "訳B2")]);

		Assert.Equal(["訳B2", "訳A", "訳B"], history.Snapshot().Select(entry => entry.Translation));
	}

	[Fact]
	public void Stop_DoesNotClear_ButClearWithNewerGenerationDropsOldEntries()
	{
		var history = Create();
		history.AddResult(1, [Placed("a", "旧")]);
		Assert.Single(history.Snapshot());

		history.Clear(minimumGeneration: 2);

		Assert.Equal(0, history.Count);
	}

	[Fact]
	public void LateResultOfOlderGeneration_IsRejectedAfterClear()
	{
		var history = Create();
		history.Clear(minimumGeneration: 3);

		Assert.Equal(0, history.AddResult(2, [Placed("a", "遅れて届いた旧世代")]));
		Assert.Equal(1, history.AddResult(3, [Placed("a", "新世代")]));
		Assert.Equal(["新世代"], history.Snapshot().Select(entry => entry.Translation));
	}

	[Fact]
	public void Clear_KeepsEntriesOfTheNewGeneration()
	{
		var history = Create();
		history.AddResult(1, [Placed("a", "旧")]);
		history.AddResult(2, [Placed("b", "新")]);

		history.Clear(minimumGeneration: 2);

		Assert.Equal(["新"], history.Snapshot().Select(entry => entry.Translation));
	}

	[Fact]
	public void Close_ClearsAndRefusesFurtherEntries()
	{
		var history = Create();
		history.AddResult(1, [Placed("a", "訳")]);

		history.Close();

		Assert.Equal(0, history.Count);
		Assert.Equal(0, history.AddResult(ulong.MaxValue, [Placed("a", "終了後")]));
		Assert.Empty(history.Snapshot());
	}

	[Fact]
	public void Snapshot_IsIndependentOfLaterChanges()
	{
		var history = Create();
		history.AddResult(1, [Placed("a", "訳")]);
		var snapshot = history.Snapshot();

		history.Close();

		Assert.Single(snapshot);
	}

	[Fact]
	public void Changed_IsRaisedOnlyWhenContentChanges()
	{
		var history = Create();
		var count = 0;
		history.Changed += () => count++;

		history.AddResult(1, [Placed("a", "訳")]);
		history.AddResult(1, [Placed("a", "訳")]); // 重複で変化なし
		history.Clear(1); // 消すものなし
		history.Clear(2);

		Assert.Equal(2, count);
	}

	[Fact]
	public void Entry_UsesInjectedClock_AndDoesNotPrintTexts()
	{
		var time = new ManualTimeProvider(new DateTimeOffset(2026, 10, 31, 12, 0, 0, TimeSpan.Zero));
		var history = new TranslationHistory(time);
		history.AddResult(1, [Placed("SECRET-SRC", "SECRET-TEXT")]);

		var entry = history.Snapshot().Single();

		Assert.Equal(time.GetUtcNow(), entry.Timestamp);
		Assert.DoesNotContain("SECRET", entry.ToString());
	}

	[Fact]
	public async Task ConcurrentAddsAndClears_NeverExceedCapacityOrThrow()
	{
		var history = Create();
		var writers = Enumerable.Range(0, 4).Select(w => Task.Run(() =>
		{
			for (var i = 0; i < 200; i++) history.AddResult(1, [Placed($"s{w}-{i}", $"t{w}-{i}")]);
		}));
		var reader = Task.Run(() =>
		{
			for (var i = 0; i < 200; i++) Assert.InRange(history.Snapshot().Count, 0, 100);
		});

		await Task.WhenAll(writers.Append(reader));

		Assert.Equal(100, history.Count);
	}
}

internal sealed class ManualTimeProvider(DateTimeOffset start) : TimeProvider
{
	private DateTimeOffset now = start;
	public override DateTimeOffset GetUtcNow() => now;
	public void Advance(TimeSpan span) => now += span;
}
