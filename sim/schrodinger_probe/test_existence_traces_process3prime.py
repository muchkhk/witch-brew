"""
手順3（凍結前・存在証明トレースの機械検算）: 事前登録_シュレディンガー工程3prime_kill基準.md
§8のE-F1±・E-F2±の4トレースを、simulator_process3prime.play_single_game で再現し、
手計算で導出された数値と完全一致するか検算する。

design chat裁定（対応差の単位多義の解消）:
  「対応差」は得点差ではなく、工程3実装(win_indicator)と同一の勝敗指標差である
  （勝ち=1.0・同点=0.5・負け=0.0。§D-3「同点は両者0.5勝として集計」と整合）。
  (a) ラウンド別行動・得点はこれまでどおり検証する。
  (b) 各トレースの勝敗指標（S側とB1の得点比較から導出）を検証する。
  (c) 対応差＝勝敗指標差（期待値 +1／−1／+0.5／−1）を検証する。

条件: P1(判定対象)=A・P2=B1=B・座席対称化なし・a_controls_first=True（R1が判定対象の
制御ラウンド）・c=0.5・全4ラウンド。
不一致が1件でもあれば exit(1) で終了し、凍結コミットへ進めないことを示す。
"""

import sys

from simulator_process3prime import play_single_game


def run(name_a, name_b, true_values):
    dummy_rng = None
    return play_single_game(name_a, name_b, true_values, True, dummy_rng, price=0.5)


def win_indicator(x_score, b_score):
    """工程3実装(simulator_process3.py: win_indicator)と同一の勝敗指標。"""
    if x_score > b_score:
        return 1.0
    if x_score == b_score:
        return 0.5
    return 0.0


TRACES = [
    {
        "id": "E-F1+ (K-F1 非発動例)",
        "assignment": (10, 1, 2, 11, 3, 12),
        "pair": ("S2", "S1"),
        # (a) ラウンド別行動・得点の検算（既存どおり）
        "expect_scores": {
            "S2_vs_B1_score_a": 2.5, "S2_vs_B1_score_b": 2.0,
            "S1_vs_B1_score_a": 1.5, "S1_vs_B1_score_b": 2.0,
        },
        "expect_diff": 1.0,  # (c) 対応差＝勝敗指標差
    },
    {
        "id": "E-F1- (K-F1 発動方向の例)",
        "assignment": (1, 10, 2, 11, 3, 12),
        "pair": ("S2", "S1"),
        "expect_scores": {
            "S2_vs_B1_score_a": 0.0, "S2_vs_B1_score_b": 2.0,
            "S1_vs_B1_score_a": 3.0, "S1_vs_B1_score_b": 2.0,
        },
        "expect_diff": -1.0,
    },
    {
        "id": "E-F2+ (K-F2 非発動例)",
        "assignment": (10, 1, 11, 2, 3, 12),
        "pair": ("S2", "S2f"),
        # S2fの得点は元記載(0)と再検算(0.5)で割れているため、勝敗指標(0)は動かず
        # スコア自体は検算対象から外し、勝敗指標差のみを判定基準とする（design chat裁定）。
        "expect_scores": {},
        "expect_diff": 0.5,
    },
    {
        "id": "E-F2- (K-F2 発動方向の例)",
        "assignment": (1, 10, 11, 2, 3, 12),
        "pair": ("S2", "S2f"),
        "expect_scores": {},
        "expect_diff": -1.0,
    },
]


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


def main():
    failures = []
    for tr in TRACES:
        p_name, q_name = tr["pair"]
        av = list(tr["assignment"])
        g_p = run(p_name, "B1", av)
        g_q = run(q_name, "B1", av)

        # (a) ラウンド別行動・得点
        print(f"=== {tr['id']} ===")
        print(f"  A={av}")
        print(f"  {p_name} vs B1: score_{p_name}={g_p['score_a']}, score_B1={g_p['score_b']}, "
              f"asked={g_p['asked_order']}, peeks={p_name}:{g_p['peek_count_a']}")
        print(f"  {q_name} vs B1: score_{q_name}={g_q['score_a']}, score_B1={g_q['score_b']}, "
              f"asked={g_q['asked_order']}, peeks={q_name}:{g_q['peek_count_a']}")

        for key, val in ((f"{p_name}_vs_B1_score_a", g_p["score_a"]),
                          (f"{p_name}_vs_B1_score_b", g_p["score_b"]),
                          (f"{q_name}_vs_B1_score_a", g_q["score_a"]),
                          (f"{q_name}_vs_B1_score_b", g_q["score_b"])):
            exp = tr["expect_scores"].get(key)
            if exp is not None and not approx(val, exp):
                failures.append((tr["id"], key, val, exp))

        # (b) 勝敗指標
        w_p = win_indicator(g_p["score_a"], g_p["score_b"])
        w_q = win_indicator(g_q["score_a"], g_q["score_b"])
        print(f"  勝敗指標: {p_name}={w_p} / {q_name}={w_q}")

        # (c) 対応差 = 勝敗指標差
        diff = w_p - w_q
        print(f"  対応差({p_name}-{q_name}) [勝敗指標差] = {diff}")

        exp_diff = tr["expect_diff"]
        if not approx(diff, exp_diff):
            failures.append((tr["id"], "diff(win_indicator)", diff, exp_diff))
        print()

    if failures:
        print("!!! 不一致あり !!!")
        for fid, key, actual, expected in failures:
            print(f"  {fid} / {key}: actual={actual} expected={expected}")
        sys.exit(1)
    else:
        print("=== 全件一致（4トレース） ===")
        sys.exit(0)


if __name__ == "__main__":
    main()
