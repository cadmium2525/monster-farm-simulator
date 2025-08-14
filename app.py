from flask import Flask, render_template, request, redirect, url_for
import itertools
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore

# ---------------------------------
# 1. クラス定義 (データ構造)
# ---------------------------------

# 秘伝の情報を保持するクラス
class Hiden:
    def __init__(self, category, name, rank):
        self.category = category
        self.name = name
        self.rank = rank
    
    # Firestoreへの保存/読み込みのために辞書に変換するメソッド
    def to_dict(self):
        return {
            "category": self.category,
            "name": self.name,
            "rank": self.rank
        }

    @staticmethod
    def from_dict(data):
        return Hiden(data['category'], data['name'], data['rank'])

# モンスターの情報を保持するクラス
class Monster:
    def __init__(self, name, monster_id, hidens):
        self.name = name
        self.monster_id = int(monster_id) # IDは整数として保存
        self.hidens = hidens
    
    # Firestoreへの保存/読み込みのために辞書に変換するメソッド
    def to_dict(self):
        return {
            "name": self.name,
            "monster_id": self.monster_id,
            "hidens": [h.to_dict() for h in self.hidens]
        }
    
    @staticmethod
    def from_dict(data):
        return Monster(data['name'], data['monster_id'], [Hiden.from_dict(h) for h in data['hidens']])


# 親と祖父母のセットを管理するクラス
class ParentSet:
    def __init__(self, parent_monster_id, grandpa_monster_id, grandma_monster_id, all_monsters_map):
        # Monsterオブジェクト自体ではなく、IDを保持する
        self.parent_monster_id = parent_monster_id
        self.grandpa_monster_id = grandpa_monster_id
        self.grandma_monster_id = grandma_monster_id

        # 初期化時にMonsterオブジェクトへの参照を解決
        self.parent = all_monsters_map.get(parent_monster_id)
        self.grandpa = all_monsters_map.get(grandpa_monster_id)
        self.grandma = all_monsters_map.get(grandma_monster_id)

        # 共通秘伝の計算（参照が解決されていることを前提）
        self.common_hiden = self.calculate_common_hiden()

    def calculate_common_hiden(self):
        # Monsterオブジェクトが有効な場合のみ計算
        if not all([self.parent, self.grandpa, self.grandma]):
            return {"Ⅲ": 0, "Ⅱ": 0}

        white_hidens = [h for h in self.parent.hidens if h.category == "白秘伝"]
        white_hidens.extend([h for h in self.grandpa.hidens if h.category == "白秘伝"])
        white_hidens.extend([h for h in self.grandma.hidens if h.category == "白秘伝"])
        hiden_counts = {}
        for h in white_hidens:
            hiden_counts[h.name] = hiden_counts.get(h.name, 0) + 1
        common_iii = sum(1 for count in hiden_counts.values() if count == 3)
        common_ii = sum(1 for count in hiden_counts.values() if count == 2)
        return {"Ⅲ": common_iii, "Ⅱ": common_ii}
    
    # Firestoreへの保存/読み込みのために辞書に変換するメソッド
    def to_dict(self):
        return {
            "parent_monster_id": self.parent_monster_id,
            "grandpa_monster_id": self.grandpa_monster_id,
            "grandma_monster_id": self.grandma_monster_id
        }
    
    @staticmethod
    def from_dict(data, all_monsters_map):
        # データベースから読み込んだIDを使ってParentSetを再構築
        return ParentSet(
            data['parent_monster_id'],
            data['grandpa_monster_id'],
            data['grandma_monster_id'],
            all_monsters_map
        )


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
        # Monsterオブジェクトが有効な場合のみ秘伝を結合
        all_hidens = []
        if self.father_set.parent: all_hidens.extend(self.father_set.parent.hidens)
        if self.father_set.grandpa: all_hidens.extend(self.father_set.grandpa.hidens)
        if self.father_set.grandma: all_hidens.extend(self.father_set.grandma.hidens)
        if self.mother_set.parent: all_hidens.extend(self.mother_set.parent.hidens)
        if self.mother_set.grandpa: all_hidens.extend(self.mother_set.grandpa.hidens)
        if self.mother_set.grandma: all_hidens.extend(self.mother_set.grandma.hidens)
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

