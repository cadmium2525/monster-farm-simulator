import pandas as pd
from flask import Flask, request, jsonify, render_template
import itertools
import random
from threading import Event

app = Flask(__name__)

# 探索中止フラグ
is_exploration_cancelled = Event()

# CSVファイルの読み込み (データ型を最適化)
try:
    part_affinity_df = pd.read_csv('part_affinity_lookup_table.csv').astype({
        'child_bloodline': 'category',
        'parent_bloodline': 'category',
        'grandpa_bloodline': 'category',
        'grandma_bloodline': 'category'
    })
    part_c_df = pd.read_csv('part_C_lookup_table.csv').astype({
        'parent1_bloodline': 'category',
        'parent2_bloodline': 'category'
    })
except FileNotFoundError:
    print("エラー: CSVファイルが見つかりません。最初に生成スクリプトを実行してください。")
    exit()

# C値の上位10%を事前に抽出
C_AFFINITY_THRESHOLD = 0.90
top_c_threshold = part_c_df['c_affinity'].quantile(C_AFFINITY_THRESHOLD)
part_c_df = part_c_df[part_c_df['c_affinity'] >= top_c_threshold]

# 目標相性値の辞書
TARGET_AFFINITY_SCORES = {
    '×': (0, 257),
    '△': (258, 374),
    '○': (375, 495),
    '◎': (496, 614),
    '☆': (615, float('inf'))
}

# 共通秘伝の値
COMMON_SECRET_III_BONUS = 12.5
COMMON_SECRET_II_BONUS = 5.0
SUB_BLOODLINE_RARE_BONUS = 224

### ルックアップ辞書の事前構築 ###
print("--- ルックアップ辞書の構築を開始します ---")
part_c_lookup = part_c_df.set_index(['parent1_bloodline', 'parent2_bloodline']).to_dict()['c_affinity']
part_affinity_lookup = part_affinity_df.set_index(['parent_bloodline', 'grandpa_bloodline', 'grandma_bloodline', 'child_bloodline']).to_dict()['main_affinity']

# 親と子から最適な祖父母を見つけるためのルックアップを事前に計算
# A値とB値の最適化
# Key: (parent_bloodline, child_bloodline) -> Value: (best_affinity, grandpa_bloodline, grandma_bloodline)
best_ab_lookup = {}
all_bloodlines = part_affinity_df['child_bloodline'].cat.categories.tolist()
for parent in all_bloodlines:
    for child in all_bloodlines:
        max_affinity = -1
        best_gp = None
        best_gm = None
        for gp, gm in itertools.product(all_bloodlines, repeat=2):
            affinity = part_affinity_lookup.get((parent, gp, gm, child), None)
            if affinity is not None and affinity > max_affinity:
                max_affinity = affinity
                best_gp = gp
                best_gm = gm
        best_ab_lookup[(parent, child)] = (max_affinity, best_gp, best_gm)

print("--- ルックアップ辞書の構築が完了しました ---")

@app.route('/')
def index():
    main_bloodlines = sorted(part_affinity_df['child_bloodline'].cat.categories.tolist())
    target_symbols = list(TARGET_AFFINITY_SCORES.keys())
    return render_template('index.html', bloodlines=main_bloodlines, target_symbols=target_symbols)

@app.route('/cancel_exploration', methods=['POST'])
def cancel_exploration():
    print("--- 探索中止リクエストを受信しました ---")
    is_exploration_cancelled.set()
    return jsonify({"message": "Exploration cancellation requested."})

