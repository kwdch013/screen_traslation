using System.Text.Json;
using ScreenTranslation.Client.Geometry;
using ScreenTranslation.Client.Transport;

namespace ScreenTranslation.Client.Overlay;

/// <summary>
/// 結果採用(session/generation/frame/revision/5秒)→座標変換→表示を接続する。
/// キャプチャ除外を確認できない間は<see cref="CanStream"/>がfalseのままで、呼び出し側は画像送信を始めてはならない(fail-closed)。
/// </summary>
public sealed class TranslationOverlayController : IDisposable
{
	private readonly IOverlaySurface surface;
	private readonly TranslationOverlayState state;
	private readonly ResultAcceptanceTracker tracker;
	private readonly Func<long> monotonicNanoseconds;
	private volatile bool canStream;

	public TranslationOverlayController(IOverlaySurface surface, TranslationOverlayState state, ResultAcceptanceTracker tracker, Func<long> monotonicNanoseconds)
	{
		this.surface = surface ?? throw new ArgumentNullException(nameof(surface));
		this.state = state ?? throw new ArgumentNullException(nameof(state));
		this.tracker = tracker ?? throw new ArgumentNullException(nameof(tracker));
		this.monotonicNanoseconds = monotonicNanoseconds ?? throw new ArgumentNullException(nameof(monotonicNanoseconds));
		state.Changed += OnStateChanged;
	}

	public bool CanStream => canStream;
	public event Action<OverlayFailure>? FailedClosed;

	/// <summary>オーバーレイを作り、キャプチャ除外を確認する。失敗時は理由を通知してfalse。</summary>
	public bool Prepare()
	{
		var result = surface.Prepare();
		if (result.Verified)
		{
			canStream = true;
			return true;
		}
		FailClosed(result);
		return false;
	}

	public bool Begin(Rect2D roi, ulong generation)
	{
		if (!canStream) return false;
		state.Activate(roi, generation);
		return true;
	}

	/// <summary>受信したresultを検査して表示する。採用されず表示しなければfalse。</summary>
	public bool HandleResult(JsonElement result)
	{
		if (!canStream || state.CurrentRoi is not { } roi) return false;
		if (!tracker.TryAccept(result, monotonicNanoseconds(), out var accepted, out var capturedAt)) return false;
		if (!OverlayResultMapper.TryMap(accepted, roi, out var regions)) return false;

		// 表示直前に除外が保たれているか確認し、崩れていれば表示せず停止する
		var exclusion = surface.Verify();
		if (!exclusion.Verified)
		{
			FailClosed(exclusion);
			return false;
		}
		return state.Present(accepted.GetProperty("generation").GetUInt64(), capturedAt, regions);
	}

	public void Invalidate(OverlayClearReason reason) => state.Clear(reason);

	/// <summary>期限切れ表示を消す。タイマーから呼ぶ。</summary>
	public void Tick() => state.Expire();

	public void Dispose()
	{
		state.Changed -= OnStateChanged;
		state.Clear(OverlayClearReason.Disposed);
		surface.Hide();
		surface.Dispose();
	}

	private void FailClosed(OverlayExclusionResult result)
	{
		canStream = false;
		state.Clear(OverlayClearReason.ExclusionFailed);
		FailedClosed?.Invoke(new OverlayFailure(
			$"キャプチャ除外を確認できないため翻訳オーバーレイを停止しました。{result.Detail}"));
	}

	private void OnStateChanged(OverlaySnapshot snapshot)
	{
		if (snapshot.IsEmpty) surface.Hide();
		else surface.Render(snapshot);
	}
}