# 秘伝の種類の表示順序をグローバル変数として定義
ORDERED_HIDEN_CATEGORIES = [
    "青秘伝", 
    "緑秘伝", 
    "赤秘伝", 
    "白秘伝", 
    "ノラモン秘伝", 
    "モン類秘伝", 
    "六天将秘伝"
]

# ★追加: 各カテゴリーの秘伝名のカスタム表示順を定義する辞書
# ここで各カテゴリーの秘伝名を、あなたがプルダウンで表示したい順序でリストとして定義してください。
# 未定義のカテゴリーや秘伝名は、自動的にアルファベット順に追加されます。
CUSTOM_HIDEN_NAMES_ORDER = {
    "青秘伝": ["ライフ", "ちから", "かしこさ", "命中", "回避", "丈夫さ"],
    "緑秘伝": ["火山", "海岸", "雪山", "砂漠", "森林", "零距離", "近距離", "中距離", "遠距離"],
    "赤秘伝": ["零距離", "近距離", "中距離", "遠距離"],
    "白秘伝": ["四大大会制覇", "星統べる六天", "モンスターダービー", "グレイテスト4", 
               "M-1グランプリ", "ウィナーズ", "ワールドモンスターズ", 
               "六英雄杯・紅", "六英雄杯・蒼", "六英雄杯・琥", "六英雄杯・翠", 
               "六英雄杯・煌", "六英雄杯・冥", "傷だらけのプライド"],
    "ノラモン秘伝": ["ニャー", "サンドゴーレム", "マグマハート", "ハム", "ムネンド", 
                   "グジラキング", "ディノ", "カムイ", "フェニックス", "プラント", 
                   "スピナー", "スナイプ", "シロゾー"],
    "モン類秘伝": ["無機", "創造", "幻霊", "魔族", "獣", "怪物"],
    "六天将秘伝": ["六天将"] # 六天将は「六天将」秘伝のみなので、リスト形式で定義
}


# WebテンプレートにJSONとして渡すための、秘伝マスターデータのシリアライズ可能なバージョンを生成
def get_json_serializable_hiden_data():
    json_data = {}
    
    for category in ORDERED_HIDEN_CATEGORIES:
        if category in hiden_master_data_by_category:
            json_data[category] = {}
            
            # 実際にマスターデータに存在する秘伝名を取得
            available_names_in_category = list(hiden_master_data_by_category[category].keys())
            
            ordered_names = [] # 最終的な順序付き秘伝名リスト
            
            # ★修正点: CUSTOM_HIDEN_NAMES_ORDER を参照して順序を決定
            if category in CUSTOM_HIDEN_NAMES_ORDER:
                custom_order_template = CUSTOM_HIDEN_NAMES_ORDER[category]
                # カスタム順序の秘伝名を優先して追加 (マスターに存在する秘伝名のみ)
                for name_in_order in custom_order_template:
                    if name_in_order in available_names_in_category:
                        ordered_names.append(name_in_order)
                
                # カスタム順序に含まれていない、マスタに存在する秘伝名があれば、アルファベット順で追加
                remaining_names = sorted(list(set(available_names_in_category) - set(ordered_names)))
                ordered_names.extend(remaining_names)
            else:
                # CUSTOM_HIDEN_NAMES_ORDERに定義されていないカテゴリーはアルファベット順
                ordered_names = sorted(available_names_in_category)
            
            for name in ordered_names:
                hiden_objects_from_master = hiden_master_data_by_category[category][name]
                
                if not isinstance(hiden_objects_from_master, list):
                    print(f"Warning: Expected list for {category} - {name}, but got {type(hiden_objects_from_master)}. Wrapping in list.")
                    if isinstance(hiden_objects_from_master, Hiden):
                        hiden_objects = [hiden_objects_from_master]
                    else:
                        hiden_objects = [] 
                else:
                    hiden_objects = hiden_objects_from_master 

                json_data[category][name] = [
                    {"category": h.category, "name": h.name, "rank": h.rank}
                    for h in hiden_objects
                ]
    return json_data

# --- 各秘伝の定義 ---
# ここは秘伝データをシステムに登録する箇所です。
# 表示順序は上記の get_json_serializable_hiden_data() と CUSTOM_HIDEN_NAMES_ORDER で制御されます。

# 青秘伝
blue_hidens = CUSTOM_HIDEN_NAMES_ORDER["青秘伝"]
for name in blue_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("青秘伝", name, rank)

