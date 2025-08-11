from flask import Flask, render_template, request, redirect, url_for
import itertools
import json
import os # ファイル操作のためにインポート

# ---------------------------------
# 1. クラス定義 (データ構造)
# ---------------------------------

# 秘伝の情報を保持するクラス
class Hiden:
    def __init__(self, category, name, rank):
        self.category = category
        self.name = name
        self.rank = rank

# モンスターの情報を保持するクラス
class Monster:
    def __init__(self, name, monster_id, hidens):
        self.name = name
        self.monster_id = int(monster_id) # IDは整数として保存
        self.hidens = hidens

# 親と祖父母のセットを管理するクラス
class ParentSet:
    def __init__(self, parent, grandpa, grandma):
        self.parent = parent
        self.grandpa = grandpa
        self.grandma = grandma
        self.common_hiden = self.calculate_common_hiden()

    def calculate_common_hiden(self):
        white_hidens = [h for h in self.parent.hidens if h.category == "白秘伝"]
        white_hidens.extend([h for h in self.grandpa.hidens if h.category == "白秘伝"])
        white_hidens.extend([h for h in self.grandma.hidens if h.category == "白秘伝"])
        hiden_counts = {}
        for h in white_hidens:
            hiden_counts[h.name] = hiden_counts.get(h.name, 0) + 1
        common_iii = sum(1 for count in hiden_counts.values() if count == 3)
        common_ii = sum(1 for count in hiden_counts.values() if count == 2)
        return {"Ⅲ": common_iii, "Ⅱ": common_ii}

# 父親セットと母親セットの組み合わせを管理するクラス
class Combination:
    def __init__(self, father_set, mother_set):
        self.father_set = father_set
        self.mother_set = mother_set
        self.total_hidens = self.get_total_hidens()
        self.green_stars, self.red_stars = self.calculate_green_and_red_stars()
        self.common_iii = father_set.common_hiden["Ⅲ"] + mother_set.common_hiden["Ⅲ"]
        self.common_ii = father_set.common_hiden["Ⅱ"] + mother_set.common_hiden["Ⅱ"]
        self.nora_hidens = self.get_nora_hidens_count() 

    def get_total_hidens(self):
        all_hidens = (
            self.father_set.parent.hidens + 
            self.father_set.grandpa.hidens + 
            self.father_set.grandma.hidens +
            self.mother_set.parent.hidens + 
            self.mother_set.grandpa.hidens + 
            self.mother_set.grandma.hidens
        )
        return all_hidens
    
    def calculate_green_and_red_stars(self):
        green_stars = {}
        red_stars = 0
        for hiden in self.total_hidens:
            stars = rank_to_stars.get(hiden.rank, 0)
            if hiden.category == "緑秘伝":
                green_stars[hiden.name] = green_stars.get(hiden.name, 0) + stars
            elif hiden.category == "赤秘伝":
                red_stars += stars
        return green_stars, red_stars

    # ノラモン秘伝のカウントを返すように修正
    def get_nora_hidens_count(self):
        nora_hiden_counts = {}
        for h in self.total_hidens:
            if h.category == "ノラモン秘伝":
                nora_hiden_counts[h.name] = nora_hiden_counts.get(h.name, 0) + 1
        return nora_hiden_counts

    def get_green_rank_up(self, stars):
        if stars >= 16: return 6
        elif stars >= 13: return 5
        elif stars >= 10: return 4
        elif stars >= 7: return 3
        elif stars >= 4: return 2
        elif stars >= 1: return 1
        else: return 0

# ---------------------------------
# 2. 秘伝のマスターデータ作成
# ---------------------------------

# ランクを数値に変換する辞書
rank_to_stars = {"★★★": 3, "★★☆": 2, "★☆☆": 1, None: 0}

# 秘伝のマスターデータを格納する辞書
hiden_master_data = {}
# カテゴリ別に秘伝名を整理し、Hidenオブジェクトを格納する辞書 (Python内部で使用)
hiden_master_data_by_category = {}

def add_hiden(category, name, rank):
    key = f"{category}_{name}_{rank}"
    hiden = Hiden(category, name, rank)
    hiden_master_data[key] = hiden
    
    if category not in hiden_master_data_by_category:
        hiden_master_data_by_category[category] = {}
    if name not in hiden_master_data_by_category[category]:
        hiden_master_data_by_category[category][name] = []
    hiden_master_data_by_category[category][name].append(hiden)

