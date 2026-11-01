using System.Windows;
using ScreenTranslation.Client.Settings;
using ScreenTranslation.Client.ViewModels;
using ScreenTranslation.Windows.Hotkeys;
using ScreenTranslation.Windows.Operations;

namespace ScreenTranslation.Windows;

/// <summary>接続・開始・停止・再選択・ホットキーの操作モデルを、接続設定から組み立てて操作パネルへ渡す。</summary>
public partial class MainWindow
{
	private OperationsViewModel? _operations;
	private ConnectionSettings? _composedConnection;

	private void InitializeOperations()
	{
		Operations.ConnectRequested += ConnectAsync;
		Operations.HotkeyReapplyRequested += ReapplyHotkeys;
		Closed += async (_, _) => await DisposeOperationsAsync();
	}

	private async Task ConnectAsync()
	{
		ClientSettings? settings;
		try
		{
			settings = await _settingsStore.LoadAsync();
		}
		catch (Exception)
		{
			StatusText.Text = "保存済み設定を読み取れません。接続設定を保存し直してください。";
			return;
		}
		if (settings is null)
		{
			StatusText.Text = "先にサーバー接続先を設定して保存してください。";
			return;
		}

		// 接続設定が同じなら組み立て直さない(再接続で対象・領域・字幕履歴を失わない)
		if (_operations is not null && _composedConnection == settings.Connection)
		{
			_operations.ApplyHotkeys(settings.Hotkeys);
			await _operations.ConnectAsync();
			return;
		}

		await DisposeOperationsAsync();
		_composedConnection = settings.Connection;
		var app = (App)Application.Current;
		var registrar = new WindowsHotkeyRegistrar();
		_operations = OperationsComposition.Create(
			app.CaptureRuntime, settings, _credentialStore, Dispatcher, new UnavailableSessionGrantProvider(), registrar);
		Operations.Attach(_operations, app.CaptureRuntime.Targets);
		_operations.ApplyHotkeys(settings.Hotkeys);
		await _operations.ConnectAsync();
	}

	private async void ReapplyHotkeys()
	{
		if (_operations is null) return;
		try
		{
			_operations.ApplyHotkeys((await _settingsStore.LoadAsync())?.Hotkeys);
		}
		catch (Exception)
		{
			StatusText.Text = "ホットキーの設定を読み込めませんでした。設定を保存し直してください。";
		}
	}

	private async Task DisposeOperationsAsync()
	{
		var current = _operations;
		_operations = null;
		Operations.Attach(null, null);
		if (current is not null) await current.DisposeAsync();
	}
}
