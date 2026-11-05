using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;

namespace ScreenTranslation.Client.TestSupport;

/// <summary>
/// WPF(STAスレッド・Dispatcher・Window等)を使う試験クラスが、直列化の集合(Collection)に入っているかを静的に調べる。
/// 付け忘れると他のWPF試験と並列に動き、STA試験が全て応答しなくなる(#231で実際に発生。根本機構は未特定)。
/// 型を生成せず、フィールド・シグネチャ・ローカル変数・IL内のメタデータ参照だけを読む(OS非依存・副作用なし)。
/// 試験クラスは、テストメソッド([Fact]/[Theory])を持つ型。試験の補助クラス(ハーネス等)経由の利用も、同一アセンブリ内なら辿る。
/// </summary>
public static class WpfSerializationInspector
{
	/// <summary>WPFの型が属するアセンブリ(これらの型、またはこれらから派生した型を使う試験が対象)。</summary>
	public static readonly IReadOnlySet<string> WpfAssemblies = new HashSet<string>
	{
		"WindowsBase", "PresentationCore", "PresentationFramework", "System.Xaml"
	};

	private static readonly Dictionary<short, OpCode> OpCodeTable = typeof(OpCodes)
		.GetFields(BindingFlags.Public | BindingFlags.Static)
		.Where(field => field.FieldType == typeof(OpCode))
		.Select(field => (OpCode)field.GetValue(null)!)
		.ToDictionary(code => code.Value);

	public static bool IsWpfAssemblyType(Type type) => WpfAssemblies.Contains(type.Assembly.GetName().Name ?? "");

	/// <summary>
	/// 直列化の漏れ、空の理由、実在しない許可リスト項目を、理由付きで返す(空なら合格)。
	/// 許可リストは「型名」→WPFを使っても直列化が不要な理由。
	/// </summary>
	public static IReadOnlyList<string> FindProblems(
		IEnumerable<Type> types, string collectionName, IReadOnlyDictionary<string, string> allowed, Func<Type, bool>? isWpfType = null)
	{
		var wpf = isWpfType ?? IsWpfAssemblyType;
		var all = types.Where(type => !IsCompilerGenerated(type)).ToList();
		var cache = new Dictionary<Type, bool>();
		var problems = new List<string>();
		foreach (var type in all.Where(IsTestClass))
		{
			if (!UsesWpf(type, all, wpf, cache, new HashSet<Type>())) continue;
			if (allowed.ContainsKey(type.Name)) continue;
			if (!HasCollection(type, collectionName))
			{
				problems.Add($"{type.Name} はWPFを使いますが [Collection(\"{collectionName}\")] がありません。他のWPF試験と並列に動くと全てが応答しなくなります。");
			}
		}
		foreach (var (name, reason) in allowed)
		{
			if (string.IsNullOrWhiteSpace(reason)) problems.Add($"許可リストの {name} に理由がありません。直列化が不要な理由を書いてください。");
			if (all.All(type => type.Name != name)) problems.Add($"許可リストの {name} に対応する型がありません。削除してください。");
		}
		return problems;
	}

	private static bool IsCompilerGenerated(Type type) =>
		type.IsDefined(typeof(CompilerGeneratedAttribute), false) || type.Name.StartsWith('<');

	private static bool IsTestClass(Type type) =>
		type.GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
			.Any(method => method.GetCustomAttributesData().Any(data => InheritsFromNamed(data.AttributeType, "FactAttribute")));

	private static bool InheritsFromNamed(Type? type, string name)
	{
		for (; type is not null; type = type.BaseType) if (type.Name == name) return true;
		return false;
	}

	private static bool HasCollection(Type type, string collectionName) =>
		type.GetCustomAttributesData().Any(data =>
			data.AttributeType.Name == "CollectionAttribute"
			&& data.ConstructorArguments.Count > 0
			&& data.ConstructorArguments[0].Value as string == collectionName);

	/// <summary>型(と、その中のコンパイラ生成の入れ子型)がWPFを使うか。同一アセンブリの補助型は再帰的に辿る。</summary>
	private static bool UsesWpf(Type type, List<Type> pool, Func<Type, bool> wpf, Dictionary<Type, bool> cache, HashSet<Type> visiting)
	{
		if (cache.TryGetValue(type, out var known)) return known;
		if (!visiting.Add(type)) return false;
		var result = false;
		foreach (var reference in References(type))
		{
			if (IsWpf(reference, wpf)) { result = true; break; }
			var owner = Outermost(reference);
			if (owner != type && owner.Assembly == type.Assembly && pool.Contains(owner) && UsesWpf(owner, pool, wpf, cache, visiting))
			{
				result = true;
				break;
			}
		}
		visiting.Remove(type);
		cache[type] = result;
		return result;
	}

