# FutureView Strategy 1 — Handoff

Last consolidated: 2026-08-28

## 目前研究目標

現階段先縮小問題，不碰 Layer2。

目前只問：

> 在重新整理 legal Entry / Exit 資料後，Strategy 1 的 C / Q 結構與 Layer1 統計關係是否仍然存在？

流程必須是：

```text
Raw market data
→ scan all raw legal Entry/Exit
→ 3-session forward-anchor preprocessing
→ cleaned Entry/Exit data
→ Strategy paths
→ R,U,B,C,Q
→ Layer1
```

模型只能發生在上述資料整理完成之後。

---

## 1. Legal Entry / Exit preprocessing — LOCKED

這是資料處理規則，不是模型規則。

### Entry

第一步先完整掃描所有 raw legal Entry。

legal Entry 條件：

```text
close > MA5
close > MA10
close > MA20
MA5 > MA10
MA10 > MA20
```

掃描完全部 raw legal Entry 後，再由時間最早開始整理。

假設目前最早尚未處理的 Entry 是 `e0`。

把 `e0` 後面 3 個 trading sessions 以內的 raw legal Entry 全部合併到 `e0`：

```text
ei - e0 <= 3
```

被合併的 Entry 不可以再往後延伸 cluster。

因此這不是 transitive clustering。

例如 raw Entry：

```text
100, 103, 106, 107
```

100 為 anchor：

```text
100,103 → 100
```

雖然 `106-103=3`，但 103 已被合併，所以不能再往後推。

下一個 anchor 是 106：

```text
106,107 → 106
```

最後 cleaned Entry：

```text
{100,106}
```

不是 `{100}`。

### Exit

Exit 完全使用相同 preprocessing 原則：

1. 先掃描全部 raw legal Exit。
2. 從最早尚未處理的 Exit 開始。
3. 合併該 Exit 後 3 個 trading sessions 內的同類 Exit。
4. 被合併的 Exit 不再成為 anchor。
5. 繼續下一個未處理 Exit。

注意：

```text
不是 ±3
```

而是：

```text
anchor 之後 3 個 trading sessions
```

---

## 2. Cleaned data 才是正式 Strategy data

raw legal Entry / Exit 只是 preprocessing 的中間資料。

正式 downstream analysis 必須使用 cleaned Entry / Exit。

不能是：

```text
raw Entry → C/Q → merge
```

必須是：

```text
raw points
→ merge
→ cleaned points
→ Strategy
→ C/Q
```

Layer1 / Layer2 都只能使用 cleaned data。

---

## 3. Strategy outcome notation — LOCKED

對一個正式 legal Entry `e`，沿 deterministic Strategy path 得到：

```text
R(e)
```

其中：

```text
R(e) = 該 Entry 的實際 Strategy return
```

在 evaluation region `W` 中：

```text
I_W = {cleaned legal Entries in W}
```

則：

```text
U_W = max_{e in I_W} R(e)
```

`B_W` 為相同 evaluation region 的 periodic baseline return。

核心定義：

```text
C_W = U_W - B_W
```

因此：

- `R(e)`：單一 Entry 的 Strategy return
- `U`：該 region 中最好的 legal Entry return
- `B`：baseline
- `C`：Strategy 最佳 opportunity 相對 baseline 的優勢

不要再用舊的 `E(e)` 作主要符號。

---

## 4. Q 定義 — LOCKED

對 legal Entry `e`：

```text
Q(e) = U - R(e)
```

所以：

- `Q=0`：該 Entry 本身達到 region 的 upper bound
- Q 越小：Entry timing 越靠近最佳 legal Entry
- Q 越大：Entry 距離 region 中最佳 legal Entry 越遠

Q 不是 trend strength。

Q 不 normalize by C。

---

## 5. C/Q 語意

```text
C = U - B
```

C 表示：

> 在這個 evaluation region 裡，固定 Strategy 如果選到最佳合法 Entry，可以比 periodic baseline 好多少。

所以 C 是 local Strategy opportunity quality，不是單一 Entry profit。

單一 Entry profit 是：

```text
R(e)
```

Entry quality 是：

```text
Q(e) = U - R(e)
```

理想 region / Entry：

```text
C 大，Q 小
```

---

## 6. Fixed deterministic Strategy path

Strategy 本身不因 preprocessing 改變。

每個 cleaned legal Entry 進入唯一 deterministic Strategy path。

目前 locked semantics：

- initial Entry：1/3 capital
- base minimum：Entry 前最近 5d/10d retrospective local minimum union
- `D_b = P_entry - P_base_min`
- Addon 只可發生於後續 5d/10d retrospective local maxima
- candidate 必須滿足 `candidate_close - last_buy_price > D_b`
- 使用同一個原始 `D_b`
- 最多 Entry + 2 Addons
- 每次部署 1/3 original capital
- first legal SMA5 exit：賣出當時持股 40%，只觸發一次
- 5d partial exit 後仍可 Addon
- legal SMA10 exit：全部平倉並終止
- same-day priority：10d exit > 5d exit > Addon
- 最長 horizon 60 sessions；未結束部位在 horizon close 平倉
- 沒有 3-day cooldown

Entry/Exit preprocessing 發生在這些正式 Strategy points 被 downstream 使用之前。

---

## 7. Window / Layer1 reference

目前 Layer1 使用：

```text
W = 30 trading sessions
stride = 1
```

Short rolling reference：

```text
90 sessions
```

Long reference：

```text
756 sessions ≈ 3Y
```