@app.route('/explore', methods=['POST'])
def explore_combinations():
    print("--- 探索開始 ---")
    is_exploration_cancelled.clear()

    data = request.json
    
    common_secret_iii = int(data.get('common_secret_iii', 0))
    common_secret_ii = int(data.get('common_secret_ii', 0))
    target_symbol = data.get('target_symbol', '◎')
    target_affinity_value = data.get('target_affinity_value', None)
    excluded_monsters = set(data.get('excluded_monsters', []))
    limit = int(data.get('limit', 50))
    
    fixed_slots = {
        'child': data.get('child', None),
        'parent1': data.get('parent1', None),
        'grandpa1': data.get('grandpa1', None),
        'grandma1': data.get('grandma1', None),
        'parent2': data.get('parent2', None),
        'grandpa2': data.get('grandpa2', None),
        'grandma2': data.get('grandma2', None)
    }

    common_secret_bonus = (common_secret_iii * COMMON_SECRET_III_BONUS) + (common_secret_ii * COMMON_SECRET_II_BONUS)
    fixed_bonus = common_secret_bonus + SUB_BLOODLINE_RARE_BONUS

    # 目標相性値の決定ロジック
    if target_affinity_value is not None and target_affinity_value != '':
        try:
            target_min = float(target_affinity_value)
        except (ValueError, TypeError):
            target_min, _ = TARGET_AFFINITY_SCORES.get(target_symbol, (496, 614))
    else:
        target_min, _ = TARGET_AFFINITY_SCORES.get(target_symbol, (496, 614))

    exploring_slot_keys = [key for key, value in fixed_slots.items() if value is None]
    all_bloodlines = part_affinity_df['child_bloodline'].cat.categories.tolist()
    explorable_bloodlines = [bl for bl in all_bloodlines if bl not in excluded_monsters]

    # すべてのスロットが固定されている場合の処理
    if not exploring_slot_keys:
        p1 = fixed_slots['parent1']
        p2 = fixed_slots['parent2']
        gp1 = fixed_slots['grandpa1']
        gm1 = fixed_slots['grandma1']
        gp2 = fixed_slots['grandpa2']
        gm2 = fixed_slots['grandma2']
        child = fixed_slots['child']

        c_val = part_c_lookup.get(tuple(sorted((p1, p2))), None)
        a_val = part_affinity_lookup.get((p1, gp1, gm1, child), None)
        b_val = part_affinity_lookup.get((p2, gp2, gm2, child), None)

        if c_val is not None and a_val is not None and b_val is not None:
            total_affinity = a_val + b_val + c_val + fixed_bonus
            result = {
                'best_affinity': total_affinity,
                'combination': {
                    'child': child,
                    'parent1': p1, 'grandpa1': gp1, 'grandma1': gm1,
                    'parent2': p2, 'grandpa2': gp2, 'grandma2': gm2
                }
            }
            return jsonify([result])
        else:
            return jsonify([])

    # 親・祖父母は固定されているが、子が探索対象の場合の処理
    fixed_parent_slots = [fixed_slots['parent1'], fixed_slots['parent2'], fixed_slots['grandpa1'], fixed_slots['grandma1'], fixed_slots['grandpa2'], fixed_slots['grandma2']]
    if fixed_slots['child'] is None and all(fixed_parent_slots):
        print("--- 子のみが探索対象のため、詳細情報を生成します ---")
        detailed_results = []
        
        p1 = fixed_slots['parent1']
        p2 = fixed_slots['parent2']
        gp1 = fixed_slots['grandpa1']
        gm1 = fixed_slots['grandma1']
        gp2 = fixed_slots['grandpa2']
        gm2 = fixed_slots['grandma2']
        
        c_val = part_c_lookup.get(tuple(sorted((p1, p2))), None)
        if c_val is None:
            return jsonify([])
        
        for child_bloodline in explorable_bloodlines:
            if is_exploration_cancelled.is_set():
                return jsonify({"error": "探索が中止されました"}), 500
            
            a_val = part_affinity_lookup.get((p1, gp1, gm1, child_bloodline), None)
            b_val = part_affinity_lookup.get((p2, gp2, gm2, child_bloodline), None)
            
            total_affinity = 0
            if a_val is not None and b_val is not None:
                total_affinity = a_val + b_val + c_val + fixed_bonus
            
            detailed_results.append({
                'child_bloodline': child_bloodline,
                'total_affinity': total_affinity if total_affinity > 0 else None
            })
        
        return jsonify(detailed_results)

    # **ここから改善されたアルゴリズム**
    if fixed_slots['child']:
        print("--- 子が指定されているため、ヒューリスティック探索を実行します ---")
        best_affinity = -1
        best_combination = None
        
        child_bl = fixed_slots['child']
        
        # 1. C値で親候補を絞り込む
        # C値の高い順に上位1000件の親ペアを取得
        c_candidates = sorted(part_c_lookup.items(), key=lambda item: item[1], reverse=True)[:1000]
        
        processed_count = 0
        for (p1_cand, p2_cand), c_val in c_candidates:
            if is_exploration_cancelled.is_set():
                print("--- 探索が中断されました ---")
                return jsonify({"error": "探索が中止されました"}), 500

            # 固定されている親がいれば、その親を含むペアのみを考慮
            if fixed_slots['parent1'] is not None and p1_cand != fixed_slots['parent1'] and p2_cand != fixed_slots['parent1']:
                continue
            if fixed_slots['parent2'] is not None and p1_cand != fixed_slots['parent2'] and p2_cand != fixed_slots['parent2']:
                continue
                
            # 除外モンスターは考慮しない
            if p1_cand in excluded_monsters or p2_cand in excluded_monsters:
                continue

            # 2. A値とB値の最適値を個別に探索
            best_a_val = -1
            best_b_val = -1
            best_gp1 = fixed_slots['grandpa1']
            best_gm1 = fixed_slots['grandma1']
            best_gp2 = fixed_slots['grandpa2']
            best_gm2 = fixed_slots['grandma2']
            
            # A値の探索
            if fixed_slots['parent1'] is None or fixed_slots['parent1'] == p1_cand:
                a_val, gp1_cand, gm1_cand = best_ab_lookup.get((p1_cand, child_bl), (None, None, None))
                if a_val is not None:
                    best_a_val = a_val
                    if fixed_slots['grandpa1'] is None: best_gp1 = gp1_cand
                    if fixed_slots['grandma1'] is None: best_gm1 = gm1_cand

            # B値の探索
            if fixed_slots['parent2'] is None or fixed_slots['parent2'] == p2_cand:
                b_val, gp2_cand, gm2_cand = best_ab_lookup.get((p2_cand, child_bl), (None, None, None))
                if b_val is not None:
                    best_b_val = b_val
                    if fixed_slots['grandpa2'] is None: best_gp2 = gp2_cand
                    if fixed_slots['grandma2'] is None: best_gm2 = gm2_cand

            if best_a_val != -1 and best_b_val != -1:
                total_affinity = best_a_val + best_b_val + c_val + fixed_bonus
                
                # 3. 最高値を追跡
                if total_affinity > best_affinity:
                    best_affinity = total_affinity
                    best_combination = {
                        'parent1': p1_cand,
                        'grandpa1': best_gp1,
                        'grandma1': best_gm1,
                        'parent2': p2_cand,
                        'grandpa2': best_gp2,
                        'grandma2': best_gm2
                    }
            
            processed_count += 1
            if processed_count % 100 == 0:
                print(f"  -> 親ペア候補を {processed_count} 件処理中...", end='\r')

        print("\n--- ヒューリスティック探索完了 ---")
        if best_combination:
            # 探索対象のスロットのみを結果に含める
            result_combination = {key: best_combination[key] for key in exploring_slot_keys if key in best_combination}
            result = {
                'best_affinity': best_affinity,
                'combination': result_combination
            }
            return jsonify([result])
        else:
            return jsonify([])

    # 以下、子が指定されていない場合の既存のサマリー探索ロジック
    else:
        print("--- 子が指定されていないため、サマリーを生成します ---")
        summary_results = {}
        exploring_slot_keys = [key for key, value in fixed_slots.items() if value is None and key != 'child']
        all_bloodlines = part_affinity_df['child_bloodline'].cat.categories.tolist()
        explorable_bloodlines = [bl for bl in all_bloodlines if bl not in excluded_monsters]
    
        if not exploring_slot_keys:
            return jsonify([])
    
        exploration_space = [explorable_bloodlines] * len(exploring_slot_keys)
        all_exploring_combinations = itertools.product(*exploration_space)
    
        is_fast_mode = len(exploring_slot_keys) >= 4
        if is_fast_mode:
            print("空きスロットが4つ以上の為、高速モードで探索します。")
            sample_size = 200000
            sampled_combinations = [
                tuple(random.choices(explorable_bloodlines, k=len(exploring_slot_keys)))
                for _ in range(sample_size)
            ]
            all_exploring_combinations = sampled_combinations
            
        processed_count = 0
        for combo in all_exploring_combinations:
            if is_exploration_cancelled.is_set():
                print("--- 探索が中断されました ---")
                return jsonify({"error": "探索が中止されました"}), 500

            current_fixed_slots = fixed_slots.copy()
            for i, key in enumerate(exploring_slot_keys):
                current_fixed_slots[key] = combo[i]
            
            p1 = current_fixed_slots['parent1']
            p2 = current_fixed_slots['parent2']
    
            if not p1 or not p2: continue
            
            c_val = part_c_lookup.get(tuple(sorted((p1, p2))), None)
            if c_val is None: continue
            
            # 親と祖父母の組み合わせをキーとして使用
            combo_parts = [current_fixed_slots[key] for key in exploring_slot_keys]
            summary_key = tuple(combo_parts)
            
            if summary_key not in summary_results:
                summary_results[summary_key] = {'combination': {}, 'matched_children': set()}
                for i, key in enumerate(exploring_slot_keys):
                    summary_results[summary_key]['combination'][key] = combo[i]

            processed_count += 1
            print(f"  -> 処理中: {processed_count}件目の組み合わせ...", end='\r')

            for child_bloodline in all_bloodlines:
                a_val = part_affinity_lookup.get((p1, current_fixed_slots['grandpa1'], current_fixed_slots['grandma1'], child_bloodline), None)
                b_val = part_affinity_lookup.get((p2, current_fixed_slots['grandpa2'], current_fixed_slots['grandma2'], child_bloodline), None)
    
                if a_val is not None and b_val is not None:
                    total_affinity = a_val + b_val + c_val + fixed_bonus
                    if total_affinity >= target_min:
                         summary_results[summary_key]['matched_children'].add(child_bloodline)

        final_summary_list = []
        for key, value in summary_results.items():
            final_summary_list.append({
                'parent_bloodline': " / ".join(value['combination'].values()),
                'matches': len(value['matched_children']),
                'combination': value['combination']
            })

        print(f"\n--- 探索完了（サマリー生成）---")
        final_summary_list.sort(key=lambda x: x['matches'], reverse=True)
        return jsonify(final_summary_list[:limit]) 