# WebテンプレートにJSONとして渡すための、秘伝マスターデータのシリアライズ可能なバージョンを生成
def get_json_serializable_hiden_data():
    json_data = {}
    # カテゴリの表示順を定義 (実際のゲーム順があればここを調整)
    # なければ、キーのソート順でOK
    ordered_categories = [
        "青秘伝", "緑秘伝", "赤秘伝", "白秘伝", 
        "ノラモン秘伝", "モン類秘伝", "六天将秘伝"
    ]
    
    for category in ordered_categories:
        if category in hiden_master_data_by_category:
            json_data[category] = {}
            # 秘伝名の表示順も定義 (実際のゲーム順があればここを調整)
            # なければ、キーのソート順でOK
            ordered_names = sorted(hiden_master_data_by_category[category].keys()) # とりあえずアルファベット順
            
            for name in ordered_names:
                hiden_objects_from_master = hiden_master_data_by_category[category][name]
                
                # ここでhiden_objects_from_masterがリストであることを確認し、そうでない場合はリストでラップ
                if not isinstance(hiden_objects_from_master, list):
                    # 予期せぬデータ型の場合（例：単一のHidenオブジェクトが誤って格納された場合）
                    print(f"Warning: Expected list for {category} - {name}, but got {type(hiden_objects_from_master)}. Wrapping in list.")
                    if isinstance(hiden_objects_from_master, Hiden):
                        hiden_objects = [hiden_objects_from_master]
                    else:
                        hiden_objects = [] # 処理できない場合は空リスト
                else:
                    hiden_objects = hiden_objects_from_master # 期待通りのリストであればそのまま使用

                json_data[category][name] = [
                    {"category": h.category, "name": h.name, "rank": h.rank}
                    for h in hiden_objects
                ]
    return json_data

# --- 各秘伝の定義 ---
# ここで秘伝の定義順序を、ゲーム内の表示順に近づけることができます。
# 例: 青秘伝 -> 緑秘伝 -> 赤秘伝 -> 白秘伝 -> ノラモン秘伝 -> モン類秘伝 -> 六天将秘伝

# 青秘伝
blue_hidens = ["ライフ", "ちから", "かしこさ", "命中", "回避", "丈夫さ"]
for name in blue_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("青秘伝", name, rank)

# 緑秘伝 (ゲーム内の表示順があればここに反映)
green_hidens_list = ["火山", "海岸", "雪山", "砂漠", "森林", "零距離", "近距離", "中距離", "遠距離"]
for name in green_hidens_list:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("緑秘伝", name, rank)

# 赤秘伝
red_hidens = ["零距離", "近距離", "中距離", "遠距離"]
for name in red_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("赤秘伝", name, rank)

white_hidens = ["四大大会制覇", "星統べる六天", "モンスターダービー", "グレイテスト4", "M-1グランプリ", "ウィナーズ", "ワールドモンスターズ", "英雄秘伝(赤)", "英雄秘伝(青)", "英雄秘伝(黄)", "英雄秘伝(緑)", "英雄秘伝(白)", "英雄秘伝(黒)", "傷だらけのプライド"]
for name in white_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("白秘伝", name, rank)

# ノラモン秘伝
nora_hidens = ["ニャー", "サンドゴーレム", "マグマハート", "ハム", "ムネンド", "グジラキング", "ディノ", "カムイ", "フェニックス", "プラント", "スピナー", "スナイプ", "シロゾー"]
for name in nora_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("ノラモン秘伝", name, rank)

# モン類秘伝
monrui_hidens = ["無機", "創造", "幻霊", "魔族", "獣", "怪物"]
for name in monrui_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("モン類秘伝", name, rank)

for rank in ["★★★", "★★☆", "★☆☆"]:
    add_hiden("六天将秘伝", "六天将", rank)


# ---------------------------------
# 3. シミュレーション関数
# ---------------------------------

def get_green_rank_up(stars):
    if stars >= 16: return 6
    elif stars >= 13: return 5
    elif stars >= 10: return 4
    elif stars >= 7: return 3
    elif stars >= 4: return 2
    elif stars >= 1: return 1
    else: return 0