# 緑秘伝
green_hidens_list = CUSTOM_HIDEN_NAMES_ORDER["緑秘伝"] # home.htmlに渡すために変数名を維持
for name in green_hidens_list:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("緑秘伝", name, rank)

# 赤秘伝
red_hidens = CUSTOM_HIDEN_NAMES_ORDER["赤秘伝"]
for name in red_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("赤秘伝", name, rank)

white_hidens = CUSTOM_HIDEN_NAMES_ORDER["白秘伝"]
for name in white_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("白秘伝", name, rank)

# ノラモン秘伝
nora_hidens = CUSTOM_HIDEN_NAMES_ORDER["ノラモン秘伝"]
for name in nora_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("ノラモン秘伝", name, rank)

# モン類秘伝
monrui_hidens = CUSTOM_HIDEN_NAMES_ORDER["モン類秘伝"]
for name in monrui_hidens:
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("モン類秘伝", name, rank)

# 六天将秘伝
six_ten_hidens = CUSTOM_HIDEN_NAMES_ORDER["六天将秘伝"]
for name in six_ten_hidens: # 六天将秘伝は"六天将"のみ
    for rank in ["★★★", "★★☆", "★☆☆"]:
        add_hiden("六天将秘伝", name, rank)


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
        # Monsterオブジェクトが有効でない親セットはスキップ
        if not all([father_set.parent, father_set.grandpa, father_set.grandma,
                    mother_set.parent, mother_set.grandpa, mother_set.grandma]):
            continue

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
# 4. Flaskアプリケーションの定義
# ---------------------------------
app = Flask(__name__)

# Firebase初期化
try:
    service_account_json = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS_JSON')
    if service_account_json:
        cred_path = "/tmp/serviceAccountKey.json"
        with open(cred_path, "w") as f:
            f.write(service_account_json)
        
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK initialized successfully.")
    else:
        print("GOOGLE_APPLICATION_CREDENTIALS_JSON environment variable not found. Firebase will not be initialized.")
except Exception as e:
    print(f"Error initializing Firebase Admin SDK: {e}")

db = firestore.client()

def load_data_from_firestore():
    monsters = []
    parent_sets_data = [] 

    try:
        monsters_ref = db.collection('monsters').order_by('monster_id').get()
        for doc in monsters_ref:
            monster_data = doc.to_dict()
            monsters.append(Monster.from_dict(monster_data))
        print(f"Loaded {len(monsters)} monsters from Firestore.")
    except Exception as e:
        print(f"Error loading monsters from Firestore: {e}")
        monsters = [] 

    try:
        parent_sets_ref = db.collection('parent_sets').get()
        for doc in parent_sets_ref:
            parent_sets_data.append(doc.to_dict())
        print(f"Loaded {len(parent_sets_data)} parent sets data from Firestore.")
    except Exception as e:
        print(f"Error loading parent sets from Firestore: {e}")
        parent_sets_data = [] 
    
    monster_map_by_id = {m.monster_id: m for m in monsters}
    resolved_parent_sets = []
    for ps_data in parent_sets_data:
        resolved_parent_sets.append(ParentSet.from_dict(ps_data, monster_map_by_id))
    
    return monsters, resolved_parent_sets

def save_monster_to_firestore(monster):
    try:
        db.collection('monsters').document(str(monster.monster_id)).set(monster.to_dict())
        print(f"Monster {monster.name} (ID: {monster.monster_id}) saved to Firestore.")
    except Exception as e:
        print(f"Error saving monster {monster.name} to Firestore: {e}")

def delete_monster_from_firestore(monster_id):
    try:
        db.collection('monsters').document(str(monster_id)).delete()
        print(f"Monster ID: {monster_id} deleted from Firestore.")

        parent_sets_to_delete_ref = db.collection('parent_sets').where('parent_monster_id', '==', monster_id).get()
        for doc in parent_sets_to_delete_ref:
            doc.reference.delete()
            print(f"ParentSet {doc.id} (parent: {monster_id}) deleted from Firestore.")
        
        parent_sets_to_delete_ref = db.collection('parent_sets').where('grandpa_monster_id', '==', monster_id).get()
        for doc in parent_sets_to_delete_ref:
            doc.reference.delete()
            print(f"ParentSet {doc.id} (grandpa: {monster_id}) deleted from Firestore.")

        parent_sets_to_delete_ref = db.collection('parent_sets').where('grandma_monster_id', '==', monster_id).get()
        for doc in parent_sets_to_delete_ref:
            doc.reference.delete()
            print(f"ParentSet {doc.id} (grandma: {monster_id}) deleted from Firestore.")

    except Exception as e:
        print(f"Error deleting monster ID: {monster_id} from Firestore: {e}")

