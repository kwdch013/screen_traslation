import type { SubtitleEntry } from './translationEvents'

interface SubtitleListProps {
	history: SubtitleEntry[]
}

export function SubtitleList({ history }: SubtitleListProps) {
	return (
		<>
			<h2>字幕リスト</h2>
			{history.length === 0 ? (
				<p className="empty-subtitles">翻訳結果はまだありません。</p>
			) : (
				<ul className="subtitle-list">
					{history.map((entry) => (
						<li key={entry.id}>
							<p className="subtitle-source">{entry.source}</p>
							<p className="subtitle-translated">{entry.translated}</p>
						</li>
					))}
				</ul>
			)}
		</>
	)
}
