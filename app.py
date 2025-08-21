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

    # 以下、既存の探索ロジック
    if fixed_slots['child']:
        print("--- 子が指定されているため、最適な組み合わせを探索します ---")
        best_affinity = -1
        best_combination = None
        
        exploring_parents = []
        if fixed_slots['parent1'] is None: exploring_parents.append('parent1')
        if fixed_slots['parent2'] is None: exploring_parents.append('parent2')

        c_candidates = sorted(part_c_lookup.items(), key=lambda item: item[1], reverse=True)
        
        parent_combos_to_explore = []
        if len(exploring_parents) == 2:
            parent_combos_to_explore = [(item[0][0], item[0][1]) for item in c_candidates]
        elif len(exploring_parents) == 1:
            fixed_parent = 'parent1' if fixed_slots['parent1'] else 'parent2'
            for bl in explorable_bloodlines:
                p1 = fixed_slots[fixed_parent]
                p2 = bl
                parent_combos_to_explore.append( (p1, p2) if fixed_parent == 'parent1' else (p2, p1) )
        else:
            parent_combos_to_explore.append( (fixed_slots['parent1'], fixed_slots['parent2']) )

        processed_parent_count = 0
        for p_combo in parent_combos_to_explore:
            if is_exploration_cancelled.is_set():
                print("--- 探索が中断されました ---")
                return jsonify({"error": "探索が中止されました"}), 500

            p1 = p_combo[0]
            p2 = p_combo[1]
            c_val = part_c_lookup.get(tuple(sorted((p1, p2))), None)
            if c_val is None: continue
            
            exploring_grandparents = [key for key in ['grandpa1', 'grandma1', 'grandpa2', 'grandma2'] if fixed_slots[key] is None]
            
            grandparent_combos = []
            if exploring_grandparents:
                grandparent_combos = list(itertools.product(explorable_bloodlines, repeat=len(exploring_grandparents)))
            else:
                grandparent_combos = [[]]

            for gp_combo in grandparent_combos:
                if is_exploration_cancelled.is_set():
                    print("--- 探索が中断されました ---")
                    return jsonify({"error": "探索が中止されました"}), 500

                current_fixed_slots = fixed_slots.copy()
                for i, key in enumerate(exploring_grandparents):
                    current_fixed_slots[key] = gp_combo[i]

                gp1 = current_fixed_slots['grandpa1']
                gm1 = current_fixed_slots['grandma1']
                gp2 = current_fixed_slots['grandpa2']
                gm2 = current_fixed_slots['grandma2']
                child = current_fixed_slots['child']
                
                a_val = part_affinity_lookup.get((p1, gp1, gm1, child), None)
                b_val = part_affinity_lookup.get((p2, gp2, gm2, child), None)
                
                if a_val is not None and b_val is not None:
                    total_affinity = a_val + b_val + c_val + fixed_bonus
                    if total_affinity > best_affinity:
                        best_affinity = total_affinity
                        
                        best_combination_slots = {
                            'parent1': p1, 'grandpa1': gp1, 'grandma1': gm1,
                            'parent2': p2, 'grandpa2': gp2, 'grandma2': gm2
                        }
                        best_combination = {key: val for key, val in best_combination_slots.items() if key in exploring_slot_keys}
                        
            processed_parent_count += 1
            if processed_parent_count % 100 == 0:
                print(f"  -> 親ペア候補を {processed_parent_count} 件処理中...", end='\r')

        print("\n--- 探索完了 ---")
        if best_combination:
            result = {
                'best_affinity': best_affinity,
                'combination': best_combination
            }
            return jsonify([result])
        else:
            return jsonify([])

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
            sample_size = 500000
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
            
            summary_key_parts = [f"{key}:{current_fixed_slots[key]}" for key in exploring_slot_keys]
            summary_key = " / ".join(summary_key_parts)
            
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
                'parent_bloodline': key,
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