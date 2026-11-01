using System.Reflection;

namespace ScreenTranslation.Client.TestSupport;

/// <summary>公開イベントの購読状態。</summary>
public enum EventWiringState
{
	/// <summary>購読者が1つ以上ある。</summary>
	Subscribed,
	/// <summary>購読者がない(配線の忘れ)。</summary>
	Unsubscribed,
	/// <summary>購読の有無を調べられない(フィールド型イベントでない)。許可リストで明示しない限り不合格にする。</summary>
	Uninspectable
}

public sealed record EventWiring(Type Owner, string Event, EventWiringState State)
{
	/// <summary>許可リストと報告で使う識別子(型名.イベント名)。</summary>
	public string Key => $"{Owner.Name}.{Event}";
}

/// <summary>
/// 公開イベントを列挙し、購読者がいるかを調べる(OS非依存)。
/// 将来イベントを足して購読を忘れたとき、列挙に自動で加わるため検査が落ちる。
/// 対象は、対象オブジェクトと同じアセンブリで宣言された型のインスタンスの公開イベントだけ
/// (WPFなど基盤の型が持つイベントは、基盤が購読を管理するため対象外)。
/// </summary>
public static class EventWiringInspector
{
	private const BindingFlags Declared = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

	public static IReadOnlyList<EventWiring> Inspect(object publisher)
	{
		ArgumentNullException.ThrowIfNull(publisher);
		var result = new List<EventWiring>();
		var assembly = publisher.GetType().Assembly;
		for (var type = publisher.GetType(); type is not null && type.Assembly == assembly; type = type.BaseType)
		{
			foreach (var evt in type.GetEvents(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly))
			{
				// フィールド型イベントの購読者は、同名のデリゲート型フィールドに保持される
				var field = type.GetField(evt.Name, Declared);
				var state = field is null || field.FieldType != evt.EventHandlerType
					? EventWiringState.Uninspectable
					: field.GetValue(publisher) is null ? EventWiringState.Unsubscribed : EventWiringState.Subscribed;
				result.Add(new EventWiring(type, evt.Name, state));
			}
		}
		return result;
	}

	/// <summary>
	/// 購読されていない公開イベント、および実在しない許可リスト項目を、理由付きで返す(空なら合格)。
	/// 許可リストは「型名.イベント名」→購読不要である理由。
	/// </summary>
	public static IReadOnlyList<string> FindProblems(IEnumerable<object> publishers, IReadOnlyDictionary<string, string> allowed)
	{
		var all = publishers.SelectMany(Inspect).ToList();
		var problems = new List<string>();
		foreach (var wiring in all.Where(w => w.State != EventWiringState.Subscribed && !allowed.ContainsKey(w.Key)))
		{
			problems.Add(wiring.State == EventWiringState.Unsubscribed
				? $"{wiring.Key} を購読している処理がありません(配線の忘れ)。"
				: $"{wiring.Key} は購読の有無を調べられません。フィールド型イベントにするか、理由を付けて許可リストに入れてください。");
		}
		foreach (var key in allowed.Keys.Where(key => all.All(w => w.Key != key)))
		{
			problems.Add($"許可リストの {key} に対応するイベントがありません。削除してください。");
		}
		return problems;
	}
}
