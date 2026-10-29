# shellcheck shell=sh
# hook 共通処理。判定規則は scripts/ai-review-gate.py と揃える:
# 行頭の AI-Work-Unit: を本文全体から拾い、1 個以上かつすべて有効な UUID であること。

WORK_UNIT_UUID_PATTERN='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'

# stdin の commit message から Work Unit 値を 1 行ずつ出力する。
# commit -v の diff を拾わないよう scissors 行以降は無視する。
work_units_from_message() {
	sed '/^# -\{24\} >8 -\{24\}$/,$d' \
		| sed -n 's/^[Aa][Ii]-[Ww][Oo][Rr][Kk]-[Uu][Nn][Ii][Tt]:[[:blank:]]*//p' \
		| sed 's/[[:space:]]*$//;s/^$/<empty>/'
}

# 引数の Work Unit 一覧 (改行区切り) に不正な値が含まれていれば 1 を返す
work_units_are_valid() {
	! printf '%s\n' "$1" | grep -Evq "$WORK_UNIT_UUID_PATTERN"
}