def search_combinations(target_green_hidens, parent_sets_to_choose):
    found_combinations = []
    all_parent_set_pairs = itertools.combinations(parent_sets_to_choose, 2)
    for father_set, mother_set in all_parent_set_pairs:
        if father_set.parent.monster_id == mother_set.parent.monster_id: # 親が同じIDでないことを確認
            continue
        current_combination = Combination(father_set, mother_set)
        green_stars, _ = current_combination.calculate_green_and_red_stars()
        is_match = True
        for hiden_name, target_rank in target_green_hidens.items():
            stars = green_stars.get(hiden_name, 0)
            if get_green_rank_up(stars) < target_rank:
                is_match = False
                break
        if is_match:
            found_combinations.append(current_combination)
    return found_combinations

# ---------------------------------
# 4. データ永続化の関数
# ---------------------------------

DATA_FILE = 'simulator_data.json' # データを保存するファイル名

# オブジェクトを辞書に変換するヘルパー関数 (JSONシリアライズ用)
def obj_to_dict(obj):
    if isinstance(obj, Hiden):
        return {"__Hiden__": True, "category": obj.category, "name": obj.name, "rank": obj.rank}
    if isinstance(obj, Monster):
        return {"__Monster__": True, "name": obj.name, "monster_id": obj.monster_id, "hidens": [obj_to_dict(h) for h in obj.hidens]}
    # ParentSetは、モンスターIDのみを保存し、ロード時に再構築する
    if isinstance(obj, ParentSet):
        return {
            "__ParentSet__": True,
            "parent_id": obj.parent.monster_id,
            "grandpa_id": obj.grandpa.monster_id,
            "grandma_id": obj.grandma.monster_id
        }
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

# 辞書をオブジェクトに変換するヘルパー関数 (JSONデシリアライズ用)
def dict_to_obj(dct):
    # ★ 修正箇所: dctが辞書でない場合はそのまま返す (TypeError回避)
    if not isinstance(dct, dict):
        return dct 

    if "__Hiden__" in dct:
        return Hiden(dct["category"], dct["name"], dct["rank"])
    if "__Monster__" in dct:
        hidens_data = dct.get("hidens", [])
        reconstructed_hidens = []
        if isinstance(hidens_data, list):
            for h_item in hidens_data:
                # h_itemが辞書であれば再帰的にdict_to_objを呼び出す
                if isinstance(h_item, dict):
                    reconstructed_hidens.append(dict_to_obj(h_item))
                # h_itemがすでにHidenオブジェクトであればそのまま追加
                elif isinstance(h_item, Hiden):
                    reconstructed_hidens.append(h_item)
        return Monster(dct["name"], dct["monster_id"], reconstructed_hidens)
    if "__ParentSet__" in dct:
        return dct 
    return dct

def save_data(monsters_data, parent_sets_data):
    data = {
        "monsters": [obj_to_dict(m) for m in monsters_data],
        "parent_sets": [obj_to_dict(ps) for ps in parent_sets_data],
        "next_monster_id": next_monster_id 
    }
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print("データが保存されました。")

def load_data():
    global my_monsters, parent_sets, next_monster_id
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f, object_hook=dict_to_obj)
        
        # モンスターデータをロード
        my_monsters = [dict_to_obj(m) for m in data.get('monsters', [])]
        
        # 次のモンスターIDをロード
        next_monster_id = data.get('next_monster_id', 1001)

        # parent_setsをロードし、Monsterオブジェクトを再リンク
        loaded_parent_sets_dicts = data.get('parent_sets', [])
        parent_sets = []
        monster_map_by_id = {m.monster_id: m for m in my_monsters}
        
        for ps_dict in loaded_parent_sets_dicts:
            try:
                parent = monster_map_by_id.get(ps_dict['parent_id'])
                grandpa = monster_map_by_id.get(ps_dict['grandpa_id'])
                grandma = monster_map_by_id.get(ps_dict['grandma_id'])
                
                # 削除されたモンスターが親セットに紐づいている可能性も考慮
                if all([parent, grandpa, grandma]):
                    parent_sets.append(ParentSet(parent, grandpa, grandma))
            except KeyError:
                print(f"警告: 存在しないモンスターIDを含む親セットが見つかりました: {ps_dict}")
                continue 

    else:
        print("データファイルが見つかりませんでした。新規作成します。")
        my_monsters = []
        parent_sets = []
        next_monster_id = 1001 

# ---------------------------------
# 5. Flaskアプリケーションの定義
# ---------------------------------
app = Flask(__name__)

# グローバル変数としてモンスターと親セットを定義
my_monsters = []
parent_sets = []
next_monster_id = 1001 

# アプリケーション起動時にデータをロード
load_data()

