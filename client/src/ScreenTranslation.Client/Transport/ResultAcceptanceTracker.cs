using System.Text.Json;

namespace ScreenTranslation.Client.Transport;

public sealed class ResultAcceptanceTracker
{
	private const long MaximumResultAgeNanoseconds = 5_000_000_000;
	private readonly object sync = new();
	private readonly Dictionary<ulong, long> sentFrameCaptureTimes = [];
	private Guid? sessionId;
	private ulong generation;
	private ulong dictionaryRevision;
	private ulong lastAppliedFrameId;
	private ulong latestSentFrameId;
	private long latestCaptureMonotonicNanoseconds;

	public void BeginSession(Guid newSessionId, ulong newGeneration, ulong newDictionaryRevision)
	{
		if (newGeneration == 0 || newDictionaryRevision == 0)
		{
			throw new ArgumentOutOfRangeException(nameof(newSessionId), "session、generation、revisionは有効な正数で指定してください。");
		}

		lock (sync)
		{
			sessionId = newSessionId;
			generation = newGeneration;
			dictionaryRevision = newDictionaryRevision;
			lastAppliedFrameId = 0;
			latestSentFrameId = 0;
			latestCaptureMonotonicNanoseconds = 0;
			sentFrameCaptureTimes.Clear();
		}
	}

	public void MarkFrameSent(ulong frameId, long capturedMonotonicNanoseconds)
	{
		lock (sync)
		{
			if (sessionId is null || frameId == 0 || frameId <= latestSentFrameId || capturedMonotonicNanoseconds < latestCaptureMonotonicNanoseconds)
			{
				throw new InvalidOperationException("frame送信順またはsession状態が不正です。");
			}

			var earliestRetainedCapture = Math.Max(0, capturedMonotonicNanoseconds - MaximumResultAgeNanoseconds);
			foreach (var expiredFrame in sentFrameCaptureTimes.Where(item => item.Value < earliestRetainedCapture).Select(item => item.Key).ToArray()) sentFrameCaptureTimes.Remove(expiredFrame);
			latestSentFrameId = frameId;
			latestCaptureMonotonicNanoseconds = capturedMonotonicNanoseconds;
			sentFrameCaptureTimes.Add(frameId, capturedMonotonicNanoseconds);
		}
	}

	public void ChangeDictionaryRevision(ulong newDictionaryRevision)
	{
		lock (sync)
		{
			if (sessionId is null || newDictionaryRevision == 0) throw new InvalidOperationException("有効なsessionとrevisionが必要です。");
			dictionaryRevision = newDictionaryRevision;
		}
	}

	public bool TryAccept(JsonElement result, long nowMonotonicNanoseconds, out JsonElement acceptedResult) =>
		TryAccept(result, nowMonotonicNanoseconds, out acceptedResult, out _);

	/// <summary>採用したresultに対応する取得時刻(クライアント単調時計)も返す。表示期限の起点に使う。</summary>
	public bool TryAccept(JsonElement result, long nowMonotonicNanoseconds, out JsonElement acceptedResult, out long capturedAtNanoseconds)
	{
		acceptedResult = default;
		capturedAtNanoseconds = 0;
		lock (sync)
		{
			if (sessionId is null || !TransportProtocol.IsValidTextMessage(result.GetRawText())) return false;
			if (!result.TryGetProperty("type", out var type) || type.GetString() != "result") return false;
			if (!Guid.TryParse(result.GetProperty("session_id").GetString(), out var resultSessionId) || resultSessionId != sessionId
				|| result.GetProperty("generation").GetUInt64() != generation
				|| result.GetProperty("dictionary_revision").GetUInt64() != dictionaryRevision) return false;

			var frameId = result.GetProperty("frame_id").GetUInt64();
			if (frameId <= lastAppliedFrameId || frameId > latestSentFrameId || !sentFrameCaptureTimes.TryGetValue(frameId, out var capturedAt)) return false;
			if (nowMonotonicNanoseconds < capturedAt || nowMonotonicNanoseconds - capturedAt > MaximumResultAgeNanoseconds) return false;

			lastAppliedFrameId = frameId;
			foreach (var expiredFrame in sentFrameCaptureTimes.Keys.Where(id => id <= frameId).ToArray()) sentFrameCaptureTimes.Remove(expiredFrame);
			acceptedResult = result.Clone();
			capturedAtNanoseconds = capturedAt;
			return true;
		}
	}

	public void InvalidateSession()
	{
		lock (sync)
		{
			sessionId = null;
			generation = 0;
			dictionaryRevision = 0;
			lastAppliedFrameId = 0;
			latestSentFrameId = 0;
			latestCaptureMonotonicNanoseconds = 0;
			sentFrameCaptureTimes.Clear();
		}
	}
}
