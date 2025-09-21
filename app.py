import pandas as pd
from flask import Flask, request, jsonify, render_template, g
import itertools
import random
from threading import Event
from collections import defaultdict
import heapq
import uuid

app = Flask(__name__)

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
    # monsters.xlsxの読み込み
    monsters_df = pd.read_excel('monsters.xlsx')
    monsters_by_category = defaultdict(list)
    for _, row in monsters_df.iterrows():
        monsters_by_category[row['モン類']].append(row['主血統'])

except FileNotFoundError:
    print("エラー: 必要なファイルが見つかりません。アプリケーションを終了します。")
    exit()

@app.route('/monsters_data', methods=['GET'])
def get_monsters_data():
    """モンスターデータをJSON形式で返すエンドポイント"""
    return jsonify(monsters_df.to_dict(orient='records'))

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

# 非対称辞書 (順序を保持)
part_c_lookup_asymmetric = part_c_df.set_index(['parent1_bloodline', 'parent2_bloodline']).to_dict()['c_affinity']
# 対称辞書 (ソート済み)
part_c_df['sorted_parents'] = part_c_df.apply(lambda row: tuple(sorted((row['parent1_bloodline'], row['parent2_bloodline']))), axis=1)
part_c_lookup_symmetric = part_c_df.set_index('sorted_parents').to_dict()['c_affinity']

# 20250829改修: C値を高い順にソートした親ペアリストを事前構築
sorted_c_pairs = part_c_df.sort_values('c_affinity', ascending=False)[['parent1_bloodline', 'parent2_bloodline']].values.tolist()

# B値とA値のルックアップ
part_affinity_lookup = part_affinity_df.set_index(['parent_bloodline', 'grandpa_bloodline', 'grandma_bloodline', 'child_bloodline']).to_dict()['main_affinity']

# 親と子から最適な祖父母を見つけるためのルックアップを事前に計算
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

# ヘルパー関数: C値を取得
def get_c_value(p1, p2):
    # 非対称辞書を優先して検索
    val = part_c_lookup_asymmetric.get((p1, p2))
    if val is not None:
        return val
    # 見つからなければ対称辞書を検索
    return part_c_lookup_symmetric.get(tuple(sorted((p1, p2))))

# ヘルパー関数: A値またはB値を取得 (祖父母の最適化も含む)
def get_ab_value(parent, child, fixed_gp=None, fixed_gm=None, excluded_monsters=None):
    # 固定された祖父母が両方指定されている場合は、その値をそのまま使用
    if fixed_gp is not None and fixed_gm is not None:
        return part_affinity_lookup.get((parent, fixed_gp, fixed_gm, child), -1), fixed_gp, fixed_gm

    base_ab_val, base_gp, base_gm = best_ab_lookup.get((parent, child), (None, None, None))
    
    # 既存のロジックを簡潔に修正
    max_affinity = -1
    best_gp = None
    best_gm = None
    
    # 祖父母の候補リストを、固定値と除外リストを考慮して作成
    gp_candidates = [fixed_gp] if fixed_gp is not None else [bl for bl in all_bloodlines if bl not in excluded_monsters]
    gm_candidates = [fixed_gm] if fixed_gm is not None else [bl for bl in all_bloodlines if bl not in excluded_monsters]
    
    if not gp_candidates or not gm_candidates:
        return -1, None, None

    for gp_new, gm_new in itertools.product(gp_candidates, gm_candidates):
        affinity = part_affinity_lookup.get((parent, gp_new, gm_new, child), None)
        if affinity is not None and affinity > max_affinity:
            max_affinity = affinity
            best_gp = gp_new
            best_gm = gm_new

    return max_affinity, best_gp, best_gm

# ヘルパー関数: 総相性値を計算
def calculate_affinity(child, p1, p2, gp1, gm1, gp2, gm2, fixed_bonus):
    c_val = get_c_value(p1, p2)
    a_val = part_affinity_lookup.get((p1, gp1, gm1, child), None)
    b_val = part_affinity_lookup.get((p2, gp2, gm2, child), None)
    
    if c_val is not None and a_val is not None and b_val is not None:
        return a_val + b_val + c_val + fixed_bonus
    return -1

@app.route('/')
def index():
    main_bloodlines = sorted(part_affinity_df['child_bloodline'].cat.categories.tolist())
    target_symbols = list(TARGET_AFFINITY_SCORES.keys())
    monster_categories = sorted(monsters_by_category.keys())
    return render_template('index.html', bloodlines=main_bloodlines, target_symbols=target_symbols, monster_categories=monster_categories, monsters_by_category=dict(monsters_by_category))