@app.route('/get_details', methods=['POST'])
def get_details():
    print("--- 詳細情報取得リクエストを受信 ---")
    data = request.json
     
    common_secret_iii = int(data.get('common_secret_iii', 0))
    common_secret_ii = int(data.get('common_secret_ii', 0))
    excluded_monsters = set(data.get('excluded_monsters', []))
     
    fixed_slots = {
        'parent1': data.get('parent1', None),
        'grandpa1': data.get('grandpa1', None),
        'grandma1': data.get('grandma1', None),
        'parent2': data.get('parent2', None),
        'grandpa2': data.get('grandpa2', None),
        'grandma2': data.get('grandma2', None)
    }
 
    if not fixed_slots['parent1'] or not fixed_slots['parent2']:
        return jsonify([])
 
    common_secret_bonus = (common_secret_iii * COMMON_SECRET_III_BONUS) + (common_secret_ii * COMMON_SECRET_II_BONUS)
    fixed_bonus = common_secret_bonus + SUB_BLOODLINE_RARE_BONUS
     
    detailed_results = []
     
    p1 = fixed_slots['parent1']
    p2 = fixed_slots['parent2']
    gp1 = fixed_slots['grandpa1']
    gm1 = fixed_slots['grandma1']
    gp2 = fixed_slots['grandpa2']
    gm2 = fixed_slots['grandma2']

    c_val = part_c_lookup.get(tuple(sorted((p1, p2))), None)
    if c_val is None:
        return jsonify([])
 
    all_bloodlines = part_affinity_df['child_bloodline'].cat.categories.tolist()
 
    for child_bloodline in all_bloodlines:
        a_val = part_affinity_lookup.get((p1, gp1, gm1, child_bloodline), None)
        b_val = part_affinity_lookup.get((p2, gp2, gm2, child_bloodline), None)
        
        total_affinity = 0
        if a_val is not None and b_val is not None:
            total_affinity = a_val + b_val + c_val + fixed_bonus
        
        detailed_results.append({
            'child_bloodline': child_bloodline,
            'total_affinity': total_affinity if total_affinity > 0 else None
        })
 
    print(f"--- 詳細情報取得完了 ---")
    return jsonify(detailed_results)

if __name__ == '__main__':
    app.run(debug=True)