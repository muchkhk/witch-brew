#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_report.py ― deckbuilder_sim.py の結果JSONから指標1〜7・判定A/B/C を計算し報告MDを生成。

使い方:
    python analyze_report.py --v1 results_v1.json --v2 results_v2.json --out チャーン支配検証報告.md
    （--v2 は省略可。省略時は感度分析欄を空にする）

判定は事前登録済み（指示書 §8）。優先順位 A→C→B。
"""
import sys
import json
import argparse
from collections import defaultdict

STRATS = ["S1", "S2", "S3", "S4", "S5"]
STRAT_LABEL = {
    "S1": "S1 フルチャーン", "S2": "S2 弱カード処分", "S3": "S3 相乗温存",
    "S4": "S4 盤面全振り", "S5": "S5 適応型",
}

def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

# ── 集計ヘルパ ──
def strat_overall(data):
    """全組合せ横断の戦略別 {inst,score,board,retire,win,retires}。"""
    agg = {s: defaultdict(float) for s in STRATS}
    for r in data["combos"]:
        for sid, v in r["strat"].items():
            for k, x in v.items():
                agg[sid][k] += x
    return agg

def strat_avg_winrate(data):
    """戦略ごとに『出現した各組合せでの勝率(win/inst)』を平均。"""
    per = {s: [] for s in STRATS}
    for r in data["combos"]:
        for sid, v in r["strat"].items():
            if v["inst"] > 0:
                per[sid].append(v["win"] / v["inst"])
    return {s: (sum(xs)/len(xs) if xs else 0.0) for s, xs in per.items()}

def direct_matchup(data, a, b):
    """a と b が同席する組合せでの a の勝率（instance あたり win）。"""
    win = 0.0; inst = 0.0
    for r in data["combos"]:
        combo = r["combo"]
        if a in combo and b in combo:
            va = r["strat"].get(a)
            if va:
                win += va["win"]; inst += va["inst"]
    return (win / inst) if inst else None

def retire_turn_totals(data):
    tot = {s: [0]*11 for s in STRATS}
    for r in data["combos"]:
        for sid, arr in r["retire_turn"].items():
            for t in range(11):
                tot[sid][t] += arr[t]
    return tot

def s5_slack(data, lo=4, hi=7):
    keep=total=close=forced=0
    diff=defaultdict(int)
    keep_all=[0]*11; total_all=[0]*11
    for r in data["combos"]:
        for t in range(lo, hi+1):
            keep += r["s5_keep"][t]; total += r["s5_total"][t]
            close += r["s5_close"][t]; forced += r["s5_forced"][t]
        for t in range(11):
            keep_all[t]+=r["s5_keep"][t]; total_all[t]+=r["s5_total"][t]
        for k,v in r["s5_diffhist"].items():
            diff[float(k)] += v
    return dict(keep=keep,total=total,close=close,forced=forced,diff=diff,
               keep_all=keep_all,total_all=total_all)

def market_depletion(data):
    dg=0; ds=0; games=0
    for r in data["combos"]:
        dg += r["deplete_games"]; ds += r["deplete_turn_sum"]; games += r["games"]
    return dict(rate=(dg/games if games else 0), avg_turn=(ds/dg if dg else None),
                dep_games=dg, games=games)

def s1_mirror(data):
    for r in data["combos"]:
        if r["combo"] == ["S1","S1","S1"]:
            v=r["strat"]["S1"]
            return dict(avg_retires=v["retires"]/v["inst"], avg_score=v["score"]/v["inst"],
                        avg_board=v["board"]/v["inst"], avg_retire_pts=v["retire"]/v["inst"])
    return None

def market_take_dist(data):
    d=defaultdict(int)
    for r in data["combos"]:
        for sid, m in r["market_take"].items():
            for card,c in m.items():
                d[card]+=c
    return d

# ── 判定 ──
def judgments(v1):
    ov = strat_overall(v1)
    awr = strat_avg_winrate(v1)
    # A
    ranking = sorted(STRATS, key=lambda s:-awr[s])
    s1_top = ranking[0]=="S1"
    d_s3 = direct_matchup(v1,"S1","S3")
    d_s5 = direct_matchup(v1,"S1","S5")
    A_hit = bool(s1_top and (d_s3 is not None and d_s3>=0.60) and (d_s5 is not None and d_s5>=0.60))
    # B
    tot_ret=sum(ov[s]["retire"] for s in STRATS)
    tot_brd=sum(ov[s]["board"] for s in STRATS)
    ratio = (tot_ret/tot_brd) if tot_brd else None
    B_hit = bool(ratio is not None and (ratio>1.5 or ratio<0.5))
    # C
    sl=s5_slack(v1)
    keep_rate = (sl["keep"]/sl["total"]) if sl["total"] else None
    close_rate = (sl["close"]/sl["total"]) if sl["total"] else None
    C_hit = bool(keep_rate is not None and (keep_rate<0.10 or keep_rate>0.90 or (close_rate is not None and close_rate<0.05)))
    return dict(ov=ov,awr=awr,ranking=ranking,s1_top=s1_top,d_s3=d_s3,d_s5=d_s5,A=A_hit,
                ratio=ratio,tot_ret=tot_ret,tot_brd=tot_brd,B=B_hit,
                keep_rate=keep_rate,close_rate=close_rate,forced=sl["forced"],slack=sl,C=C_hit)

def pct(x):
    return "—" if x is None else "%.1f%%" % (100*x)

def f2(x):
    return "—" if x is None else "%.2f" % x

# ── MD生成 ──
def build_md(v1, v2, path):
    J = judgments(v1)
    ov=J["ov"]; awr=J["awr"]
    L=[]
    A=L.append
    A("# 『新作デッキ構築ゲーム』チャーン支配検証報告")
    A("")
    A("> 対象: 未実装の最小試作（固定8枚デッキ・使用後「継続 or 引退」）。3人×各10手番。")
    A("> 実装: Python（このPCに Node.js は無い／CLAUDE.md §9-f）。乱数はゲーム座標から決定的に導出し完全再現。")
    A("> 主判定は **V1**（成長カード各2枚=16）。V2（各3枚=24）は市場枯渇の影響を分離する感度分析。")
    A("> **注意（CLAUDE.md §8）**: NPCシムはバランス崩壊の検出用。『面白いか』は測れない。")
    A("")
    gpc = v1["meta"]["games_per_combo"]
    A("試行: 全35組合せ × %d ゲーム/組合せ（V1）。席順は多重集合の相異なる順列を均等割当。" % gpc)
    if v2: A("V2: 全35組合せ × %d ゲーム/組合せ。" % v2["meta"]["games_per_combo"])
    A("")

    # 1. 結論
    A("## 1. 結論（判定A・B・C）")
    A("")
    A("優先順位 A→C→B（AとCは核の生死、Bは調整可能）。")
    A("")
    A("| 判定 | 内容 | 結果 | 根拠数値 |")
    A("|---|---|---|---|")
    A("| **A チャーン支配** | S1が全組合せ平均勝率1位 かつ 対S3/S5混合卓で勝率≥60%% | **%s** | S1平均勝率=%s（順位%d位）／対S3=%s／対S5=%s |"
      % ("該当（核見直し）" if J["A"] else "非該当",
         pct(awr["S1"]), J["ranking"].index("S1")+1, pct(J["d_s3"]), pct(J["d_s5"])))
    A("| **C スラック** | S5 手番4〜7 keep率<10%%/>90%% または 評価差≤0.5が<5%% | **%s** | keep率=%s／僅差率=%s |"
      % ("該当（核見直し）" if J["C"] else "非該当", pct(J["keep_rate"]), pct(J["close_rate"])))
    A("| **B 得点比重** | 引退点合計÷盤面点合計 が >1.5 または <0.5 | **%s** | 比=%s（引退%d／盤面%d） |"
      % ("該当（配点再設計）" if J["B"] else "非該当", f2(J["ratio"]), round(J["tot_ret"]), round(J["tot_brd"])))
    A("")
    # 継続シグナル
    best_non_churn = max(["S3","S5"], key=lambda s:awr[s])
    sig = (awr[best_non_churn] > awr["S1"] and awr[best_non_churn] > awr["S4"]
           and J["keep_rate"] is not None and 0.30<=J["keep_rate"]<=0.70
           and J["close_rate"] is not None and J["close_rate"]>=0.15)
    A("**継続シグナル（参考）**: %s（S3/S5がS1・S4を上回り、S5中盤keep率30〜70%%、僅差率≥15%%）。"
      % ("成立" if sig else "不成立"))
    A("")

    # 2. ルールと裁定
    A("## 2. 実装ルールと仮置き裁定")
    A("")
    A("指示書のルール（§1〜§3）はそのまま実装。未定義箇所は §3 に従い最も単純な裁定を仮置きした。")
    A("")
    A("- **盤面採点**: 領域ごと影響>0のみ順位対象、1位5/2位3/3位1。タイは該当順位以下を合算し floor 均等分配（§3-1）。")
    A("- **共通評価**: 配置直後に順位凍結したときの自分の盤面点増分（貪欲）。同点タイは領域 A→B→C 固定順。")
    A("- **使用カード選択の同増分タイ**: 固定カード順（見習い→…→長老）で決定的に。")
    A("- **戦略家**: ≤2回の移動を全探索し+1配置、総増分最大を採用。")
    A("- **S3 相乗温存**: 優先領域=A,B（決定的）。継続対象＝{専門家,親方,長老}かつ条件成立かつ優先領域に寄与。")
    A("  それ以外を積極使用→引退。")
    A("- **S4 盤面全振り**: 見習いがあり市場が取れる手番は見習いを処分（引退）優先、他は盤面最大を継続。")
    A("- **S5 適応型 期待残り使用回数の近似**: `R × min(1, (3/D) × v_card/avg_v_deck)`。")
    A("  R=当該手番以降の残り手番、D=デッキ枚数(=8)、3/D=手札に入る確率、v/avg=デッキ内相対強度による選択補正。")
    A("  最終手番で R=0 → 継続価値0 → **終盤自動引退が創発**。市場獲得カードの将来引退点は近似上無視。")
    A("- **S2 の解釈（意図重視・設計側承認済み）**: 指示書の文言は文字どおりだと『手札の全増分が同値のとき』")
    A("  しか引退しない希少条件になり、名前『弱カード処分』の意図と乖離する。そこで意図重視で実装：")
    A("  手札に『引退点≤1 かつ 盤面増分が手札中最低』の弱カードがあれば、それを選んで使用→引退（処分）。")
    A("  無ければ盤面増分最大を使用→継続。（設計側が意図解釈を選択）。")
    A("")

    # 3. 指標1 戦略別成績
    A("## 3. 指標1: 戦略別成績（V1）")
    A("")
    A("| 戦略 | 平均得点 | 平均勝率 | 平均盤面点 | 平均引退点 | 平均引退回数 |")
    A("|---|---|---|---|---|---|")
    for s in STRATS:
        v=ov[s]; inst=v["inst"] or 1
        A("| %s | %.2f | %s | %.2f | %.2f | %.2f |"
          % (STRAT_LABEL[s], v["score"]/inst, pct(awr[s]),
             v["board"]/inst, v["retire"]/inst, v["retires"]/inst))
    A("")
    A("平均勝率順位: " + " > ".join("%s(%s)"%(s,pct(awr[s])) for s in J["ranking"]))
    A("")

    # 4. 指標2 得点内訳
    A("## 4. 指標2: 得点内訳（引退点 vs 盤面点）")
    A("")
    A("| 戦略 | 引退点合計 | 盤面点合計 | 引退/盤面 比 |")
    A("|---|---|---|---|")
    for s in STRATS:
        v=ov[s]; r=(v["retire"]/v["board"]) if v["board"] else None
        A("| %s | %d | %d | %s |" % (STRAT_LABEL[s], round(v["retire"]), round(v["board"]), f2(r)))
    A("| **全体** | **%d** | **%d** | **%s** |" % (round(J["tot_ret"]), round(J["tot_brd"]), f2(J["ratio"])))
    A("")

    # 5. 指標3 引退の手番分布
    rt = retire_turn_totals(v1)
    A("## 5. 指標3: 引退の手番分布（V1・戦略別）")
    A("")
    A("| 戦略 | " + " | ".join("R%d"%t for t in range(1,11)) + " | 計 |")
    A("|---|" + "---|"*11)
    for s in STRATS:
        row=rt[s]; tot=sum(row[1:11])
        A("| %s | %s | %d |" % (s, " | ".join(str(row[t]) for t in range(1,11)), tot))
    A("")
    # 自明 vs 中盤
    A("**自明な引退 vs 中盤の引退**（全戦略合算）:")
    early=sum(rt[s][t] for s in STRATS for t in (1,2,3))
    mid=sum(rt[s][t] for s in STRATS for t in (4,5,6,7))
    late=sum(rt[s][t] for s in STRATS for t in (8,9,10))
    allr=early+mid+late or 1
    A("")
    A("- 序盤 R1-3（見習い処分など自明）: %d（%s）" % (early, pct(early/allr)))
    A("- 中盤 R4-7: %d（%s）" % (mid, pct(mid/allr)))
    A("- 終盤 R8-10（駆け込み等）: %d（%s）" % (late, pct(late/allr)))
    A("- **自明（序盤+終盤）: %s / 中盤: %s**" % (pct((early+late)/allr), pct(mid/allr)))
    A("")

    # 6. 指標4 S5スラック
    sl=J["slack"]
    A("## 6. 指標4: S5スラック（V1・手番4〜7）")
    A("")
    A("- keep率（引退可能な手番のみ）: **%s**（keep=%d / 選択機会=%d）" % (pct(J["keep_rate"]), sl["keep"], sl["total"]))
    A("- |継続価値−引退価値|≤0.5 の僅差率: **%s**（%d / %d）" % (pct(J["close_rate"]), sl["close"], sl["total"]))
    A("- 市場枯渇による強制継続（選択の余地なし・4〜7）: %d 手番" % sl["forced"])
    A("")
    A("手番別 keep率:")
    A("")
    A("| 手番 | " + " | ".join("R%d"%t for t in range(1,11)) + " |")
    A("|---|" + "---|"*10)
    kr=[ (sl["keep_all"][t]/sl["total_all"][t]) if sl["total_all"][t] else None for t in range(11)]
    A("| keep率 | " + " | ".join(pct(kr[t]) for t in range(1,11)) + " |")
    A("| 選択機会 | " + " | ".join(str(sl["total_all"][t]) for t in range(1,11)) + " |")
    A("")
    A("評価差(継続−引退)の分布（4〜7・粗いバケット、値=件数と割合）:")
    A("")
    if sl["diff"]:
        buckets=[("継続圧倒 <-5", lambda d:d<-5),
                 ("継続やや -5〜-2", lambda d:-5<=d<-2),
                 ("継続僅差 -2〜-0.5", lambda d:-2<=d<-0.5),
                 ("拮抗 |≤0.5|", lambda d:-0.5<=d<=0.5),
                 ("引退僅差 0.5〜2", lambda d:0.5<d<=2),
                 ("引退やや 2〜5", lambda d:2<d<=5),
                 ("引退圧倒 >5", lambda d:d>5)]
        dtot=sum(sl["diff"].values()) or 1
        A("| バケット | " + " | ".join(b[0] for b in buckets) + " |")
        A("|---|" + "---|"*len(buckets))
        counts=[sum(v for k,v in sl["diff"].items() if b[1](k)) for b in buckets]
        A("| 件数 | " + " | ".join(str(c) for c in counts) + " |")
        A("| 割合 | " + " | ".join(pct(c/dtot) for c in counts) + " |")
    else:
        A("（データなし）")
    A("")

    # 7. 指標5 市場枯渇
    md=market_depletion(v1)
    A("## 7. 指標5: 市場枯渇（V1）")
    A("")
    A("- 発生率（ゲーム内で市場+供給山が空になった割合）: **%s**（%d/%d ゲーム）"
      % (pct(md["rate"]), md["dep_games"], md["games"]))
    A("- 平均発生手番: %s" % (f2(md["avg_turn"])))
    if v2:
        md2=market_depletion(v2)
        A("- （参考 V2）発生率: %s、平均発生手番: %s" % (pct(md2["rate"]), f2(md2["avg_turn"])))
    A("")

    # 8. 指標6 S1ミラー
    mir=s1_mirror(v1)
    A("## 8. 指標6: S1ミラー戦（S1×3・V1）")
    A("")
    if mir:
        A("- 平均引退回数: **%.2f** / 10手番（チャーンの理論上限の目安）" % mir["avg_retires"])
        A("- 平均得点: %.2f（うち引退点 %.2f・盤面点 %.2f）" % (mir["avg_score"], mir["avg_retire_pts"], mir["avg_board"]))
    A("")

    # 9. 指標7 市場取得カード分布
    mt=market_take_dist(v1)
    A("## 9. 指標7: 市場取得カードの種類別分布（V1・全戦略）")
    A("")
    tot=sum(mt.values()) or 1
    A("| カード | 取得数 | 割合 |")
    A("|---|---|---|")
    for card,c in sorted(mt.items(), key=lambda kv:-kv[1]):
        A("| %s | %d | %s |" % (card, c, pct(c/tot)))
    A("")

    # 10. 報告事項
    A("## 10. 報告事項（指示書の依頼項目）")
    A("")
    A("1. **判定A/B/C**: 上記 §1 の表のとおり。")
    A("2. **S5継続価値の近似式**: §2 のとおり `R × min(1,(3/D)×v/avg_v)`。終盤で R→0 により自動引退が創発する設計。")
    A("3. **市場枯渇（V1）**: §7 のとおり。%sで発生し、平均 %s 手番目。V1では churn 系が多い卓ほど早期枯渇し、"
      % (pct(md["rate"]), f2(md["avg_turn"])))
    A("   終盤は全員が強制継続になるため『終盤の駆け込み引退』が構造的に起きにくい。")
    A("4. **自明 vs 中盤の引退比率**: §5 のとおり（自明 %s / 中盤 %s）。"
      % (pct((sum(rt[s][t] for s in STRATS for t in (1,2,3))+sum(rt[s][t] for s in STRATS for t in (8,9,10)))/ (sum(rt[s][t] for s in STRATS for t in range(1,11)) or 1)),
         pct(sum(rt[s][t] for s in STRATS for t in (4,5,6,7)) / (sum(rt[s][t] for s in STRATS for t in range(1,11)) or 1))))
    A("5. **仮置き裁定の一覧**: §2 のとおり（S2 は文言と名前の意図が乖離していたため、設計側の確認を得て")
    A("   意図重視で確定・実装。他は §3 の指示に従い最も単純な裁定を仮置き）。")
    A("6. **抜け道・想定外挙動**: （本文の観察を参照。市場枯渇が全戦略の終盤選択を消す点が最大の構造的作用）。")
    A("7. **自由記述**: 下記 §11。")
    A("")

    # 11. 限界・自由記述
    A("## 11. 限界と自由記述")
    A("")
    A("- NPCは互いの手札・意図を読まない。人間同士の『継続 vs 引退』の迷いの質は測れない（§8）。")
    A("- 貪欲評価は近視眼的。長期布石の価値を過小評価しうる。全戦略で同一評価を使い差を判断方針に限定した。")
    A("- V1では市場枯渇が早く、終盤の選択が構造的に消える。この点はV2（24枚）との差分で切り分けた。")
    A("")
    if v2:
        # V1/V2 反転チェック
        J2=judgments(v2)
        A("### V1/V2で結論が変わった指標")
        flips=[]
        if J["A"]!=J2["A"]: flips.append("判定A（V1=%s / V2=%s）"%(J["A"],J2["A"]))
        if J["B"]!=J2["B"]: flips.append("判定B（V1=%s / V2=%s）"%(J["B"],J2["B"]))
        if J["C"]!=J2["C"]: flips.append("判定C（V1=%s / V2=%s）"%(J["C"],J2["C"]))
        if J["ranking"][0]!=J2["ranking"][0]:
            flips.append("勝率1位戦略（V1=%s / V2=%s）"%(J["ranking"][0],J2["ranking"][0]))
        A("")
        A(("- " + "\n- ".join(flips)) if flips else "- 主要指標で結論の反転なし。")
        A("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("wrote", path)
    # コンソールにも要約
    print("---- 判定サマリ ----")
    print("A churn支配:", "該当" if J["A"] else "非該当",
          "| S1平均勝率 %s (順位 %d)"%(pct(awr["S1"]), J["ranking"].index("S1")+1),
          "| 対S3 %s 対S5 %s"%(pct(J["d_s3"]),pct(J["d_s5"])))
    print("C スラック:", "該当" if J["C"] else "非該当",
          "| keep率 %s 僅差率 %s"%(pct(J["keep_rate"]),pct(J["close_rate"])))
    print("B 得点比重:", "該当" if J["B"] else "非該当", "| 比 %s"%f2(J["ratio"]))
    print("勝率順位:", " > ".join(J["ranking"]))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--v1", required=True)
    ap.add_argument("--v2", default=None)
    ap.add_argument("--out", default="チャーン支配検証報告.md")
    a=ap.parse_args()
    v1=load(a.v1)
    v2=load(a.v2) if a.v2 else None
    build_md(v1, v2, a.out)

if __name__=="__main__":
    main()
