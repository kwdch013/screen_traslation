using ScreenTranslation.Client.Geometry;

namespace ScreenTranslation.Client.Overlay;

/// <summary>
/// 現在表示している訳文と有効期限の状態。時計は注入でき、OSにもUIにも依存しない。
/// 停止・再選択・対象消失・切断では<see cref="Clear"/>が同期的に表示を空にし、以後の結果は
/// <see cref="Activate"/>されるまで受け付けない(遅延応答で表示を復活させない)。
/// <see cref="Changed"/>は状態ロック内で順序どおり発火するため、購読側は待たずに即返すこと。
/// </summary>
public sealed class TranslationOverlayState
{
	public const long LifetimeNanoseconds = 5_000_000_000;

	private readonly Func<long> monotonicNanoseconds;
	private readonly object sync = new();
	private bool active;
	private ulong generation;
	private Rect2D roi;
	private OverlaySnapshot snapshot = OverlaySnapshot.Empty;
	private long displayedCapturedAt;
	private OverlayClearReason? lastClearReason;

	public TranslationOverlayState(Func<long> monotonicNanoseconds)
	{
		this.monotonicNanoseconds = monotonicNanoseconds ?? throw new ArgumentNullException(nameof(monotonicNanoseconds));
	}

	public event Action<OverlaySnapshot>? Changed;

	public bool IsActive { get { lock (sync) return active; } }
	public ulong Generation { get { lock (sync) return generation; } }
	public Rect2D? CurrentRoi { get { lock (sync) return active ? roi : null; } }
	public OverlayClearReason? LastClearReason { get { lock (sync) return lastClearReason; } }

	public void Activate(Rect2D roi, ulong generation)
	{
		if (generation == 0) throw new ArgumentOutOfRangeException(nameof(generation), "generationは1以上が必要です。");
		if (!roi.IsValid) throw new ArgumentException("ROIは正の幅と高さが必要です。", nameof(roi));
		lock (sync)
		{
			active = true;
			this.generation = generation;
			this.roi = roi;
			lastClearReason = null;
			SetSnapshot(OverlaySnapshot.Empty);
		}
	}

	/// <summary>採用済みの結果を表示へ反映する。世代違い・非アクティブ・期限切れ・より古い取得は拒否する。</summary>
	public bool Present(ulong resultGeneration, long capturedAtNanoseconds, IReadOnlyList<OverlayRegion> regions)
	{
		ArgumentNullException.ThrowIfNull(regions);
		lock (sync)
		{
			var age = monotonicNanoseconds() - capturedAtNanoseconds;
			if (!active || resultGeneration != generation || age < 0 || age > LifetimeNanoseconds) return false;
			if (!snapshot.IsEmpty && capturedAtNanoseconds < displayedCapturedAt) return false;

			displayedCapturedAt = capturedAtNanoseconds;
			var placed = regions.Where(region => region.PhysicalRect is not null).ToArray();
			var unplaced = regions.Where(region => region.PhysicalRect is null).Select(region => region.Text).ToArray();
			SetSnapshot(placed.Length + unplaced.Length == 0 ? OverlaySnapshot.Empty : new OverlaySnapshot(roi, placed, unplaced));
			return true;
		}
	}

	/// <summary>表示を消し、以後<see cref="Activate"/>まで結果を受け付けない。</summary>
	public void Clear(OverlayClearReason reason)
	{
		lock (sync)
		{
			active = false;
			lastClearReason = reason;
			SetSnapshot(OverlaySnapshot.Empty);
		}
	}

	/// <summary>表示が期限切れなら消して true。まだ有効または表示なしなら何もしない。</summary>
	public bool Expire()
	{
		lock (sync)
		{
			if (snapshot.IsEmpty || !IsExpired()) return false;
			SetSnapshot(OverlaySnapshot.Empty);
			return true;
		}
	}

	public OverlaySnapshot GetSnapshot()
	{
		lock (sync) return snapshot.IsEmpty || IsExpired() ? OverlaySnapshot.Empty : snapshot;
	}

	/// <summary>次に表示が失効するまでの時間。表示がなければ null。タイマー設定用。</summary>
	public TimeSpan? TimeUntilExpiry()
	{
		lock (sync)
		{
			if (snapshot.IsEmpty) return null;
			var remaining = displayedCapturedAt + LifetimeNanoseconds - monotonicNanoseconds();
			return remaining <= 0 ? TimeSpan.Zero : TimeSpan.FromTicks(remaining / 100);
		}
	}

	private bool IsExpired() => monotonicNanoseconds() - displayedCapturedAt > LifetimeNanoseconds;

	private void SetSnapshot(OverlaySnapshot next)
	{
		snapshot = next;
		Changed?.Invoke(next);
	}
}
