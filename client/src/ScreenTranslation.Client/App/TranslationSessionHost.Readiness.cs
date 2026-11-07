using System.Text.Json;
using ScreenTranslation.Client.Overlay;

namespace ScreenTranslation.Client.App;

/// <summary>
/// WSSの<c>MODEL_NOT_READY</c>(サーバーの翻訳エンジンが準備前・準備失敗中・停止開始後で、フレームを破棄した)を受けたときの挙動 (Issue #202)。
/// 送信を一時停止し、<c>/api/v1/ready</c>が準備完了を返したら自動で再開する。session・世代・WSSは維持し、生存通知(keepalive)も止めない。
/// </summary>
public sealed partial class TranslationSessionHost
{
	private const string ReadinessCheckFailedMessage = "サーバーの準備状態を確認できなかったため停止しました。接続設定と資格情報を確認してください。";

	private readonly IServerReadinessProbe? readinessProbe;
	private readonly Func<TimeSpan, CancellationToken, Task> readinessDelay;
	private Task readinessTask = Task.CompletedTask;
	// 準備待ちの間はtrue。準備待ちの確認ループは1本だけで、再入(続けて届くMODEL_NOT_READY)では増やさない
	private bool waitingForServer;
	// 再開前に送ったフレームへの、遅れて届くMODEL_NOT_READYを再び準備待ちの契機にしないための境界
	private ulong staleNotReadyGeneration;
	private ulong staleNotReadyThroughFrameId;

	/// <summary>
	/// サーバーの準備待ちの状態が変わった(準備待ちに入った・確認できない・再開した)。
	/// 準備待ちに入るのは現在のsessionの<c>MODEL_NOT_READY</c>を採用したときの1回で、続く通知は出さない。
	/// </summary>
	public event Action<ServerReadinessState>? ServerReadinessChanged;

	/// <summary>準備待ちで送信を止めているか。</summary>
	public bool IsWaitingForServer { get { lock (sync) return waitingForServer; } }

	/// <summary>
	/// 採用済みの<c>MODEL_NOT_READY</c>を処理する。確認手段が無い構成(readinessProbe未指定)は従来どおりcodeだけを通知し、送信は止めない。
	/// </summary>
	private void OnModelNotReady(JsonElement message)
	{
		if (readinessProbe is null)
		{
			FrameFailed?.Invoke("MODEL_NOT_READY");
			return;
		}

		var generationOfError = message.TryGetProperty("generation", out var g) && g.TryGetUInt64(out var parsedGeneration) ? parsedGeneration : 0;
		var frameId = message.TryGetProperty("frame_id", out var f) && f.TryGetUInt64(out var parsedFrame) ? parsedFrame : 0;
		lock (sync)
		{
			if (!active || waitingForServer || sendCancellation is not { } owner) return;
			if (generationOfError == staleNotReadyGeneration && frameId <= staleNotReadyThroughFrameId) return;
			if (!pipeline.Suspend()) return;

			waitingForServer = true;
			var checking = CancellationTokenSource.CreateLinkedTokenSource(owner.Token);
			readinessTask = Task.Run(() => RunReadinessLoopAsync(owner, checking));
		}
		ServerReadinessChanged?.Invoke(ServerReadinessState.Preparing);
	}

	/// <summary>
	/// 準備完了を確認するまで、間隔を置いて<c>/api/v1/ready</c>を確認する。停止・再選択・切断・破棄ではsessionの取消で止まる。
	/// ロック内ではawaitしない。確認の失敗は固定の状態通知へ分類し、回復しない失敗だけ停止する。
	/// </summary>
	private async Task RunReadinessLoopAsync(CancellationTokenSource owner, CancellationTokenSource checking)
	{
		var token = checking.Token;
		var interval = ServerReadinessPolicy.InitialInterval;
		var reported = ServerReadinessState.Preparing;
		try
		{
			while (!token.IsCancellationRequested)
			{
				await readinessDelay(interval, token).ConfigureAwait(false);
				ServerReadinessResult result;
				try
				{
					result = await readinessProbe!.CheckAsync(token).ConfigureAwait(false);
				}
				catch (OperationCanceledException) when (token.IsCancellationRequested)
				{
					return;
				}
				catch (Exception)
				{
					// 確認手段の想定外の失敗は、一時的な失敗として扱う(例外の内容は残さない)
					result = ServerReadinessResult.Unavailable;
				}
				if (token.IsCancellationRequested) return;

				switch (result)
				{
					case ServerReadinessResult.Ready:
						ResumeAfterReady(owner);
						return;
					case ServerReadinessResult.Rejected:
						if (EndSession(OverlayClearReason.Disconnected, owner))
						{
							_ = StopAfterFailureAsync();
							Faulted?.Invoke(ReadinessCheckFailedMessage);
						}
						return;
					case ServerReadinessResult.Unavailable when reported != ServerReadinessState.CheckFailed:
						reported = ServerReadinessState.CheckFailed;
						if (IsWaitingFor(owner)) ServerReadinessChanged?.Invoke(reported);
						break;
					case ServerReadinessResult.NotReady when reported != ServerReadinessState.Preparing:
						reported = ServerReadinessState.Preparing;
						if (IsWaitingFor(owner)) ServerReadinessChanged?.Invoke(reported);
						break;
				}
				interval = ServerReadinessPolicy.Next(interval);
			}
		}
		catch (OperationCanceledException)
		{
		}
		finally
		{
			checking.Dispose();
		}
	}

	private bool IsWaitingFor(CancellationTokenSource owner)
	{
		lock (sync) return active && waitingForServer && ReferenceEquals(sendCancellation, owner);
	}

	/// <summary>
	/// 準備完了で送信を再開する。待機中のまま同じsessionが続いている場合だけ。保持している最新の画像を、取得時刻を現在へ付け替えて1件送る。
	/// 再開前に送ったフレームに対するMODEL_NOT_READYが遅れて届いても、再び準備待ちに入らない。
	/// </summary>
	private void ResumeAfterReady(CancellationTokenSource owner)
	{
		lock (sync)
		{
			if (!active || !waitingForServer || !ReferenceEquals(sendCancellation, owner)) return;
			staleNotReadyGeneration = generation;
			staleNotReadyThroughFrameId = pipeline.LastFrameId;
			waitingForServer = false;
			pipeline.Resume(clock());
		}
		ServerReadinessChanged?.Invoke(ServerReadinessState.Resumed);
	}
}