Reference windows 必須完全在 current W30 之前：

```text
reference.end < current.start
```

避免 reference 與 current W30 overlap。

---

## 8. Layer1 thresholds — LOCKED

保留原始 40/60 定義。

Short reference quantiles：

```text
C90_40, C90_60
Q90_40, Q90_60
```

Long 3Y median：

```text
C3Y_50, Q3Y_50
```

High：

```text
C >= C90_60
and Q <= Q90_60
and C > C3Y_50
and Q < Q3Y_50
```

Low：

```text
C <= C90_40
and Q >= Q90_40
and C < C3Y_50
and Q > Q3Y_50
```

Neutral：otherwise。

不要改成 50%。

Layer1 的用途仍然是 Neutral prefilter：

```text
High → PASS
Low → PASS
Neutral → FILTER/BLOCK
```

不是 Good-vs-Bad classifier。

---

## 9. Layer1 semantic interpretation

High：

```text
high Strategy opportunity + relatively good Entry timing
```

Low：

```text
low Strategy opportunity + relatively poor Entry timing
```

Neutral 為中間 / 不明確區。

High 不代表下一個 W30 一定繼續 High。

目前歷史結果比較像 mean reversion，而不是 continuation。

---

## 10. Cleaned-data C/Q audit 最新結果

TSLA 5Y，W30。

在加入 forward-anchor 3-session preprocessing 後：

```text
windows = 798
Entry-window pairs = 2275
entries/window mean = 2.851
entries/window median = 3.0
```

C：

```text
mean   = -4.5863%
median = -3.0118%
P25    = -11.1253%
P75    = +4.2117%
P90    = +11.0524%
max    = +26.5654%
```

Q：

```text
mean   = 2.3183%
median = 1.0481%
P75    = 3.8188%
P90    = 6.1764%
Q=0 rate = 35.08%
```

Relevant full-audit run:

```text
33177328828
```

---

## 11. Preprocessing 的主要效果

原本相鄰 legal Entry 非常密集。

cleaning 後每 W30 Entry 數量明顯下降。

大致：

```text
High:    5.61 → 1.63
Neutral: 7.73 → 2.89
Low:    12.36 → 4.24
```

所以 preprocessing 確實移除了大量時間上非常靠近、屬於同一訊號區域的 raw Entry。

---

## 12. Layer1 forward-W 統計仍然存在

cleaning 後：

```text
Corr_P(C_past, C_future) = -0.301
Corr_S(C_past, C_future) = -0.322
```

原本的 C mean-reversion relationship 沒有因為 Entry preprocessing 消失。

分組結果：

### High

```text
n = 60
Past C   = +4.31%
Next-W C = -10.10%
Past Q   = 0.10%
Next-W Q = 1.78%
```

### Neutral

```text
n = 158
Past C   = -4.98%
Next-W C = -7.37%
Past Q   = 1.58%
Next-W Q = 2.31%
```

### Low

```text
n = 79
Past C   = -21.80%
Next-W C = -3.56%
Past Q   = 3.25%
Next-W Q = 1.82%
```

Past W30：

```text
C_High > C_Neutral > C_Low
```

Future W30：

```text
C_future,High < C_future,Neutral < C_future,Low
```

因此仍然呈現明顯 mean-reversion structure。

Relevant forward-W audit run：

```text
33177328925
```

---

## 13. Q forward relationship

cleaning 後：

```text
Corr_P(Q_past, Q_future) = -0.349
Corr_S(Q_past, Q_future) = -0.319
```

相比 preprocessing 前，Q 的 past/future association 更清楚。

目前把它視為值得繼續 investigation 的 historical association，不直接宣稱 independent predictive significance。

---

## 14. 現階段結論

目前可以說：

> 3-session forward-anchor preprocessing 大幅降低 Entry duplication，但沒有破壞 C/Q 與 Layer1 的主要歷史統計結構。

目前 evidence 仍支持：

> Past C/Q state contains historical information about the next W30.

主要 relationship 是 mean reverting，而不是 continuation。

但 W30 stride=1，高度 overlapping，所以目前只稱為 historical descriptive association。

---

## 15. Layer2 暫停

先不要繼續 CNN / Layer2。

之前 Layer2 model、checkpoint、live TSLA inference 都是在舊 legal Entry population 上建立。

因為 preprocessing 已經改變正式 dataset：

```text
舊 Layer2 sample count、training result、checkpoint、live C/Q prediction 全部需要重建
```

之前舊模型的：

```text
C_hat = -15.05%
Q_hat = 9.52%
```

不能再視為目前正式模型結果。

---

## 16. 下一個最小問題

下一步不要急著重新 train model。

先繼續 Layer1 statistical investigation。

目前最合理的小問題：

> cleaned Entry data 後，High / Neutral / Low 的 C/Q separation 是否穩定且有意義？

優先檢查：

1. C distribution separation
2. Q distribution separation
3. forward-W C/Q distribution
4. mean 之外的 median / quantiles
5. High / Low 是否在不同 chronological periods 都呈現同方向 relationship

第一層確認後，再決定 Layer2 training dataset。

---

## GitHub state

Formal branch：

```text
strategy-profitability-restart
```

Preprocessing 已接進 deterministic path / C-Q pipeline。

Pre-handoff code/audit commit：

```text
449aeeade02d77c57dd2e88a00f19edff0e06963
```

Key audit runs：

```text
C/Q Full Audit:          33177328828
Layer1 Forward-W Audit:  33177328925
```

目前不要回到舊 raw-entry Layer2 結果。