def save_parent_set_to_firestore(parent_set):
    try:
        db.collection('parent_sets').add(parent_set.to_dict())
        print(f"ParentSet saved to Firestore: Parent ID={parent_set.parent_monster_id}")
    except Exception as e:
        print(f"Error saving parent set to Firestore: {e}")

def delete_parent_set_from_firestore(parent_monster_id, grandpa_monster_id, grandma_monster_id):
    try:
        q = db.collection('parent_sets').where('parent_monster_id', '==', parent_monster_id)\
                                        .where('grandpa_monster_id', '==', grandpa_monster_id)\
                                        .where('grandma_monster_id', '==', grandma_monster_id).limit(1)
        docs = q.get()
        for doc in docs:
            doc.reference.delete()
            print(f"ParentSet {doc.id} (P:{parent_monster_id}, Gp:{grandpa_monster_id}, Gm:{grandma_monster_id}) deleted from Firestore.")
            break 
    except Exception as e:
        print(f"Error deleting parent set from Firestore: {e}")


@app.route('/')
def home():
    all_monsters, parent_sets = load_data_from_firestore()

    return render_template(
        'home.html', 
        all_monsters=all_monsters, 
        parent_sets=parent_sets,
        hiden_master_data_by_category=get_json_serializable_hiden_data(),
        green_hiden_names=green_hidens_list,
        ordered_hiden_categories=ORDERED_HIDEN_CATEGORIES 
    )

@app.route('/register_monster', methods=['POST'])
def register_monster():
    name = request.form['monster_name']
    
    all_monsters, _ = load_data_from_firestore() 
    existing_ids = {m.monster_id for m in all_monsters}
    new_monster_id = max(existing_ids) + 1 if existing_ids else 1001

    if any(m.monster_id == new_monster_id for m in all_monsters):
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
    save_monster_to_firestore(new_monster) 

    return redirect(url_for('home'))

@app.route('/delete_monster', methods=['POST'])
def delete_monster():
    monster_id_to_delete = int(request.form['monster_id'])

    delete_monster_from_firestore(monster_id_to_delete) 

    return redirect(url_for('home'))

@app.route('/register_parent_set', methods=['POST'])
def register_parent_set():
    parent_id = int(request.form['parent_monster'])
    grandpa_id = int(request.form['grandpa_monster'])
    grandma_id = int(request.form['grandma_monster'])
    
    all_monsters, _ = load_data_from_firestore()
    monster_map_by_id = {m.monster_id: m for m in all_monsters}

    parent = monster_map_by_id.get(parent_id)
    grandpa = monster_map_by_id.get(grandpa_id)
    grandma = monster_map_by_id.get(grandma_id)
    
    if len(set([parent_id, grandpa_id, grandma_id])) != 3:
        return redirect(url_for('home'))
    
    if not all([parent, grandpa, grandma]):
        return redirect(url_for('home'))

    new_parent_set = ParentSet(parent_id, grandpa_id, grandma_id, monster_map_by_id)
    save_parent_set_to_firestore(new_parent_set) 

    return redirect(url_for('home'))

@app.route('/delete_parent_set', methods=['POST'])
def delete_parent_set():
    parent_id = int(request.form['parent_monster_id'])
    grandpa_id = int(request.form['grandpa_monster_id'])
    grandma_id = int(request.form['grandma_monster_id'])

    delete_parent_set_from_firestore(parent_id, grandpa_id, grandma_id) 
    
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

    all_monsters, parent_sets = load_data_from_firestore()

    if not parent_sets:
        return render_template('results.html', results=[], error_message="親セットが登録されていません。")
    
    if not target_green_hidens:
        return render_template('results.html', results=[], error_message="検索条件が設定されていません。")

    results = search_combinations(target_green_hidens, parent_sets)

    return render_template('results.html', results=results, get_green_rank_up=get_green_rank_up)

# if __name__ == '__main__':
#     app.run(debug=True)
