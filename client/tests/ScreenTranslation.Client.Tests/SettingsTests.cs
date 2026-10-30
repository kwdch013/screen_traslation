using System.Text;
using ScreenTranslation.Client.Security;
using ScreenTranslation.Client.Settings;
using Xunit;

namespace ScreenTranslation.Client.Tests;

public sealed class SettingsTests
{
	[Theory]
	[InlineData("http://example.invalid")]
	[InlineData("ftp://example.invalid")]
	[InlineData("https://user:password@example.invalid")]
	[InlineData("not a uri")]
	public void ConnectionSettings_rejects_unsafe_or_invalid_endpoint(string endpoint)
	{
		var settings = new ConnectionSettings(endpoint);

		Assert.Throws<ArgumentException>(settings.Validate);
	}

	[Fact]
	public async Task Settings_round_trip_contains_connection_preferences_but_no_token()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		var store = new SettingsStore(path);
		var settings = new ClientSettings(new ConnectionSettings("https://service.example"), true);

		await store.SaveAsync(settings);
		var loaded = await store.LoadAsync();
		var serialized = await File.ReadAllTextAsync(path);

		Assert.Equal(settings, loaded);
		Assert.DoesNotContain("token", serialized, StringComparison.OrdinalIgnoreCase);
		Assert.DoesNotContain("password", serialized, StringComparison.OrdinalIgnoreCase);
	}

	[Fact]
	public async Task Credential_store_persists_only_protected_bytes_and_round_trips()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		var protector = new TestCredentialProtector();
		var store = new ProtectedCredentialStore(path, protector);
		const string token = "test-only-device-credential";

		await store.SaveAsync(token);
		var bytes = await File.ReadAllBytesAsync(path);
		var loaded = await store.LoadAsync();

		Assert.False(bytes.AsSpan().SequenceEqual(Encoding.UTF8.GetBytes(token)));
		Assert.Equal(token, loaded);
	}

	[Fact]
	public async Task Corrupt_settings_are_rejected_without_echoing_file_contents()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		const string sensitiveInput = "private-settings-content";
		await File.WriteAllTextAsync(path, sensitiveInput);

		var error = await Assert.ThrowsAsync<InvalidDataException>(() => new SettingsStore(path).LoadAsync());

		Assert.DoesNotContain(sensitiveInput, error.Message, StringComparison.Ordinal);
	}

	[Fact]
	public async Task Null_settings_document_is_not_treated_as_missing_settings()
	{
		var path = Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());
		await File.WriteAllTextAsync(path, "null");

		await Assert.ThrowsAsync<InvalidDataException>(() => new SettingsStore(path).LoadAsync());
	}

	private sealed class TestCredentialProtector : ICredentialProtector
	{
		public byte[] Protect(ReadOnlySpan<byte> plaintext) => plaintext.ToArray().Reverse().ToArray();

		public byte[] Unprotect(ReadOnlySpan<byte> protectedData) => protectedData.ToArray().Reverse().ToArray();
	}
}