@app.route('/')
def home():
    return render_template(
        'home.html', 
        all_monsters=my_monsters, 
        parent_sets=parent_sets,
        hiden_master_data_by_category=get_json_serializable_hiden_data(),
        green_hiden_names=green_hidens_list 
    )

@app.route('/register_monster', methods=['POST'])
def register_monster():
    global next_monster_id 
    name = request.form['monster_name']
    
    # IDの自動割り当て
    # 既存のIDをチェックして、最大のID+1を割り当てる (欠番は埋めないシンプルな方式)
    existing_ids = {m.monster_id for m in my_monsters}
    if existing_ids:
        new_monster_id = max(existing_ids) + 1
    else:
        new_monster_id = 1001 

    # IDが既に登録されていないかチェック (自動割り当てなので基本不要だが念のため)
    if any(m.monster_id == new_monster_id for m in my_monsters):
        print(f"警告: ID {new_monster_id} はすでに存在します。")
        return redirect(url_for('home'))

    hidens_to_add = []
    categories = request.form.getlist('hiden_category')
    names = request.form.getlist('hiden_name')
    ranks = request.form.getlist('hiden_rank')

    for i in range(len(categories)):
        category = categories[i]
        hiden_name = names[i]
        rank = ranks[i]
        
        if category and hiden_name and rank: 
            hiden_key = f"{category}_{hiden_name}_{rank}"
            if hiden_key in hiden_master_data:
                hidens_to_add.append(hiden_master_data[hiden_key])

    new_monster = Monster(name, new_monster_id, hidens_to_add)
    my_monsters.append(new_monster)
    
    # データ保存
    save_data(my_monsters, parent_sets)

    return redirect(url_for('home'))

@app.route('/delete_monster', methods=['POST'])
def delete_monster():
    monster_id_to_delete = int(request.form['monster_id'])

    global my_monsters, parent_sets
    my_monsters = [m for m in my_monsters if m.monster_id != monster_id_to_delete]
    
    parent_sets = [
        ps for ps in parent_sets 
        if ps.parent.monster_id != monster_id_to_delete and 
           ps.grandpa.monster_id != monster_id_to_delete and 
           ps.grandma.monster_id != monster_id_to_delete
    ]
    
    # データ保存
    save_data(my_monsters, parent_sets)

    return redirect(url_for('home'))

@app.route('/register_parent_set', methods=['POST'])
def register_parent_set():
    parent_id = int(request.form['parent_monster'])
    grandpa_id = int(request.form['grandpa_monster'])
    grandma_id = int(request.form['grandma_monster'])
    
    monster_map_by_id = {m.monster_id: m for m in my_monsters} 
    
    parent = monster_map_by_id.get(parent_id)
    grandpa = monster_map_by_id.get(grandpa_id)
    grandma = monster_map_by_id.get(grandma_id)
    
    if len(set([parent_id, grandpa_id, grandma_id])) != 3:
        return redirect(url_for('home'))
    
    if not all([parent, grandpa, grandma]):
        return redirect(url_for('home'))

    new_parent_set = ParentSet(parent, grandpa, grandma)
    parent_sets.append(new_parent_set)
    
    # データ保存
    save_data(my_monsters, parent_sets)

    return redirect(url_for('home'))

@app.route('/delete_parent_set', methods=['POST'])
def delete_parent_set():
    try:
        index_to_delete = int(request.form['parent_set_index'])
        if 0 <= index_to_delete < len(parent_sets):
            parent_sets.pop(index_to_delete)
            # データ保存
            save_data(my_monsters, parent_sets)
    except (ValueError, IndexError):
        pass
    return redirect(url_for('home'))

@app.route('/run_simulation', methods=['POST'])
def run_simulation():
    target_green_hidens = {}
    for i in range(6): 
        hiden_name = request.form.get(f'search_hiden_name_{i}')
        rank_up_str = request.form.get(f'search_rank_up_{i}')
        
        if hiden_name and rank_up_str:
            try:
                target_green_hidens[hiden_name] = int(rank_up_str)
            except ValueError:
                pass

    if not parent_sets:
        return render_template('results.html', results=[], error_message="親セットが登録されていません。")
    
    if not target_green_hidens:
        return render_template('results.html', results=[], error_message="検索条件が設定されていません。")

    results = search_combinations(target_green_hidens, parent_sets)

    return render_template('results.html', results=results, get_green_rank_up=get_green_rank_up)

