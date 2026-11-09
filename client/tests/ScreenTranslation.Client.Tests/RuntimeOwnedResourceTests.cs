using ScreenTranslation.Client.Capture;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class RuntimeOwnedResourceTests
{
	[Fact]
	public void RepeatedSessionAccessReusesOneResourceUntilRuntimeDisposal()
	{
		var ledger = new CaptureResourceLedger();
		var created = 0;
		var owner = new RuntimeOwnedResource<Probe>(() => { created++; return new Probe(); }, ledger, CaptureResourceKind.D3DDevice);

		var firstSession = owner.GetOrCreate();
		var secondSession = owner.GetOrCreate();

		Assert.Same(firstSession, secondSession);
		Assert.Equal(1, created);
		Assert.Equal(1, ledger.Created(CaptureResourceKind.D3DDevice));
		Assert.Equal(0, ledger.Disposed(CaptureResourceKind.D3DDevice));

		owner.Dispose();
		owner.Dispose();

		Assert.True(firstSession.IsDisposed);
		Assert.Equal(1, ledger.Disposed(CaptureResourceKind.D3DDevice));
		Assert.Throws<ObjectDisposedException>(() => { owner.GetOrCreate(); });
	}

	[Fact]
	public void InvalidatedDeviceIsReleasedAndNextSessionGetsOneReplacement()
	{
		var ledger = new CaptureResourceLedger();
		var owner = new RuntimeOwnedResource<Probe>(() => new Probe(), ledger, CaptureResourceKind.D3DDevice);

		var lost = owner.GetOrCreate();
		Assert.True(owner.Invalidate(lost));
		var replacement = owner.GetOrCreate();

		Assert.NotSame(lost, replacement);
		Assert.True(lost.IsDisposed);
		Assert.Equal(2, ledger.Created(CaptureResourceKind.D3DDevice));
		Assert.Equal(1, ledger.Disposed(CaptureResourceKind.D3DDevice));

		owner.Dispose();
		Assert.Equal(2, ledger.Disposed(CaptureResourceKind.D3DDevice));
	}

	[Fact]
	public void StaleSessionCannotInvalidateAReplacementDevice()
	{
		var owner = new RuntimeOwnedResource<Probe>(() => new Probe());
		var old = owner.GetOrCreate();
		owner.Invalidate(old);
		var current = owner.GetOrCreate();

		Assert.False(owner.Invalidate(old));
		Assert.False(current.IsDisposed);
		owner.Dispose();
	}

	private sealed class Probe : IDisposable
	{
		public bool IsDisposed { get; private set; }
		public void Dispose() => IsDisposed = true;
	}
}
