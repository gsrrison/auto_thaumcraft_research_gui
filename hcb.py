from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image
from PyQt5 import QtCore, QtGui
# 存储合成配方和名称映射
recipes = {'aer': [], 'terra': [], 'ignis': [], 'aqua': [], 'ordo': [], 'perditio': [], 'alienis': ['vacuos', 'tenebrae'], 'arbor': ['aer', 'herba'], 'auram': ['praecantatio', 'aer'], 'bestia': ['motus', 'victus'], 'cognitio': ['ignis', 'spiritus'], 'corpus': ['mortuus', 'bestia'], 'exanimis': ['motus', 'mortuus'], 'fabrico': ['humanus', 'instrumentum'], 'fames': ['victus', 'vacuos'], 'gelum': ['ignis', 'perditio'], 'herba': ['victus', 'terra'], 'humanus': ['bestia', 'cognitio'], 'instrumentum': ['humanus', 'ordo'], 'iter': ['motus', 'terra'], 'limus': ['victus', 'aqua'], 'lucrum': ['humanus', 'fames'], 'lux': ['aer', 'ignis'], 'machina': ['motus', 'instrumentum'], 'messis': ['herba', 'humanus'], 'metallum': ['terra', 'vitreus'], 'meto': ['messis', 'instrumentum'], 'mortuus': ['victus', 'perditio'], 'motus': ['aer', 'ordo'], 'pannus': ['instrumentum', 'bestia'], 'perfodio': ['humanus', 'terra'], 'permutatio': ['perditio', 'ordo'], 'potentia': ['ordo', 'ignis'], 'praecantatio': ['vacuos', 'potentia'], 'sano': ['ordo', 'victus'], 'sensus': ['aer', 'spiritus'], 'spiritus': ['victus', 'mortuus'], 'telum': ['instrumentum', 'ignis'], 'tempestas': ['aer', 'aqua'], 'tenebrae': ['vacuos', 'lux'], 'tutamen': ['instrumentum', 'terra'], 'vacuos': ['aer', 'perditio'], 'venenum': ['aqua', 'perditio'], 'victus': ['aqua', 'terra'], 'vinculum': ['motus', 'perditio'], 'vitium': ['praecantatio', 'perditio'], 'vitreus': ['terra', 'ordo'], 'volatus': ['aer', 'motus'], 'ira': ['telum', 'ignis'], 'infernus': ['ignis', 'praecantatio'], 'gula': ['fames', 'vacuos'], 'invidia': ['sensus', 'fames'], 'desidia': ['vinculum', 'spiritus'], 'superbia': ['volatus', 'vacuos'], 'luxuria': ['corpus', 'fames'], 'tempus': ['vacuos', 'ordo'], 'electrum': ['potentia', 'machina'], 'magneto': ['metallum', 'iter'], 'nebrisum': ['perfodio', 'lucrum'], 'radio': ['lux', 'potentia'], 'strontio': ['perditio', 'cognitio'], 'exubitor': ['alienis', 'mortuus'], 'citrus': ['herba', 'sensus'], 'magnes': ['metallum', 'potentia'], 'fluctuatio': ['magnes', 'machina'], 'revelatio': ['alienis', 'cognitio'], 'MRU': ['praecantatio', 'potentia'], 'matrix': ['MRU', 'humanus'], 'radiation': ['MRU', 'motus'], 'terminus': ['lucrum', 'alienis'], 'signum': ['potentia', 'auram'], 'perplexus': ['cognitio', 'vinculum'], 'darkness': ['tenebrae', 'telum'], 'odachi': ['telum', 'vacuos'], 'proud': ['spiritus', 'odachi'], 'taurethrim': ['abonnen', 'arbor'], 'morwaith': ['abonnen', 'venenum'], 'dunlan': ['abonnen', 'perditio'], 'mordor': ['orchoth', 'telum'], 'torog': ['orchoth', 'tenebrae'], 'perian': ['humanus', 'sensus'], 'dale': ['abonnen', 'permutatio'], 'angdol': ['nauglin', 'perfodio'], 'nazgul': ['angmar', 'spiritus'], 'harad': ['abonnen', 'ignis'], 'ithryn': ['alfirin', 'praecantatio'], 'eredluin': ['nauglin', 'gelum'], 'fangorn': ['onodrim', 'arbor'], 'isengard': ['mornogol', 'praecantatio'], 'lothlorien': ['edhel', 'auram'], 'edhel': ['humanus', 'alfirin'], 'nauglin': ['humanus', 'perfodio'], 'valaraukar': ['alfirin', 'alienis'], 'dunedain': ['abonnen', 'iter'], 'rohan': ['abonnen', 'bestia'], 'druardh': ['edhel', 'arbor'], 'onodrim': ['arbor', 'motus'], 'lindon': ['edhel', 'aqua'], 'uhorm': ['arbor', 'bestia'], 'draugol': ['bestia', 'telum'], 'angmar': ['orchoth', 'vitium'], 'orchoth': ['edhel', 'exanimis'], 'dorwinion': ['abonnen', 'edhel'], 'dolguldur': ['orchoth', 'spiritus'], 'shire': ['perian', 'meto'], 'pertorog': ['abonnen', 'torog'], 'gundabad': ['orchoth', 'venenum'], 'gondor': ['abonnen', 'ordo'], 'mornogol': ['orchoth', 'abonnen'], 'utumno': ['valaraukar', 'alienis'], 'abonnen': ['humanus', 'lucrum'], 'rhudel': ['abonnen', 'fames'], 'alfirin': ['praecantatio', 'permutatio'], 'dragon': ['praecantatio', 'bestia'], 'substance': ['aqua', 'ordo'], 'space': ['substance', 'vacuos'], 'universe': ['substance', 'ordo'], 'destroy': ['aqua', 'ignis'], 'mana': ['auram', 'potentia'], 'dream': ['cognitio', 'ordo'], 'relic': ['cognitio', 'herba'], 'evil': ['vitium', 'lucrum'], 'treasure': ['lucrum', 'telum'], 'dackmagic': ['praecantatio', 'vitium'], 'manaherba': ['praecantatio', 'herba'], 'darkenergy': ['perditio', 'potentia'], 'magnetic': ['metallum', 'potentia'], 'electricity': ['aqua', 'potentia'], 'cave': ['terra', 'vacuos'], 'antimatter': ['perditio', 'substance'], 'enchant': ['undefined', 'telum'], 'alloy': ['ignis', 'metallum'], 'lava': ['terra', 'ignis'], 'time': ['ordo', 'vacuos'], 'rock': ['terra', 'perditio'], 'vegetation': ['aer', 'terra'], 'paper': ['herba', 'fabrico'], 'gravity': ['potentia', 'substance'], 'anteanus': ['humanus', 'chronos'], 'chronos': ['permutatio', 'motus'], 'priscus': ['bestia', 'chronos'], 'luacdiaoz': ['herba', 'bestia'], 'rattus': ['perditio', 'bestia'],
           'caelum': ['vitreus', 'metallum'], 'tabernus': ['iter', 'tutamen']}