	private static Type Outermost(Type type)
	{
		while (type.DeclaringType is { } outer && IsCompilerGenerated(type)) type = outer;
		return type;
	}

	private static bool IsWpf(Type type, Func<Type, bool> wpf)
	{
		for (var current = type; current is not null; current = current.BaseType) if (wpf(current)) return true;
		return false;
	}

	/// <summary>型が参照する型(フィールド・シグネチャ・ローカル変数・ILのメタデータ参照)を、配列・ジェネリック引数も展開して列挙する。</summary>
	private static IEnumerable<Type> References(Type type)
	{
		const BindingFlags all = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;
		var raw = new List<Type>();
		foreach (var field in type.GetFields(all)) raw.Add(field.FieldType);
		var methods = type.GetMethods(all).Cast<MethodBase>().Concat(type.GetConstructors(all));
		foreach (var method in methods)
		{
			if (method is MethodInfo info) raw.Add(info.ReturnType);
			raw.AddRange(method.GetParameters().Select(parameter => parameter.ParameterType));
			MethodBody? body = null;
			try { body = method.GetMethodBody(); } catch (Exception) { }
			if (body is null) continue;
			raw.AddRange(body.LocalVariables.Select(local => local.LocalType));
			raw.AddRange(TokenTypes(method, body));
		}
		foreach (var nested in type.GetNestedTypes(BindingFlags.Public | BindingFlags.NonPublic).Where(IsCompilerGenerated))
		{
			raw.AddRange(References(nested));
		}
		return raw.SelectMany(Expand).Distinct();
	}

	private static IEnumerable<Type> Expand(Type type)
	{
		if (type.HasElementType) { foreach (var inner in Expand(type.GetElementType()!)) yield return inner; yield break; }
		yield return type;
		if (!type.IsGenericType) yield break;
		foreach (var argument in type.GetGenericArguments()) foreach (var inner in Expand(argument)) yield return inner;
	}

	/// <summary>ILを読み、メソッド・フィールド・型のトークンから参照先の型(宣言型・戻り値・引数・フィールド型)を取り出す。</summary>
	private static IEnumerable<Type> TokenTypes(MethodBase method, MethodBody body)
	{
		var il = body.GetILAsByteArray();
		if (il is null) yield break;
		var typeArguments = method.DeclaringType is { IsGenericType: true } declaring ? declaring.GetGenericArguments() : null;
		var methodArguments = method.IsGenericMethod ? method.GetGenericArguments() : null;
		var module = method.Module;
		for (var position = 0; position < il.Length;)
		{
			short value = il[position++];
			if (value == 0xFE && position < il.Length) value = (short)(0xFE00 | il[position++]);
			if (!OpCodeTable.TryGetValue(value, out var code)) yield break;
			var operandStart = position;
			switch (code.OperandType)
			{
				case OperandType.InlineNone: break;
				case OperandType.ShortInlineBrTarget:
				case OperandType.ShortInlineI:
				case OperandType.ShortInlineVar: position += 1; break;
				case OperandType.InlineVar: position += 2; break;
				case OperandType.InlineI8:
				case OperandType.InlineR: position += 8; break;
				case OperandType.InlineSwitch: position += 4 + 4 * BitConverter.ToInt32(il, position); break;
				default: position += 4; break;
			}
			if (code.OperandType is not (OperandType.InlineMethod or OperandType.InlineField or OperandType.InlineType or OperandType.InlineTok)) continue;
			MemberInfo? member = null;
			try { member = module.ResolveMember(BitConverter.ToInt32(il, operandStart), typeArguments, methodArguments); } catch (Exception) { }
			foreach (var type in MemberTypes(member)) yield return type;
		}
	}

	private static IEnumerable<Type> MemberTypes(MemberInfo? member)
	{
		switch (member)
		{
			case Type type: yield return type; break;
			case FieldInfo field:
				if (field.DeclaringType is not null) yield return field.DeclaringType;
				yield return field.FieldType;
				break;
			case MethodBase method:
				if (method.DeclaringType is not null) yield return method.DeclaringType;
				if (method is MethodInfo info) yield return info.ReturnType;
				foreach (var parameter in method.GetParameters()) yield return parameter.ParameterType;
				break;
		}
	}
}
