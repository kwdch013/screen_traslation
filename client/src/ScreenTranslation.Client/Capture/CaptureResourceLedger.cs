namespace ScreenTranslation.Client.Capture;

/// <summary>計測の対象にする取得資源の種類。</summary>
public enum CaptureResourceKind
{
	CaptureItem,
	D3DDevice,
	FramePool,
	CaptureSession,
	TargetWatcher,
	SoftwareBitmap,
}

/// <summary>
/// 取得資源の生成数と破棄数を種類ごとに数える計測フック。
/// プロセス全体のハンドル数は他スレッドの影響で揺れるため、試験は生成数と破棄数の一致を直接検証する。
/// 製品の通常経路では渡さない(null)。スレッドセーフ。
/// 限界: 数えるのはDisposeの呼び出しだけで、破棄後もネイティブ側の参照が残る漏れは数えられない。
/// また<c>GraphicsCaptureItem</c>にはDisposeが無いため、イベント購読の解除を「破棄」とみなして数えている。
/// </summary>
public sealed class CaptureResourceLedger
{
	private static readonly CaptureResourceKind[] Kinds = Enum.GetValues<CaptureResourceKind>();
	private readonly long[] created = new long[Kinds.Length];
	private readonly long[] disposed = new long[Kinds.Length];

	public void RecordCreated(CaptureResourceKind kind) => Interlocked.Increment(ref created[(int)kind]);

	public void RecordDisposed(CaptureResourceKind kind) => Interlocked.Increment(ref disposed[(int)kind]);

	public int Created(CaptureResourceKind kind) => (int)Interlocked.Read(ref created[(int)kind]);

	public int Disposed(CaptureResourceKind kind) => (int)Interlocked.Read(ref disposed[(int)kind]);

	/// <summary>生成されたが破棄されていない数。</summary>
	public int Outstanding(CaptureResourceKind kind) => Created(kind) - Disposed(kind);

	/// <summary>未破棄の資源がある種類と、その数。</summary>
	public IReadOnlyList<(CaptureResourceKind Kind, int Count)> Unreleased() =>
		[.. Kinds.Select(kind => (Kind: kind, Count: Outstanding(kind))).Where(entry => entry.Count != 0)];

	/// <summary>
	/// 資源を破棄して数える。破棄を試みた時点で所有権を手放したものとして、破棄が例外でも数える。
	/// 破棄の呼び出しと計測を1か所にまとめ、破棄の呼び忘れが数の不一致として必ず現れるようにする。
	/// </summary>
	public void Release(CaptureResourceKind kind, IDisposable? resource)
	{
		if (resource is null)
		{
			return;
		}
		try
		{
			resource.Dispose();
		}
		finally
		{
			RecordDisposed(kind);
		}
	}
}