@app.route('/api/search', methods=['POST'])
def explore_combinations():
    data = request.json
    
    common_secret_iii = int(data.get('common_secret_iii', 0))
    common_secret_ii = int(data.get('common_secret_ii', 0))
    target_symbol = data.get('target_symbol', '◎')
    target_affinity_value = data.get('target_affinity_value', None)
    excluded_monsters = set(data.get('excluded_monsters', []))
    limit = int(data.get('limit', 50))
    
    fixed_slots = {
        'child': data.get('child', []),
        'parent1': data.get('parent1', None),
        'grandpa1': data.get('grandpa1', None),
        'grandma1': data.get('grandma1', None),
        'parent2': data.get('parent2', None),
        'grandpa2': data.get('grandpa2', None),
        'grandma2': data.get('grandma2', None)
    }

    common_secret_bonus = (common_secret_iii * COMMON_SECRET_III_BONUS) + (common_secret_ii * COMMON_SECRET_II_BONUS)
    fixed_bonus = common_secret_bonus + SUB_BLOODLINE_RARE_BONUS

    if target_affinity_value is not None and target_affinity_value != '':
        try:
            target_min = float(target_affinity_value)
        except (ValueError, TypeError):
            target_min, _ = TARGET_AFFINITY_SCORES.get(target_symbol, (496, 614))
    else:
        target_min, _ = TARGET_AFFINITY_SCORES.get(target_symbol, (496, 614))

    all_bloodlines = part_affinity_df['child_bloodline'].cat.categories.tolist()

    # --- 修正箇所: 新しい探索モードを追加 ---
    is_all_parents_fixed = (
        fixed_slots['parent1'] is not None and
        fixed_slots['grandpa1'] is not None and
        fixed_slots['grandma1'] is not None and
        fixed_slots['parent2'] is not None and
        fixed_slots['grandpa2'] is not None and
        fixed_slots['grandma2'] is not None
    )

    if len(fixed_slots['child']) == 1 and is_all_parents_fixed:
        print("--- 子1体と全ての親祖父母が固定されているため、単一の相性値を計算します ---")
        child_bl = fixed_slots['child'][0]
        total_affinity = calculate_affinity(
            child_bl,
            fixed_slots['parent1'], fixed_slots['parent2'],
            fixed_slots['grandpa1'], fixed_slots['grandma1'],
            fixed_slots['grandpa2'], fixed_slots['grandma2'],
            fixed_bonus
        )
        
        if total_affinity != -1:
            result = {
                'total_affinity': total_affinity,
                'combination': fixed_slots,
                'mode': 'FixedChildAndParents'
            }
            return jsonify([result])
        else:
            return jsonify([])

    # ここからマルチ探索ロジックの統合
    if len(fixed_slots['child']) >= 2:
        print("--- マルチモード探索開始 ---")

        # 修正箇所: 探索対象の候補リストをユーザーの固定値を考慮して生成
        p1_candidates = [fixed_slots['parent1']] if fixed_slots['parent1'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
        gp1_candidates = [fixed_slots['grandpa1']] if fixed_slots['grandpa1'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
        gm1_candidates = [fixed_slots['grandma1']] if fixed_slots['grandma1'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
        p2_candidates = [fixed_slots['parent2']] if fixed_slots['parent2'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
        gp2_candidates = [fixed_slots['grandpa2']] if fixed_slots['grandpa2'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
        gm2_candidates = [fixed_slots['grandma2']] if fixed_slots['grandma2'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]

        best_min_affinity = -1
        best_combination = None
        
        # 総計算量の計算を修正
        total_calculations = len(p1_candidates) * len(gp1_candidates) * len(gm1_candidates) * len(p2_candidates) * len(gp2_candidates) * len(gm2_candidates)

        EXPLORATION_THRESHOLD = 250_000
        is_fast_mode = total_calculations > EXPLORATION_THRESHOLD

        if is_fast_mode:
            sample_size = min(20000, total_calculations)
            
            top_c_pairs_count = min(1000, len(sorted_c_pairs) // 30)
            
            # 修正箇所: 親ペアのフィルタリングを修正
            filtered_c_pairs = [
                pair for pair in sorted_c_pairs[:top_c_pairs_count] 
                if (fixed_slots['parent1'] is None or pair[0] == fixed_slots['parent1']) and
                   (fixed_slots['parent2'] is None or pair[1] == fixed_slots['parent2']) and
                   (pair[0] not in excluded_monsters) and (pair[1] not in excluded_monsters)
            ]
            
            if fixed_slots['parent1'] and fixed_slots['parent2'] and (fixed_slots['parent1'], fixed_slots['parent2']) not in filtered_c_pairs:
                filtered_c_pairs.append((fixed_slots['parent1'], fixed_slots['parent2']))

            print(f"総計算量 ({total_calculations}) が閾値 ({EXPLORATION_THRESHOLD}) を超えたため、C値上位 {len(filtered_c_pairs)} 件の親ペアと高速モードで探索します（{sample_size}件の組み合わせをサンプリング）。")
            
            # 修正箇所: 探索イテレータの生成ロジック
            exploration_iterator = (
                (
                    random.choice(p1_candidates),
                    random.choice(gp1_candidates),
                    random.choice(gm1_candidates),
                    random.choice(p2_candidates),
                    random.choice(gp2_candidates),
                    random.choice(gm2_candidates)
                ) for _ in range(sample_size)
            )

        else:
            # 修正箇所: 変数名をtotal_calculationsに変更
            print(f"総計算量 ({total_calculations}) が閾値 ({EXPLORATION_THRESHOLD}) 以内のため、網羅的探索を実行します。")
            exploration_iterator = itertools.product(p1_candidates, gp1_candidates, gm1_candidates, p2_candidates, gp2_candidates, gm2_candidates)

        for combo in exploration_iterator:
            p1_cand, gp1_cand, gm1_cand, p2_cand, gp2_cand, gm2_cand = combo

            c_val = get_c_value(p1_cand, p2_cand)
            if c_val is None:
                continue
            
            min_affinity_for_this_combo = float('inf')
            valid_combo = True
            
            for child_bl in fixed_slots['child']:
                total_affinity = calculate_affinity(
                    child_bl,
                    p1_cand, p2_cand,
                    gp1_cand, gm1_cand,
                    gp2_cand, gm2_cand,
                    fixed_bonus
                )
                
                if total_affinity != -1:
                    min_affinity_for_this_combo = min(min_affinity_for_this_combo, total_affinity)
                else:
                    valid_combo = False
                    break
            
            if valid_combo and min_affinity_for_this_combo > best_min_affinity:
                best_min_affinity = min_affinity_for_this_combo
                best_combination = {
                    'parent1': p1_cand,
                    'grandpa1': gp1_cand,
                    'grandma1': gm1_cand,
                    'parent2': p2_cand,
                    'grandpa2': gp2_cand,
                    'grandma2': gm2_cand
                }

        print("\n--- マルチモード探索完了 ---")
        if best_combination:
            all_children_affinities = {}
            for child_bl in fixed_slots['child']:
                total_affinity = calculate_affinity(
                    child_bl,
                    best_combination['parent1'], best_combination['parent2'],
                    best_combination['grandpa1'], best_combination['grandma1'],
                    best_combination['grandpa2'], best_combination['grandma2'],
                    fixed_bonus
                )
                all_children_affinities[child_bl] = {
                    'affinity': total_affinity,
                }
            
            # マルチ探索の結果を返す
            return jsonify([{
                'min_affinity': best_min_affinity,
                'combination': best_combination,
                'children_details': all_children_affinities,
                'mode': 'Multi'
            }])
        else:
            return jsonify([])
    
    # ここから元の/exploreロジック
    
    # 修正箇所: 探索対象の候補リストを動的に生成
    p1_candidates = [fixed_slots['parent1']] if fixed_slots['parent1'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
    p2_candidates = [fixed_slots['parent2']] if fixed_slots['parent2'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
    gp1_candidates = [fixed_slots['grandpa1']] if fixed_slots['grandpa1'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
    gm1_candidates = [fixed_slots['grandma1']] if fixed_slots['grandma1'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
    gp2_candidates = [fixed_slots['grandpa2']] if fixed_slots['grandpa2'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
    gm2_candidates = [fixed_slots['grandma2']] if fixed_slots['grandma2'] else [bl for bl in all_bloodlines if bl not in excluded_monsters]
    
    # 親祖父母全て固定 (子が指定されていない場合)
    if not fixed_slots['child'] and is_all_parents_fixed:
        print("--- 全ての親が固定されているため、サマリーを生成します ---")
        summary_results = []
        c_val = get_c_value(fixed_slots['parent1'], fixed_slots['parent2'])
        if c_val is None:
            return jsonify([])

        for child_bl in all_bloodlines:
            total_affinity = calculate_affinity(child_bl, fixed_slots['parent1'], fixed_slots['parent2'], fixed_slots['grandpa1'], fixed_slots['grandma1'], fixed_slots['grandpa2'], fixed_slots['grandma2'], fixed_bonus)
            if total_affinity != -1:
                summary_results.append({
                    'child_bloodline': child_bl,
                    'total_affinity': total_affinity,
                    'is_matched': total_affinity >= target_min,
                    'mode': 'FixedParentsAllChildren'
                })
        summary_results.sort(key=lambda x: x['total_affinity'], reverse=True)
        return jsonify(summary_results)
    
    if len(fixed_slots['child']) == 1:
        print("--- 子が1体指定されているため、ヒューリスティック探索を実行します ---")
        best_affinity = -1
        best_combination = None
        
        child_bl = fixed_slots['child'][0]
        
        processed_count = 0
        for p1_cand, p2_cand in itertools.product(p1_candidates, p2_candidates):
            c_val = get_c_value(p1_cand, p2_cand)
            if c_val is None:
                continue

            best_a_val, best_gp1, best_gm1 = get_ab_value(
                parent=p1_cand,
                child=child_bl,
                fixed_gp=fixed_slots['grandpa1'],
                fixed_gm=fixed_slots['grandma1'],
                excluded_monsters=excluded_monsters
            )
            
            best_b_val, best_gp2, best_gm2 = get_ab_value(
                parent=p2_cand,
                child=child_bl,
                fixed_gp=fixed_slots['grandpa2'],
                fixed_gm=fixed_slots['grandma2'],
                excluded_monsters=excluded_monsters
            )
            
            if best_a_val != -1 and best_b_val != -1:
                total_affinity = best_a_val + best_b_val + c_val + fixed_bonus
                if total_affinity > best_affinity:
                    best_affinity = total_affinity
                    best_combination = {
                        'parent1': p1_cand, 'grandpa1': best_gp1, 'grandma1': best_gm1,
                        'parent2': p2_cand, 'grandpa2': best_gp2, 'grandma2': best_gm2
                    }
            
            processed_count += 1

        print("\n--- ヒューリスティック探索完了 ---")
        if best_combination:
            result = {
                'affinity': best_affinity,
                'combination': best_combination,
                'mode': 'BestPairForChild'
            }
            return jsonify([result])
        else:
            return jsonify([])

    else:
        # 子が指定されていない場合
        print("--- 子が指定されていないため、サマリーを生成します ---")
        
        total_combinations = len(p1_candidates) * len(gp1_candidates) * len(gm1_candidates) * len(p2_candidates) * len(gp2_candidates) * len(gm2_candidates)
        
        EXPLORATION_THRESHOLD = 250_000
        is_fast_mode = total_combinations > EXPLORATION_THRESHOLD

        final_summary_list = [] # 網羅的探索用
        summary_heap = [] # 高速モード用
        
        if is_fast_mode:
            sample_size = min(20000, total_combinations)
            
            # --- 修正箇所: 親ペアのフィルタリングを追加 ---
            filtered_c_pairs = [
                pair for pair in sorted_c_pairs
                if (fixed_slots['parent1'] is None or pair[0] == fixed_slots['parent1']) and
                   (fixed_slots['parent2'] is None or pair[1] == fixed_slots['parent2']) and
                   (pair[0] not in excluded_monsters) and (pair[1] not in excluded_monsters)
            ]
            
            # ユーザーが特定の親ペアを固定した場合、そのペアを必ず探索対象に含める
            if fixed_slots['parent1'] and fixed_slots['parent2']:
                user_pair = (fixed_slots['parent1'], fixed_slots['parent2'])
                # 対称性も考慮してリストに存在しないかチェック
                if user_pair not in filtered_c_pairs and (user_pair[1], user_pair[0]) not in filtered_c_pairs:
                    filtered_c_pairs.insert(0, user_pair) # 先頭に追加して確実に探索させる

            # サンプリング対象リストをトップC値ペアと固定ペアに絞る
            top_c_pairs_count = min(1000, len(filtered_c_pairs) // 30)
            c_pairs_to_sample = filtered_c_pairs[:top_c_pairs_count]
            if not c_pairs_to_sample and fixed_slots['parent1'] and fixed_slots['parent2']:
                c_pairs_to_sample.append((fixed_slots['parent1'], fixed_slots['parent2']))

            print(f"総計算量 ({total_combinations}) が閾値 ({EXPLORATION_THRESHOLD}) を超えたため、C値上位 {len(c_pairs_to_sample)} 件の親ペアと高速モードで探索します（{sample_size}件の組み合わせをサンプリング）。")
            
            exploration_iterator = (
                (
                    parent_pair[0],
                    random.choice(gp1_candidates),
                    random.choice(gm1_candidates),
                    parent_pair[1],
                    random.choice(gp2_candidates),
                    random.choice(gm2_candidates)
                ) for parent_pair in random.choices(c_pairs_to_sample, k=sample_size)
            )

        else:
            print(f"総計算量 ({total_combinations}) が閾値 ({EXPLORATION_THRESHOLD}) 以内のため、網羅的探索を実行します。")
            exploration_iterator = itertools.product(p1_candidates, gp1_candidates, gm1_candidates, p2_candidates, gp2_candidates, gm2_candidates)

        for combo in exploration_iterator:
            p1, gp1, gm1, p2, gp2, gm2 = combo

            c_val = get_c_value(p1, p2)
            if c_val is None: continue
            
            max_affinity_for_combo = -1
            matched_children_count = 0

            for child_bl in all_bloodlines:
                a_val = part_affinity_lookup.get((p1, gp1, gm1, child_bl), -1)
                b_val = part_affinity_lookup.get((p2, gp2, gm2, child_bl), -1)
                
                if a_val != -1 and b_val != -1:
                    total_affinity = a_val + b_val + c_val + fixed_bonus
                    max_affinity_for_combo = max(max_affinity_for_combo, total_affinity)
                    if total_affinity >= target_min:
                        matched_children_count += 1
            
            if max_affinity_for_combo != -1:
                combination_data = {
                    'parent1': p1, 'grandpa1': gp1, 'grandma1': gm1,
                    'parent2': p2, 'grandpa2': gp2, 'grandma2': gm2
                }
                
                if is_fast_mode:
                    priority = (-matched_children_count, -max_affinity_for_combo) 
                    if len(summary_heap) < limit:
                        heapq.heappush(summary_heap, (priority, uuid.uuid4(), combination_data))
                    else:
                        current_priority = (-matched_children_count, -max_affinity_for_combo)
                        lowest_priority_tuple = summary_heap[0]
                        lowest_priority = lowest_priority_tuple[0]
                        if current_priority < lowest_priority:
                            heapq.heapreplace(summary_heap, (current_priority, uuid.uuid4(), combination_data))
                else:
                    final_summary_list.append({
                        'parent_bloodline': " / ".join(list(combination_data.values())),
                        'matches': matched_children_count,
                        'max_affinity': max_affinity_for_combo,
                        'combination': combination_data,
                        'mode': 'Summary'
                    })
        
        if is_fast_mode:
            temp_list = []
            while summary_heap:
                priority, _, combination = heapq.heappop(summary_heap)
                temp_list.append({
                    'parent_bloodline': " / ".join(list(combination.values())),
                    'matches': -priority[0],
                    'max_affinity': -priority[1],
                    'combination': combination,
                    'mode': 'Summary'
                })
            temp_list.sort(key=lambda x: (x['matches'], x['max_affinity']), reverse=True)
            final_summary_list = temp_list
        else:
            final_summary_list.sort(key=lambda x: (x['matches'], x['max_affinity']), reverse=True)
            final_summary_list = final_summary_list[:limit]

        print(f"\n--- 探索完了（サマリー生成）---")
        return jsonify(final_summary_list)


@app.route('/api/details', methods=['POST'])
def get_details():
    print("--- 詳細情報取得リクエストを受信 ---")
    data = request.json
     
    common_secret_iii = int(data.get('common_secret_iii', 0))
    common_secret_ii = int(data.get('common_secret_ii', 0))
     
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

    c_val = get_c_value(p1, p2)
    if c_val is None:
        return jsonify([])
 
    all_bloodlines = part_affinity_df['child_bloodline'].cat.categories.tolist()
 
    for child_bloodline in all_bloodlines:
        total_affinity = calculate_affinity(child_bloodline, p1, p2, gp1, gm1, gp2, gm2, fixed_bonus)
        
        detailed_results.append({
            'child_bloodline': child_bloodline,
            'total_affinity': total_affinity if total_affinity > 0 else None
        })
 
    print(f"--- 詳細情報取得完了 ---")
    return jsonify({'results': detailed_results})
    
if __name__ == '__main__':
    app.run(debug=True)