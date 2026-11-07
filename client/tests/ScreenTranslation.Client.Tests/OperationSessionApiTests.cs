using System.Net;
using ScreenTranslation.Client.Api;
using ScreenTranslation.Client.ViewModels;
using Xunit;
using static ScreenTranslation.Client.Tests.OperationFixture;

namespace ScreenTranslation.Client.Tests;

/// <summary>操作モデルに実際のSessionApiClientをつないだとき、失敗の理由が画面の文言として区別でき、再試行できる。</summary>
public sealed class OperationSessionApiTests : IDisposable
{
	private readonly ApiFixture api = new();

	public void Dispose() => api.Dispose();

	[Theory]
	[InlineData(401, "UNAUTHENTICATED", SessionGrantFailure.Unauthenticated)]
	[InlineData(403, "FORBIDDEN", SessionGrantFailure.Forbidden)]
	[InlineData(409, "SESSION_IN_USE", SessionGrantFailure.SessionInUse)]
	[InlineData(503, "MODEL_NOT_READY", SessionGrantFailure.ModelNotReady)]
	public async Task Start_ShowsTheReasonForEachServerRejection_AndCanBeRetried(int status, string code, SessionGrantFailure kind)
	{
		var rejecting = true;
		var handler = new StubHttpHandler((_, _) => Task.FromResult(rejecting
			? StubHttpHandler.JsonResponse((HttpStatusCode)status, ApiFixture.ErrorBody(status, code))
			: StubHttpHandler.JsonResponse(HttpStatusCode.Created, ApiFixture.SessionBody())));
		using var sessions = api.Sessions(handler);
		var host = new FakeSessionOperations();
		await using var vm = new OperationsViewModel(host, sessions, new FakeRegionSelector(), new FakeHotkeyRegistrar(), new ManualTimeProvider(DateTimeOffset.UnixEpoch));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ConnectAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.SelectTargetAsync(Target)));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ReselectRegionAsync()));

		Assert.Equal(OperationOutcome.Failed, await T(vm.StartAsync()));

		Assert.Equal(OperationPhase.Stopped, vm.Snapshot.Phase);
		Assert.Equal(SessionGrantMessages.For(kind), vm.Snapshot.Message);
		Assert.Equal(0, host.StartCount);

		rejecting = false;
		Assert.Equal(OperationOutcome.Completed, await T(vm.StartAsync()));
		Assert.Equal(OperationPhase.Streaming, vm.Snapshot.Phase);
		Assert.Equal(1, host.StartCount);
	}

	[Fact]
	public async Task Stop_ReleasesTheAcquiredSessionWithDelete_AndNewStartAcquiresAFreshOne()
	{
		var deletes = new List<string>();
		var recording = new StubHttpHandler((request, _) =>
		{
			if (request.Method == HttpMethod.Delete) { lock (deletes) deletes.Add(request.Uri.AbsolutePath); return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NoContent)); }
			return Task.FromResult(StubHttpHandler.JsonResponse(HttpStatusCode.Created, ApiFixture.SessionBody()));
		});
		using var sessions = api.Sessions(recording);
		var host = new FakeSessionOperations();
		await using var vm = new OperationsViewModel(host, sessions, new FakeRegionSelector(), new FakeHotkeyRegistrar(), new ManualTimeProvider(DateTimeOffset.UnixEpoch));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ConnectAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.SelectTargetAsync(Target)));
		Assert.Equal(OperationOutcome.Completed, await T(vm.ReselectRegionAsync()));
		Assert.Equal(OperationOutcome.Completed, await T(vm.StartAsync()));

		Assert.Equal(OperationOutcome.Completed, await T(vm.StopAsync()));

		Assert.Equal(["/api/v1/sessions/11111111-1111-4111-8111-111111111111"], deletes);
		Assert.Equal(OperationOutcome.Completed, await T(vm.StartAsync()));
		Assert.Equal(2, recording.Requests.Count(request => request.Method == HttpMethod.Post));
	}
}