name_mapping = {'aer': '风', 'terra': '地', 'ignis': '火', 'aqua': '水', 'ordo': '秩序', 'perditio': '混沌', 'alienis': '异域', 'arbor': '木头', 'auram': '灵气', 'bestia': '野兽', 'cognitio': '思维', 'corpus': '肉体', 'exanimis': '亡灵', 'fabrico': '合成', 'fames': '饥饿', 'gelum': '寒冰', 'herba': '植物', 'humanus': '人类', 'instrumentum': '工具', 'iter': '旅行', 'limus': '粘液', 'lucrum': '贪婪', 'lux': '光明', 'machina': '机械', 'messis': '作物', 'metallum': '金属', 'meto': '收获', 'mortuus': '死亡', 'motus': '运动', 'pannus': '布匹', 'perfodio': '采掘', 'permutatio': '交换', 'potentia': '能量', 'praecantatio': '魔法', 'sano': '治愈', 'sensus': '感知', 'spiritus': '灵魂', 'telum': '武器', 'tempestas': '气候', 'tenebrae': '黑暗', 'tutamen': '装备', 'vacuos': '虚空', 'venenum': '剧毒', 'victus': '生命', 'vinculum': '陷阱', 'vitium': '腐化', 'vitreus': '水晶', 'volatus': '飞行', 'ira': '暴怒', 'infernus': '下界', 'gula': '饕餮', 'invidia': '妒忌', 'desidia': '怠倦', 'superbia': '傲慢', 'luxuria': '欲望', 'tempus': 'MB时间', 'electrum': 'GT电力', 'magneto': '磁性', 'nebrisum': '欺诈', 'radio': '辐射', 'strontio': '愚锶', 'exubitor': '守护', 'citrus': '柑橘', 'magnes': 'TR磁力', 'fluctuatio': '波动', 'revelatio': '启示', 'MRU': '魔力辐射单元', 'matrix': '矩阵', 'radiation': '放射', 'terminus': '终结', 'signum': '信号', 'perplexus': '谜题', 'darkness': '幽暗', 'odachi': '野太刀', 'proud': '荣耀', 'taurethrim': '陶瑞斯', 'morwaith': '墨怀斯', 'dunlan': '黑蛮地', 'mordor': '魔多', 'torog': '食人妖', 'perian': '霍比特', 'dale': '长湖', 'angdol': '铁丘陵', 'nazgul': '那兹古尔', 'harad': '近哈拉德', 'ithryn': '迈雅', 'eredluin': '蓝色山脉', 'fangorn': '范贡森林', 'isengard': '艾森加德', 'lothlorien': '罗斯洛瑞恩', 'edhel': '精灵', 'nauglin': '矮人', 'valaraukar': '炎魔', 'dunedain': '游民', 'rohan': '洛汗', 'druardh': '森林王国', 'onodrim': '树人', 'lindon': '林顿', 'uhorm': '暗胡奥恩', 'draugol': '座狼', 'angmar': '安格玛', 'orchoth': '奥克', 'dorwinion': '多温尼安', 'dolguldur': '多古尔都', 'shire': '夏尔', 'pertorog': '半食人妖', 'gundabad': '北方奥克', 'gondor': '刚铎', 'mornogol': '乌鲁克', 'utumno': '乌图姆诺', 'abonnen': '中土人类', 'rhudel': '东夷', 'alfirin': '不朽', 'dragon': '龙', 'substance': '物质', 'space': '空间', 'universe': '宇宙', 'destroy': '毁灭', 'mana': 'M3魔法', 'dream': '梦想', 'relic': '文物', 'evil': '邪恶', 'treasure': '财富', 'dackmagic': '黑魔法', 'manaherba': '魔法植物', 'darkenergy': '暗能量', 'magnetic': 'M3磁力', 'electricity': 'M3电力', 'cave': '洞窟', 'antimatter': '反物质', 'enchant': '附魔', 'alloy': '合金', 'lava': '熔岩', 'time': 'M3时间', 'rock': '岩石', 'vegetation': '植被', 'paper': '纸张', 'gravity': '重力', 'anteanus': '历史', 'chronos': 'FA时间', 'priscus': '遗蜕', 'luacdiaoz': '辣条', 'rattus': '老鼠',
                'caelum': '宙空', 'tabernus': '靴子'}

