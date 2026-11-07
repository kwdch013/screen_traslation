using ScreenTranslation.Client.Capture;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class CaptureResourceLedgerTests
{
	[Fact]
	public void NewLedgerHasNothingOutstanding()
	{
		var ledger = new CaptureResourceLedger();

		Assert.Empty(ledger.Unreleased());
		Assert.Equal(0, ledger.Created(CaptureResourceKind.FramePool));
	}

	[Fact]
	public void CreatedAndDisposedAreCountedPerKind()
	{
		var ledger = new CaptureResourceLedger();

		ledger.RecordCreated(CaptureResourceKind.FramePool);
		ledger.RecordCreated(CaptureResourceKind.FramePool);
		ledger.RecordCreated(CaptureResourceKind.D3DDevice);
		ledger.RecordDisposed(CaptureResourceKind.FramePool);

		Assert.Equal(2, ledger.Created(CaptureResourceKind.FramePool));
		Assert.Equal(1, ledger.Disposed(CaptureResourceKind.FramePool));
		Assert.Equal(1, ledger.Outstanding(CaptureResourceKind.FramePool));
		Assert.Equal(1, ledger.Outstanding(CaptureResourceKind.D3DDevice));
	}

	[Fact]
	public void UnreleasedListsOnlyKindsWithLeaks()
	{
		var ledger = new CaptureResourceLedger();
		for (var i = 0; i < 3; i++)
		{
			ledger.RecordCreated(CaptureResourceKind.CaptureSession);
			ledger.RecordCreated(CaptureResourceKind.SoftwareBitmap);
		}
		ledger.RecordDisposed(CaptureResourceKind.CaptureSession);
		ledger.RecordDisposed(CaptureResourceKind.CaptureSession);
		ledger.RecordDisposed(CaptureResourceKind.CaptureSession);
		ledger.RecordDisposed(CaptureResourceKind.SoftwareBitmap);

		var unreleased = ledger.Unreleased();

		Assert.Equal([(CaptureResourceKind.SoftwareBitmap, 2)], unreleased);
	}

	[Fact]
	public void LeakingOnePerRoundIsDetectedAfterEveryRound()
	{
		var ledger = new CaptureResourceLedger();
		for (var round = 1; round <= 25; round++)
		{
			ledger.RecordCreated(CaptureResourceKind.FramePool);
			ledger.RecordCreated(CaptureResourceKind.CaptureItem);
			ledger.RecordDisposed(CaptureResourceKind.CaptureItem);
			// 1周ごとにFramePoolを1個解放し忘れる

			Assert.Equal(round, ledger.Outstanding(CaptureResourceKind.FramePool));
			Assert.NotEmpty(ledger.Unreleased());
		}
	}

	[Fact]
	public void ReleaseDisposesTheResourceAndRecordsIt()
	{
		var ledger = new CaptureResourceLedger();
		var resource = new Probe();
		ledger.RecordCreated(CaptureResourceKind.TargetWatcher);

		ledger.Release(CaptureResourceKind.TargetWatcher, resource);

		Assert.True(resource.Disposed);
		Assert.Equal(0, ledger.Outstanding(CaptureResourceKind.TargetWatcher));
	}

	[Fact]
	public void ReleaseOfNullIsIgnored()
	{
		var ledger = new CaptureResourceLedger();

		ledger.Release(CaptureResourceKind.TargetWatcher, null);

		Assert.Equal(0, ledger.Disposed(CaptureResourceKind.TargetWatcher));
	}

	[Fact]
	public void ReleaseRecordsEvenWhenDisposeThrows()
	{
		var ledger = new CaptureResourceLedger();
		ledger.RecordCreated(CaptureResourceKind.FramePool);

		Assert.Throws<InvalidOperationException>(() => ledger.Release(CaptureResourceKind.FramePool, new Probe(throws: true)));

		// 破棄を試みた時点で所有権は手放している。二重に解放して数を乱さないよう、数える
		Assert.Equal(0, ledger.Outstanding(CaptureResourceKind.FramePool));
	}

	[Fact]
	public async Task ConcurrentRecordingDoesNotLoseCounts()
	{
		var ledger = new CaptureResourceLedger();
		await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => Task.Run(() =>
		{
			for (var i = 0; i < 1000; i++)
			{
				ledger.RecordCreated(CaptureResourceKind.SoftwareBitmap);
				ledger.RecordDisposed(CaptureResourceKind.SoftwareBitmap);
			}
		})));

		Assert.Equal(8000, ledger.Created(CaptureResourceKind.SoftwareBitmap));
		Assert.Equal(0, ledger.Outstanding(CaptureResourceKind.SoftwareBitmap));
	}

	private sealed class Probe(bool throws = false) : IDisposable
	{
		public bool Disposed { get; private set; }

		public void Dispose()
		{
			Disposed = true;
			if (throws)
			{
				throw new InvalidOperationException();
			}
		}
	}
}
