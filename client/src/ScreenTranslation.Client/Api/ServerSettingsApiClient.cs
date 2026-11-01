using System.Net;
using System.Text.Json;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.ViewModels.Settings;

namespace ScreenTranslation.Client.Api;

/// <summary>
/// サーバーの設定・用語辞書API。<c>GET/PUT /api/v1/settings</c>・<c>GET/PUT /api/v1/glossary</c>。
/// PUTは取得したrevisionを<c>If-Match</c>に必ず付け、競合(409 REVISION_CONFLICT)は<see cref="ControlApiFailure.RevisionConflict"/>で伝える。
/// 応答はcontracts/schemas/{settings,glossary}.schema.jsonに厳密に適合するものだけを受け入れ、違えば<see cref="ControlApiFailure.InvalidResponse"/>。
/// 認証は呼び出しごとに保護保存から読む(管理操作には管理用の資格情報を保存したストアを渡す)。
/// </summary>
public sealed class ServerSettingsApiClient : IServerSettingsApi, IDisposable
{
	private const string SettingsPath = "/api/v1/settings";
	private const string GlossaryPath = "/api/v1/glossary";

	private readonly ControlApiClient api;

	public ServerSettingsApiClient(ConnectionSettings settings, ProtectedCredentialStore credentials)
		: this(new ControlApiClient(settings, credentials))
	{
	}

	internal ServerSettingsApiClient(ControlApiClient api) => this.api = api ?? throw new ArgumentNullException(nameof(api));

	public async Task<Revisioned<int>> GetCaptureFpsAsync(CancellationToken cancellationToken) =>
		ParseSettings(await Send(HttpMethod.Get, SettingsPath, null, null, cancellationToken).ConfigureAwait(false));

	public async Task<Revisioned<int>> UpdateCaptureFpsAsync(ulong revision, int captureFps, CancellationToken cancellationToken)
	{
		var body = JsonSerializer.Serialize(new Dictionary<string, int> { ["capture_fps"] = captureFps });
		return ParseSettings(await Send(HttpMethod.Put, SettingsPath, body, revision, cancellationToken).ConfigureAwait(false));
	}

	public async Task<Revisioned<IReadOnlyList<GlossaryEntry>>> GetGlossaryAsync(CancellationToken cancellationToken) =>
		ParseGlossary(await Send(HttpMethod.Get, GlossaryPath, null, null, cancellationToken).ConfigureAwait(false));

	public async Task<Revisioned<IReadOnlyList<GlossaryEntry>>> UpdateGlossaryAsync(
		ulong revision, IReadOnlyList<GlossaryEntry> entries, CancellationToken cancellationToken)
	{
		ArgumentNullException.ThrowIfNull(entries);
		var body = JsonSerializer.Serialize(new { entries = entries.Select(entry => new { source = entry.Source, target = entry.Target }) });
		return ParseGlossary(await Send(HttpMethod.Put, GlossaryPath, body, revision, cancellationToken).ConfigureAwait(false));
	}

	private async Task<string> Send(HttpMethod method, string path, string? body, ulong? revision, CancellationToken cancellationToken)
	{
		var response = await api.SendAsync(method, path, body, cancellationToken, revision).ConfigureAwait(false);
		// 契約の成功は200のみ。本文なし・他の2xxは契約外
		return response.Status == HttpStatusCode.OK && !string.IsNullOrWhiteSpace(response.Body)
			? response.Body
			: throw new ControlApiException(ControlApiFailure.InvalidResponse, response.Status);
	}

	private static Revisioned<int> ParseSettings(string body)
	{
		using var document = Parse(body);
		var root = document.RootElement;
		var seen = 0;
		ulong? revision = null;
		int? fps = null;
		foreach (var property in root.EnumerateObject())
		{
			seen++;
			switch (property.Name)
			{
				case "schema_version" when property.Value.ValueKind == JsonValueKind.Number && property.Value.TryGetInt32(out var version) && version == 1: break;
				case "revision": revision = ReadRevision(property.Value); break;
				case "capture_fps" when property.Value.ValueKind == JsonValueKind.Number && property.Value.TryGetInt32(out var value): fps = value; break;
				default: throw Invalid();
			}
		}

		return seen == 3 && revision is { } r && fps is >= TranslationSettingsViewModel.MinimumCaptureFps and <= TranslationSettingsViewModel.MaximumCaptureFps
			? new Revisioned<int>(r, fps.Value)
			: throw Invalid();
	}

	private static Revisioned<IReadOnlyList<GlossaryEntry>> ParseGlossary(string body)
	{
		using var document = Parse(body);
		var seen = 0;
		ulong? revision = null;
		List<GlossaryEntry>? entries = null;
		foreach (var property in document.RootElement.EnumerateObject())
		{
			seen++;
			switch (property.Name)
			{
				case "schema_version" when property.Value.ValueKind == JsonValueKind.Number && property.Value.TryGetInt32(out var version) && version == 1: break;
				case "revision": revision = ReadRevision(property.Value); break;
				case "entries" when property.Value.ValueKind == JsonValueKind.Array: entries = ReadEntries(property.Value); break;
				default: throw Invalid();
			}
		}

		return seen == 3 && revision is { } r && entries is not null ? new Revisioned<IReadOnlyList<GlossaryEntry>>(r, entries) : throw Invalid();
	}

	private static List<GlossaryEntry> ReadEntries(JsonElement array)
	{
		if (array.GetArrayLength() > GlossaryViewModel.MaximumEntries) throw Invalid();
		var entries = new List<GlossaryEntry>();
		foreach (var item in array.EnumerateArray())
		{
			if (item.ValueKind != JsonValueKind.Object) throw Invalid();
			string? source = null, target = null;
			var seen = 0;
			foreach (var property in item.EnumerateObject())
			{
				seen++;
				if (property.Value.ValueKind != JsonValueKind.String) throw Invalid();
				switch (property.Name)
				{
					case "source": source = property.Value.GetString(); break;
					case "target": target = property.Value.GetString(); break;
					default: throw Invalid();
				}
			}

			if (seen != 2 || !ValidText(source) || !ValidText(target)) throw Invalid();
			entries.Add(new GlossaryEntry(source!, target!));
		}

		return entries;
	}

	private static bool ValidText(string? text) => text is { Length: > 0 } && text.EnumerateRunes().Count() <= GlossaryViewModel.MaximumTextLength;

	private static ulong ReadRevision(JsonElement value) =>
		value.ValueKind == JsonValueKind.Number && value.TryGetUInt64(out var revision) && revision >= 1 ? revision : throw Invalid();

	private static JsonDocument Parse(string body)
	{
		try
		{
			var document = JsonDocument.Parse(body, new JsonDocumentOptions { MaxDepth = 8 });
			if (document.RootElement.ValueKind == JsonValueKind.Object) return document;
			document.Dispose();
		}
		catch (JsonException)
		{
		}

		throw Invalid();
	}

	private static ControlApiException Invalid() => new(ControlApiFailure.InvalidResponse, HttpStatusCode.OK);

	public void Dispose() => api.Dispose();
}
