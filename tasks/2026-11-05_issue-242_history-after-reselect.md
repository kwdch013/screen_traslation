# Issue #242 再選択後の新sessionで履歴が記録されない不具合を直す

## 原因(事実)
- `TranslationHistory.Clear`の世代の下限は`Math.Max`で単調に増える。再選択で`Clear(host.Generation + 1)`を呼ぶと下限が上がる。
- 新sessionの世代は1から始まる(契約・#210)。開始時の`Clear(host.Generation)`は下限を下げないため、再選択を経たsessionの結果(世代1)が全て下限未満で落ちていた。
- 履歴への入力は`ResultAcceptanceTracker`(session/世代/frame/revision/5秒)を通った結果だけ。ただし採否の後、`Presented`の発火までに停止・再開始が割り込む競合があり、世代の下限は旧世代の遅れた結果を履歴の入口で止める二重の防御だった。

## 設計
- 下限をsessionごとの状態(`SessionState`: 再選択の`Floor`と記録済み最大世代`Highest`)に持つ。新sessionの開始(`BeginSession`)で作り直し、旧sessionの下限を持ち越さない。
- 下限をリセットするだけだと、旧sessionの遅れた結果(世代が新sessionの下限以上)が通るので、`Presented`にsession_idを渡し、履歴は(session, 世代)で照合する。旧sessionの結果は世代の値によらず拒否。
- 開始の完了前に届く新sessionの最初の結果を失わないよう、`ExpectSession`(grant取得直後、履歴は消さない)→`BeginSession`(開始成功。他sessionの履歴を消す)の2段階。開始失敗・取消は`CancelExpectedSession`(解放経路)でそのsessionの結果を捨て、旧履歴は残す(`FailedStart_DoesNotClearHistory`を維持)。
- 同一session内で世代が進んだ後(移動追従など)の旧世代の結果は、記録済み最大世代より小さいとして拒否。
- ログ・`ToString`にsession_id・原文・訳文を出さない(`HistoryEntry.SessionId`は`PrintMembers`から除外)。

## 点検
- `OperationsViewModel`/`TranslationHistory`/`TranslationSessionHost`/`TranslationOverlayController`で、世代の単調性をsessionをまたいで持つ箇所は履歴のみ。ホストと追跡器は`BeginSession`で世代を作り直す。
- 試験の補助(`FakeSessionOperations`)は世代を単調に進めていたため、新session=世代1を再現する試験は`Generation = 0`で明示した。

## 試験
- 単体: `TranslationHistoryTests`(session別の下限・旧sessionの拒否・Expect/Begin/Cancel・同一session内の旧世代)、`OperationHistoryTests`(再選択後の新session・旧sessionの遅れた結果・開始前に届く最初の結果・開始失敗)。
- 結合: `ClientScenarioTests.HistoryOfANewSessionStartedAfterReselect_IsRecorded`(旧`KnownGap_`試験)。
- 既存の2試験(`OperationReselectTests`)は履歴がsessionに結び付くため`ReadyAsync`→`StreamingAsync`に変更(主張は変えていない)。
- mutation: 下限の持ち越し(元の不具合の再現)で4試験、session照合の除去で4試験が落ちる。