recipes = {
    key.lower(): [component.lower() for component in components]
    for key, components in recipes.items()
}
name_mapping = {key.lower(): value for key, value in name_mapping.items()}

BASE_DIR = Path(__file__).resolve().parent

ys = {}
with (BASE_DIR / "ys.txt").open("r", encoding="utf-8") as f:
    for line in f:
        parts = line.replace(" ", "").strip().split(":", 1)
        if len(parts) != 2:
            continue
        try:
            color = tuple(map(int, parts[1].split(",")))
        except ValueError:
            continue
        if len(color) == 3:
            ys[color] = parts[0].lower()
# 元素系统
memo = {}
PRIMAL = {'aer', 'terra', 'ignis', 'aqua', 'ordo', 'perditio'}

# 配置
CLASS_NAMES_PATH = BASE_DIR / "class.txt"



# 加载类别名
ids = {}
getids = {}
cont = {}
with CLASS_NAMES_PATH.open("r", encoding="utf-8") as class_file:
    lins = class_file.readlines()
for i in range(len(lins)):
    ids[i] = lins[i].strip().lower()
    cont[i] = set()
    getids[lins[i].strip().lower()] = i

for k, v in recipes.items():
    if k in PRIMAL or len(v) != 2:
        continue
    if k in getids:
        if v[0] in getids:
            cont[getids[k]].add(getids[v[0]])
            cont[getids[v[0]]].add(getids[k])
        if v[1] in getids:
            cont[getids[k]].add(getids[v[1]])
            cont[getids[v[1]]].add(getids[k])

def is_con(id1, id2):
    return (id2 in cont[id1]) or (id1 in cont[id2])


def compute_cost(elem, visiting=None):
    if visiting is None:
        visiting = set()
    if elem not in getids:
        return float('inf')
    elem_name = elem
    elem_id = getids[elem_name]
    if elem_id in memo:
        return memo[elem_id]
    if elem in PRIMAL:
        memo[elem_id] = 1
        return 1
    if elem_name in visiting:
        memo[elem_id] = float('inf')
        return memo[elem_id]

    parts = recipes.get(elem_name, [])
    if not parts:
        memo[elem_id] = float('inf')
        return memo[elem_id]

    visiting.add(elem_name)
    part_costs = [compute_cost(part, visiting) for part in parts]
    visiting.remove(elem_name)
    memo[elem_id] = sum(part_costs) if all(cost != float('inf') for cost in part_costs) else float('inf')
    return memo[elem_id]


for class_name in ids.values():
    compute_cost(class_name)


class Box:
    def __init__(self, x, y, size, row=None, col=None):
        self.rect = QtCore.QRect(x, y, size, size)
        self.x = x
        self.y = y
        self.size = size
        self.row = row
        self.col = col
        self.center = QtCore.QPoint(x + size // 2, y + size // 2)

        self.label = None  # 分类结果ID
        self.highlight = False

    def draw(self, painter):
        if self.label is not None and self.label != 0:
            pen = QtGui.QPen(QtGui.QColor(0, 240, 0))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.drawRect(self.rect)
            if self.label != 1:
                pen.setColor(QtGui.QColor(255, 255, 255))
                pen.setWidth(4)
                painter.setPen(pen)
                internal_name = ids.get(self.label, str(self.label))
                text = str(name_mapping.get(internal_name, internal_name))
                text_pos = self.rect.topLeft() + QtCore.QPoint(4, self.rect.height() // 2 + 4)
                painter.drawText(text_pos, text)





@dataclass(frozen=True)
class Recognition:
    class_id: int
    sampled_color: Optional[Tuple[int, int, int]] = None
    color_distance: Optional[float] = None
    unknown: bool = False


def recognize(crop, color_tolerance=12):
    """按要素图标主色识别，并允许轻微的颜色误差。"""
    resampling = getattr(Image, "Resampling", Image)
    resize_filter = resampling.NEAREST if min(crop.size) < 24 else resampling.LANCZOS
    crop = crop.resize((24, 24), resize_filter).convert("RGB")
    pixels = crop.load()

    color_counter = Counter()
    non_white = 0
    ignored = {(255, 255, 255), (0, 0, 0), (1, 0, 0)}
    for y in range(crop.height):
        for x in range(crop.width):
            color = pixels[x, y]
            if color != (255, 255, 255):
                non_white += 1
            if color not in ignored:
                color_counter[color] += 1

    if non_white < 4:
        white_class = ys.get((255, 255, 255))
        return Recognition(getids.get(white_class, 0), (255, 255, 255), 0.0)

    if not color_counter:
        return Recognition(0)

    sampled_color, _ = color_counter.most_common(1)[0]
    if sampled_color in ys:
        return Recognition(getids.get(ys[sampled_color], 0), sampled_color, 0.0)

    known_distances = sorted(
        (
            sum((sampled_color[index] - known[index]) ** 2 for index in range(3)) ** 0.5,
            known,
        )
        for known in ys
    )
    distance, nearest_color = known_distances[0]
    second_distance = known_distances[1][0] if len(known_distances) > 1 else float("inf")
    if distance <= color_tolerance and second_distance - distance >= 4:
        return Recognition(getids.get(ys[nearest_color], 0), sampled_color, distance)

    return Recognition(0, sampled_color, distance, unknown=True)


def see(crop):
    """兼容旧调用；新代码应使用 recognize 获取诊断信息。"""
    return recognize(crop).class_id

def get_hex_neighbors(row, col):
    # 偶-奇配合的六边形偏移
    offsets = [(-1, -1), (2, 0), (1, -1), (-2, 0), (1, 1), (-1, 1)]
    return [(row + dr, col + dc) for dr, dc in offsets]



