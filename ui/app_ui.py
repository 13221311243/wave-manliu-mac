# -*- coding: utf-8 -*-
"""wave漫流 - AI 影视工业级分镜系统 (全新 UI)
架构：菜单栏(文件: 新建/打开/保存项目) + 全屏背景图 + 项目页(配置/控制台 双Tab)
控制台为原 CineMaster 全链路功能；配置页为供应商管理模式（学 Toonflow 三种添加方式）
"""
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, filedialog
import threading, json, os, hmac, hashlib, base64, time, uuid, platform, math
import requests, re, sys, queue
# 公网 HTTPS（AutoDL 自定义服务自签证书）时关闭证书校验并抑制警告
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass
from PIL import Image, ImageTk
import io

from core.agent import Agent
from skills.base_skill import AppContext

# 本地控制接口（OpenClaw/QQ 机器人遥控，2026-08-20 新增；缺失时不影响主程序）
try:
    from control_server import ControlServer
except Exception:
    ControlServer = None

# 剪映式剪辑工作台（三区布局：素材/预览/属性 + 底部时间线）
try:
    from edit_studio import EditStudio
except Exception:
    EditStudio = None

# 2026-08-21 敏感常量从 PyArmor 加密模块导入（SYSTEM_PROMPT/VIDEO_STYLE_PRESETS/GENRE_DIRECTOR_SKILLS）
from skills.protected_data import SYSTEM_PROMPT, VIDEO_STYLE_PRESETS
from skills.protected_genres_a import GENRE_DIRECTOR_SKILLS as _GDA
from skills.protected_genres_b import GENRE_DIRECTOR_SKILLS as _GDB
GENRE_DIRECTOR_SKILLS = dict(_GDA)
GENRE_DIRECTOR_SKILLS.update(_GDB)

# ================= 常量 =================
APP_NAME = "wave漫流"
APP_SUBTITLE = "| AI 影视工业级分镜引擎"
CONFIG_FILE = "config.json"
PROJECTS_DIR = "projects"
VENDOR_TEMPLATES_FILE = "vendor_templates.json"

# ================= 配色方案（偏好设置，参考 Toonflow/tdesign 主题色） =================
# 每套方案包含 12 个 UI 颜色。默认=经典蓝（原配色）；Toonflow蓝=tdesign 主题；
# 深色=暗黑模式。切换后存 config.json 的 ui_theme 字段，重启生效。
THEMES = {
    "经典蓝": {
        "bg": "#F0F2F5", "panel": "#FFFFFF", "input": "#F5F7FA",
        "text": "#333333", "text_dim": "#8E8E93",
        "accent": "#007AFF", "accent_dark": "#005ECB",
        "danger": "#FF3B30", "success": "#34C759",
        "border": "#E0E0E0", "watermark": "#E8E8E8", "credits": "#FF9500",
    },
    "Toonflow蓝": {
        "bg": "#F3F5F9", "panel": "#FFFFFF", "input": "#F0F4FA",
        "text": "#1A2333", "text_dim": "#7A8499",
        "accent": "#0052D9", "accent_dark": "#0F4A85",
        "danger": "#E34D59", "success": "#2BA471",
        "border": "#DCDCDC", "watermark": "#EBEBEB", "credits": "#EE9D28",
    },
    "暗夜黑": {
        "bg": "#1E1E1E", "panel": "#252526", "input": "#2D2D30",
        "text": "#E8E8E8", "text_dim": "#9E9E9E",
        "accent": "#3794FF", "accent_dark": "#007ACC",
        "danger": "#F14C4C", "success": "#4EC9B0",
        "border": "#3E3E42", "watermark": "#3A3A3A", "credits": "#EE9D28",
    },
    "AI科技紫": {
        # 2026-08-17 结合 Cosmius：深色玻璃拟态 + 霓虹紫青渐变（AI 高科技风）
        "bg": "#0B0E1A", "panel": "#12162B", "input": "#1A1F3A",
        "text": "#E6E9FF", "text_dim": "#8B90B8",
        "accent": "#8B5CF6", "accent_dark": "#6D3FE8",
        "danger": "#F87171", "success": "#34D399",
        "border": "#2A2F55", "watermark": "#1E2440", "credits": "#22D3EE",
    },
}
DEFAULT_THEME = "AI科技紫"

# 当前生效配色（启动时从 config 加载，见 load_config → apply_theme）
COLOR_BG = THEMES[DEFAULT_THEME]["bg"]
COLOR_PANEL = THEMES[DEFAULT_THEME]["panel"]
COLOR_INPUT = THEMES[DEFAULT_THEME]["input"]
COLOR_TEXT = THEMES[DEFAULT_THEME]["text"]
COLOR_TEXT_DIM = THEMES[DEFAULT_THEME]["text_dim"]
COLOR_ACCENT = THEMES[DEFAULT_THEME]["accent"]
COLOR_ACCENT_DARK = THEMES[DEFAULT_THEME]["accent_dark"]
COLOR_DANGER = THEMES[DEFAULT_THEME]["danger"]
COLOR_SUCCESS = THEMES[DEFAULT_THEME]["success"]
COLOR_BORDER = THEMES[DEFAULT_THEME]["border"]
COLOR_WATERMARK = THEMES[DEFAULT_THEME]["watermark"]
COLOR_CREDITS = THEMES[DEFAULT_THEME]["credits"]

def apply_theme(theme_name):
    """按主题名覆盖全局颜色常量。返回是否成功。"""
    global COLOR_BG, COLOR_PANEL, COLOR_INPUT, COLOR_TEXT, COLOR_TEXT_DIM
    global COLOR_ACCENT, COLOR_ACCENT_DARK, COLOR_DANGER, COLOR_SUCCESS
    global COLOR_BORDER, COLOR_WATERMARK, COLOR_CREDITS
    t = THEMES.get(theme_name)
    if not t:
        return False
    COLOR_BG = t["bg"]; COLOR_PANEL = t["panel"]; COLOR_INPUT = t["input"]
    COLOR_TEXT = t["text"]; COLOR_TEXT_DIM = t["text_dim"]
    COLOR_ACCENT = t["accent"]; COLOR_ACCENT_DARK = t["accent_dark"]
    COLOR_DANGER = t["danger"]; COLOR_SUCCESS = t["success"]
    COLOR_BORDER = t["border"]; COLOR_WATERMARK = t["watermark"]; COLOR_CREDITS = t["credits"]
    return True


def apply_ttk_theme():
    """让 ttk 控件（Combobox/Treeview/Scrollbar/Notebook/Progressbar）跟随当前主题。

    ttk 默认样式是浅色，切暗夜黑后不跟随 → 字体与背景相近看不清。必须在
    apply_theme() 之后、创建 ttk 控件之前调用（或重建 UI 后调用）。
    """
    try:
        import tkinter.ttk as ttk
        style = ttk.Style()
        try:
            style.theme_use("clam")  # clam 支持全面自定义
        except Exception:
            pass
        # Notebook
        style.configure("Waves.TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure("Waves.TNotebook.Tab", font=FONT_MAIN, padding=(22, 8),
                        background=COLOR_BG, foreground=COLOR_TEXT_DIM)
        style.map("Waves.TNotebook.Tab",
                  background=[("selected", COLOR_PANEL), ("active", COLOR_BG)],
                  foreground=[("selected", COLOR_ACCENT_DARK), ("active", COLOR_TEXT)])
        style.configure("Out.TNotebook", background=COLOR_PANEL, borderwidth=0)
        style.configure("Out.TNotebook.Tab", font=FONT_MAIN, padding=(14, 6),
                        background=COLOR_PANEL, foreground=COLOR_TEXT_DIM)
        style.map("Out.TNotebook.Tab",
                  background=[("selected", COLOR_INPUT), ("active", COLOR_PANEL)],
                  foreground=[("selected", COLOR_ACCENT_DARK), ("active", COLOR_TEXT)])
        # Combobox
        style.configure("TCombobox", fieldbackground=COLOR_INPUT, background=COLOR_INPUT,
                        foreground=COLOR_TEXT, arrowcolor=COLOR_TEXT,
                        selectbackground=COLOR_ACCENT, selectforeground="white",
                        bordercolor=COLOR_BORDER, lightcolor=COLOR_BORDER,
                        darkcolor=COLOR_BORDER, padding=3)
        style.map("TCombobox",
                  fieldbackground=[("readonly", COLOR_INPUT)],
                  foreground=[("readonly", COLOR_TEXT)],
                  selectbackground=[("readonly", COLOR_ACCENT)],
                  selectforeground=[("readonly", "white")])
        # Treeview（供应商列表）
        style.configure("Treeview", background=COLOR_INPUT, fieldbackground=COLOR_INPUT,
                        foreground=COLOR_TEXT, bordercolor=COLOR_BORDER,
                        lightcolor=COLOR_BORDER, darkcolor=COLOR_BORDER)
        style.map("Treeview",
                  background=[("selected", COLOR_ACCENT)],
                  foreground=[("selected", "white")])
        style.configure("Treeview.Heading", background=COLOR_PANEL, foreground=COLOR_TEXT,
                        font=("微软雅黑", 9, "bold"), relief="flat", bordercolor=COLOR_BORDER)
        style.map("Treeview.Heading", background=[("active", COLOR_BG)])
        # Scrollbar
        style.configure("Vertical.TScrollbar", background=COLOR_INPUT,
                        troughcolor=COLOR_BG, bordercolor=COLOR_BG,
                        arrowcolor=COLOR_TEXT, relief="flat")
        style.configure("Horizontal.TScrollbar", background=COLOR_INPUT,
                        troughcolor=COLOR_BG, bordercolor=COLOR_BG,
                        arrowcolor=COLOR_TEXT, relief="flat")
        # Progressbar
        style.configure("Light.Horizontal.TProgressbar", background=COLOR_ACCENT,
                        troughcolor=COLOR_INPUT, bordercolor=COLOR_BORDER)
        # 其他通用控件
        style.configure("TFrame", background=COLOR_PANEL)
        style.configure("TLabel", background=COLOR_PANEL, foreground=COLOR_TEXT)
        style.configure("TButton", background=COLOR_INPUT, foreground=COLOR_TEXT,
                        bordercolor=COLOR_BORDER, padding=4)
        style.map("TButton",
                  background=[("active", COLOR_BG), ("pressed", COLOR_ACCENT_DARK)],
                  foreground=[("pressed", "white")])
        return True
    except Exception:
        return False
# 视频风格预设（全局风格下拉框，放小说文本旁；生成图片/视频/提示词统一遵循）
DEFAULT_VIDEO_STYLE = '写实电影'


def image_style_suffix(style_name=''):
    """按全局风格返回图片生成风格后缀（替换原硬编码的漫剧卡通后缀）。
    风格为写实时返回真人写实句；其他风格返回对应 en 句。"""
    style = VIDEO_STYLE_PRESETS.get(str(style_name or '').strip()) or VIDEO_STYLE_PRESETS.get(DEFAULT_VIDEO_STYLE)
    en = (style or {}).get('en', '')
    return (', ' + en) if en else ''


# 人物地域特征提示词（新建项目选择"人物地域"：中国/海外 → 资产图人物人种特征统一）
ETHNICITY_GUIDES = {
    "中国": "中国汉族人特征：黑色直发，深棕色眼睛，黄色皮肤，东方脸型（柔和轮廓），"
            "典型东亚华人相貌，身高适中；严禁西方人特征（蓝眼/金发/高鼻深目）",
    "海外": "西方人特征：多样发色（金/棕/红/黑），蓝/绿/棕色眼睛，白人或欧美肤色，"
            "高鼻梁深眼窝，西方脸型轮廓；严禁东亚人特征",
}


def ethnicity_guide(ethnicity_name=''):
    """按人物地域返回人种特征提示词后缀（用于资产图/视频人物一致性）；空值默认中国"""
    name = str(ethnicity_name or '').strip() or '中国'
    return ETHNICITY_GUIDES.get(name, ETHNICITY_GUIDES['中国'])

# 台词语言选项 → (语言名, 注入提示词的语言指令)
# 指令用中英双语写（Qwen3VL 中英文理解都强），明确要求人物台词使用该语言
DIALECT_LANGS = {
    # 2026-08-16 锁死中文：删除全部外语选项（英语/日语/韩语/法语/德语/西语/俄语/阿语/泰语/粤语），
    # 所有台词一律中文普通话，杜绝 H3 生成外语语音。
    "中文（普通话）": ("zh", "本视频中所有人物台词必须使用中文普通话说出，对话清晰自然。",
                  "All character dialogue in this video MUST be spoken in Chinese Mandarin, clear and natural. STRICTLY NO voices in any other language (English, Japanese, Korean, etc.) anywhere in this video — every single spoken sound must be Chinese Mandarin."),
}


def dialect_lang_instruction(lang_name):
    """按语言选项名返回注入提示词的台词语言指令；自动=返回空串。
    2026-08-10 修正：返回**中文**指令（H3 Qwen3VL 原生支持中文；英文指令文本有被 H3
    音频生成当作语音念出的风险——外语声音根因之一）。禁止任何外语语音混入。"""
    try:
        v = DIALECT_LANGS.get(str(lang_name or "").strip())
        if not v:
            return ""
        _code, _zh, en = v
        if _code == "zh":
            return _zh + "。严禁本视频中出现任何外语语音（英语/日语/韩语等），所有清晰说话声必须是中文普通话。"
        return _zh
    except Exception:
        return ""


FONT_TITLE = ("微软雅黑", 12, "bold")
FONT_MAIN = ("微软雅黑", 10)
FONT_CODE = ("Consolas", 10)


# ================= Toonflow 导演技法集成（桌面4文件夹） =================
# 12 种题材导演手法（源自 Toonflow skill 体系），用于生成分镜时注入题材叙事技法
# ============ 2026-08-21 监督层评级（Toonflow 评级机制接入）============
REVIEW_SYSTEM_PROMPT = """你是影视工业化改编项目的**监督层评审专家**。你只对产出物提出问题和建议，**不做任何修改决策，所有修改决定权属于用户**。

# 审核报告格式（必须严格按此结构输出）
## 总评
- **评分**：{A/B/C/D}
- **概要**：{一句话总评，可顺带肯定亮点}

## 问题清单
| # | 严重程度 | 审核项 | 问题 | 建议方案 |
|---|----------|--------|------|----------|
| 1 | 🔴 严重 | {审核项} | {一句话描述} | {建议，多选方案用"/"分隔} |
| 2 | 🟡 中等 | {审核项} | {一句话描述} | {修复建议} |
| 3 | ⚪ 轻微 | {审核项} | {一句话描述} | {修复建议} |

# 评分标准
- A — 可直接使用：0 个严重问题，中等问题 ≤2
- B — 小修后可用：0 个严重问题，中等问题 ≤5
- C — 需较大修改：1-2 个严重问题
- D — 建议重做：≥3 个严重问题

# 精简规则
- 审核通过的项目不出现在报告中
- 同类轻微问题合并为一行
- B 级及以上省略「需要您决定」区块

# 通用审核原则
1. **可执行优先**：标准是"能不能用"，不是"完不完美"
2. **问题具体化**：每个问题指向具体位置和内容，不说"整体不够好"
3. **建议多元化**：严重问题提供多个可选方案
4. **只提建议不代决策**：所有修改决定权属于用户"""

# 剧本评级审核维度（阶段①）
REVIEW_SCRIPT_DIMENSIONS = """# 剧本（A基础角色 + B剧本正文）审核维度
请对以下【剧本产出物】按维度逐项审核，并输出审核报告：
1. **台词绝对保真**：小说原文对话是否完整保留（不得删减/概括/改写）；是否混入旁白/OS/画外音（本剧禁止）
2. **分集与时长控制**：台词总字数是否符合目标时长容量（1分钟≈150-200字）；是否超长或过短
3. **场景切换**：地点/时间变化是否严格切场景；场景描述是否极致简化（禁光影/氛围细致描写）
4. **角色一致性**：基础角色卡（A段）的形象/性格/服装锚点是否清晰；剧本中角色行为是否符合其性格
5. **心理活动转化**：内心想法是否转为角色台词（禁止旁白/OS形式）
6. **开篇吸引力**：第一场是否有强冲突/强情绪；是否踩"铺背景/开会/写景"三天坑
7. **结构完整**：剧情从小说开头推进，台词完整保留，无遗漏关键事件"""

# 分镜评级审核维度（阶段②：C/D/E资产 + 分镜全局规划 + F分镜资产）
REVIEW_STORYBOARD_DIMENSIONS = """# 分镜（C/D/E资产 + 分镜全局规划 + F分镜资产）审核维度
请对以下【分镜产出物】按维度逐项审核，并输出审核报告：
1. **台词完整性**：分镜台词与剧本一字不差；超长台词是否按 3-4字/秒 拆分（单镜≤10s）
2. **站位连续性**：同一人物相邻分镜站位/朝向是否一致（严禁左右互换）；换位是否有走位交代
3. **道具位置连续**：同一道具相邻分镜位置/持有者是否一致；转移是否有动作交代
4. **资产调用一致**：分镜引用的角色/场景/道具是否与 C/D/E 资产卡对应（不虚构）
5. **光影连贯**：相邻分镜光影色调是否连贯（无逻辑突变）；是否有过渡标注
6. **动作物理化**：动作是否为直白物理过程（双脚着地/接触点/受力方向）；无漂浮/瞬移
7. **H3六段结构**：每个分镜【H3视频提示词】六段是否完整（素材定义/成片目标/不变量锁定/时间轴/环境音配乐/负面约束）；detailed_description 是否写明总时长
8. **无台词检查**：无台词分镜是否全文无引号对话/可被 H3 念出的句子；是否写"台词：无"
9. **全局规划与F段一致**：阶段一全局规划是否与 F 段分镜站位/动作/台词一致
10. **H3 误解风险与方向歧义（2026-08-21 新增，重点审核）**：逐镜检查每个分镜中所有可能让 H3 生成模型产生歧义、矛盾或错误解读的描述，发现任何问题点必须在报告中逐条列出（指出具体分镜号+原文+问题+修正建议）：
    ① 运镜冲突：同一时间段内既写"固定机位/固定镜头/机位不变"又写推拉摇移等运镜动作（如"固定机位"与"缓推/横移/跟拍"并存），或 summary/retention 写"不推拉不摇移"而 detailed_description 时间轴里出现运镜；
    ② 方向歧义：人物移动方向/朝向必须以画面坐标明确到底（如"从巷子里走来，往巷子深处走去"——"深处"指画面纵深（背对镜头）还是巷子另一侧？必须写明"向画面深处/背对镜头/向画面左侧巷口"等无歧义表述）；禁止"深处/里面/前方/那边"等无参照方向词；
    ③ 画面左右 vs 人物朝向混淆：人物站位用"画面左侧/右侧"时，其面朝方向必须与站位、对话对象严格一致且以画面为坐标写明（正确例："A 在画面左侧坐着、面朝画面右侧看向 B；B 在画面右侧坐着、面朝画面左侧看向 A"=两人面对面；错误例："A 在左边坐着看向右侧 B，B 在右边坐着看向左侧"——H3 会把"看向右侧"理解成人物自己朝向的右侧而非画面右侧，导致生成两人背对背或各看各的）；
    ④ 视线/手势/道具指向歧义：视线落点、手指方向、道具朝向（刀尖/枪口/信纸）必须写明指向画面何处或哪个角色（如"刀尖朝上指向画面右上方"），禁止"指向那边/朝向他"等含糊表述；
    ⑤ 时间轴动作顺序歧义：同一时间段内多个动作是否明确先后（"先…再…然后…"）；是否出现"同时"与"先后"混用、动作与台词时序矛盾（台词说完前动作已完成）；
    ⑥ 其他矛盾：同一分镜内互相冲突的约束（正反描述并存，如"缓慢"与"急速"、"安静"与"喧哗"）、同一角色同一镜内位置跳变、可被 H3 多种解读的模糊描述。"""



# 视觉连续性铁律（源自 Toonflow 分镜表技法：保证相邻分镜衔接不跳画面、不穿帮）
DIRECTOR_CONTINUITY_RULES = '''【视觉连续性铁律·强制遵守】(保证剪映拼接时相邻镜头不跳画面、不穿帮)
1. 动作连续性：相邻分镜若为同一动作过程，后一镜必须从上一镜动作的结束点顺接（如：上镜"抬手推门"，下镜必须"手触门板"），严禁跳帧式切换。
2. 景别递进：相邻分镜景别差不超过2级（远景→全景→中景→近景→特写→大特写），严禁远景直接跳特写。
3. 180°视轴线：同一场景内两个对话角色，所有分镜的机位必须保持在两人连线的同一侧（180°线内），严禁越轴导致两人左右位置互换。
4. 朝向空间逻辑：角色面向、站位、与对手的相对位置（左/右/远近）必须在相邻分镜中保持一致；若需改变，必须在镜头内用走位动作交代，严禁无交代的朝向突变。
5. 节拍密度（黄金6秒）：单镜时长2-6秒为宜，最长10秒；动作镜头宁短勿长，对话镜头可稍长。
6. 头尾安全区：动作镜头的起幅（动作起始姿态）与落幅（动作结束姿态）必须完整，严禁起幅/落幅被切出画面。
7. 场景与道具衔接：同一场景的相邻分镜，场景布局、道具位置、门窗方向必须一致；换场景必须在分镜中明确标注【转场】，严禁无交代的场景突变。
8. 光源方向一致：同一场景相邻分镜的主光源方向、色温必须一致；时间变化需用光影过渡镜头交代。
9. 服装造型一致：同一角色相邻分镜的服装、发型、配饰必须完全一致，严禁穿帮。
10. 台词连续性：同一句台词被拆到多个分镜时，上下镜的台词必须无缝衔接（上镜末句=下镜首句的开头），严禁重复或漏词。
11. 每镜【画面与视听细节】必须写明与上一镜的承接关系（动作/位置/朝向/光影），格式如"承接上镜：XX"。
12. 剪辑方案【转场方案】必须覆盖所有相邻镜头切换点，同场景优先"硬切/动作顺接"，跨场景用"叠化/空镜过渡"，严禁无理由花式转场。'''




# ================= 激活（已豁免） =================
def check_license_on_start():
    return (True, "验证成功")

def update_last_run_time():
    pass


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def load_config():
    default_config = {
        "api_key": "", "base_url": "https://api.deepseek.com/v1",
        "model_name": "deepseek-chat",
        "media_api_key": "", "media_base_url": "",
        "img_model": "", "vid_model": "",
        "ui_theme": DEFAULT_THEME,   # 偏好：UI 配色方案
        # 2026-08-20 AI 遥控配置（客户自填；不填不影响使用）
        "control_port": 8712,        # 本地控制接口端口（OpenClaw/QQ 机器人调用）
        "qq_bot": {"appid": "", "appsecret": "", "token": "", "enabled": False},
        "autodl": {"api_token": "", "instance_id": "", "minimax_key": "", "enabled": False},
        # 2026-08-21 全局默认供应商配置（配置一次，新建项目自动继承，免重复配置）
        "global_vendors": None,          # 最近一次保存的供应商列表（含 api_key）
        "global_text_vendor_id": "",     # 最近一次文本供应商角色
        "global_media_vendor_id": "",    # 最近一次媒体供应商角色
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            default_config.update(loaded)
        except Exception:
            pass
    # 应用配色主题（偏好设置）
    apply_theme(default_config.get("ui_theme") or DEFAULT_THEME)
    return default_config

# ================= 供应商模板 =================
# 2026-08-06：已删除 火山引擎/OpenAI/Toonflow中转 供应商（用户要求），仅保留 DeepSeek + ComfyUI
DEFAULT_VENDOR_TEMPLATES = [
    {
        "id": "deepseek", "name": "DeepSeek 官方",
        "base_url": "https://api.deepseek.com/v1", "api_key": "",
        "models": [
            {"name": "deepseek-chat", "type": "text", "display": "DeepSeek Chat"},
            {"name": "deepseek-reasoner", "type": "text", "display": "DeepSeek Reasoner"},
        ],
    },
    {
        "id": "comfyui", "name": "ComfyUI 服务器", "type": "comfyui",
        "base_url": "http://你的服务器IP:端口", "api_key": "",
        "models": [
            {"name": "comfyui-flux2", "type": "image", "display": "Flux2 生图（需含 flux-2-klein 模型）"},
            {"name": "comfyui-qwen", "type": "image", "display": "Qwen-Image 生图（中文文字不乱码，需含 nunchaku_qwen_image fp4 模型）"},
            {"name": "comfyui-ltx23", "type": "video", "display": "LTX 2.3 生视频（需含 ltx 模型）"},
            {"name": "comfyui-h3", "type": "video", "display": "MiniMax H3 生视频（多图参考+原生立体声，需含 minimax_h3 模型）"},
        ],
    },
]

def get_vendor_templates():
    if os.path.exists(VENDOR_TEMPLATES_FILE):
        try:
            with open(VENDOR_TEMPLATES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_VENDOR_TEMPLATES

def save_vendor_templates(templates):
    try:
        with open(VENDOR_TEMPLATES_FILE, "w", encoding="utf-8") as f:
            json.dump(templates, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ================= 工具 =================
def bind_hover(widget, bg_normal, bg_hover):
    widget.bind("<Enter>", lambda e: widget.config(bg=bg_hover))
    widget.bind("<Leave>", lambda e: widget.config(bg=bg_normal))

def sanitize_api_key(key):
    """清洗 API Key：全角冒号→半角、全角空格→半角、去 api: 前缀、去空白"""
    if not key:
        return ""
    s = key.replace("\uff1a", ":").replace("\u3000", " ").strip()
    if s.lower().startswith("api:"):
        s = s[4:]
    return s.strip()



# ================= 主窗口 =================
class CineMasterUI:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME + " - AI 影视工业级分镜系统")
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w, h = int(sw * 0.9), int(sh * 0.9)
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.root.minsize(1000, 680)
        try:
            self.root.iconbitmap(resource_path("app.ico"))
        except Exception:
            pass
        self.root.configure(bg=COLOR_BG)

        # 核心上下文（与 skills 层约定接口，不能改名）
        self.ctx = AppContext()
        self.agent = Agent(self.ctx)
        self.text_widgets = {}
        self.line_buffer = ""
        self.current_section = "script"
        self.current_config = load_config()
        # 主题应用：ttk 控件跟随配色（必须在创建任何 ttk 控件之前）
        try:
            apply_ttk_theme()
        except Exception:
            pass
        self.image_history = []
        self.video_history = []
        self._video_local_paths = {}      # 2026-08-21 视频本地保存路径映射（url → 本地 mp4）
        self._video_preview_frames = {}   # 2026-08-21 视频预览帧目录映射（url → 帧 PNG 目录）
        self._selected_hist_idx = set()   # 图片历史中选中待删除的索引集合
        # 2026-08-21 需求2：批量生成按钮锁定时间戳（ComfyUI 卡死时 3 分钟自动恢复）
        self._btn_lock_times = {}          # {'gen_img': ts, 'gen_vid': ts}
        self._btn_timeout_seconds = 180    # 3 分钟超时
        self.current_tk_img = None
        self.current_image_url = ""
        self.current_video_url = ""
        self.video_ref_image_urls = []
        self.video_ref_image_path = ""
        self.models_cache = {"image": [], "video": []}
        self.video_matched_ready = False
        self.pending_video_ref_urls = []
        self.MAX_VIDEO_REFS = 9  # 每分镜最多 9 张参考图（与 video_skill.MAX_REFS 一致）
        # 分镜提示词列表（自动从分镜资产同步，供批量生成视频）
        self.storyboard_prompts = []      # [{'num': 1, 'prompt': '...'}, ...]
        self.story_prompt_vars = []       # 每行勾选 BooleanVar
        self.story_prompt_texts = []      # 每行可编辑 Text 控件
        self._story_batch_done = 0        # 批量生成视频完成计数
        # 资产图匹配（视频tab左侧：分镜→资产图）
        self.asset_images = {}            # {资产名: {'url','img','prompt'}} 同名资产唯一
        self.asset_voices = {}            # {资产核心名: 本地音色文件路径}（人物专属，生成视频时按分镜人物上传给 H3）
        self.story_asset_links = []       # [{'num': N, 'assets': [资产名,...]}]
        self._asset_prompt_map = {}       # {资产名: 生成提示词}（批量生图时构建）
        # 图片预览"重新生成"状态（_finish_image_done 回填替换用）
        self._regen_hist_idx = None
        self._regen_asset_name = ''
        self._regen_prompt = ''
        self._regen_prompt_cn = ''
        # 资产名→中文提示词 映射（双击图片预览显示中文）
        self._asset_prompt_cn_map = {}
        # 小说转化完成标记（流式 [ALL_DONE] 或 status 生成完毕信号触发，用于自动同步分镜提示词）
        self._story_gen_done = False
        # 2026-08-21 分段评级状态
        self._gen_stage = 0              # 当前生成阶段：0无/1剧本/2资产分镜/3剪辑
        self._gen_novel_text = ''        # 本轮小说文本（阶段间复用）
        self._gen_command_text = ''      # 本轮附加指令
        self._gen_system_prompt = ''     # 本轮 system prompt（含风格/导演/地域注入）
        self._gen_review_text = ''       # 上一轮评级意见（重新生成携带）
        self._stage_review_done = set()  # 2026-08-21 已触发评级的阶段标记集合（防重复评级）
        self._pending_stage_after = None # 2026-08-21 挂起的阶段评级 after 回调 id（确认后取消）
        self._asset_photo_refs = {}       # 缩略图 PhotoImage 引用防GC
        self._asset_checked = {}          # {资产名: bool} 勾选状态
        self._regenerating_asset = None   # 正在重新生成的资产名

        # 项目状态
        self.current_project = None  # {name, remark, config, vendors, text_vendor_id, media_vendor_id, novel, command, sections, ...}
        self.project_start_time = None
        self._build_menu()
        self._build_ui()

        # 事件泵
        self.root.after(50, self._process_ui_queue)
        self.root.after(100, self._flush_ui_buffer)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ============ 菜单栏 ============
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="新建项目", accelerator="Ctrl+N", command=self._new_project_dialog)
        file_menu.add_command(label="打开项目", accelerator="Ctrl+O", command=self._open_project_dialog)
        file_menu.add_command(label="管理项目…", command=self._manage_projects_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="保存项目", accelerator="Ctrl+S", command=self._save_project)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件(F)", menu=file_menu)
        about_menu = tk.Menu(menubar, tearoff=0)
        about_menu.add_command(label="激活软件…", command=self._show_license_dialog)
        about_menu.add_separator()
        about_menu.add_command(label="偏好设置…", command=self._show_preferences)
        about_menu.add_separator()
        about_menu.add_command(label="关于 " + APP_NAME, command=self._show_about)
        menubar.add_cascade(label="帮助(H)", menu=about_menu)
        self.root.config(menu=menubar)
        self.root.bind_all("<Control-n>", lambda e: self._new_project_dialog())
        self.root.bind_all("<Control-o>", lambda e: self._open_project_dialog())
        self.root.bind_all("<Control-s>", lambda e: self._save_project())

    def _show_about(self):
        messagebox.showinfo(APP_NAME, APP_NAME + " " + APP_SUBTITLE + "\n\n基于 AI 的全链路影视分镜工作流：\n小说 → 剧本 → 角色/场景/道具资产 → 分镜 → 图片 → 视频")

    def _show_preferences(self):
        """偏好设置：UI 配色方案（参考 Toonflow/tdesign 主题）。切换后写 config，重启生效。"""
        dlg = tk.Toplevel(self.root)
        dlg.title("偏好设置")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("420x260")
        tk.Label(dlg, text="界面配色风格：", font=FONT_MAIN, bg=COLOR_PANEL,
                 fg=COLOR_TEXT).pack(anchor="w", padx=20, pady=(18, 6))
        cur_theme = self.current_config.get("ui_theme") or DEFAULT_THEME
        var = tk.StringVar(value=cur_theme)
        for name, t in THEMES.items():
            row = tk.Frame(dlg, bg=COLOR_PANEL)
            row.pack(fill="x", padx=20, pady=3)
            rb = tk.Radiobutton(row, text=name, variable=var, value=name,
                                font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT,
                                activebackground=COLOR_PANEL, selectcolor=COLOR_PANEL)
            rb.pack(side="left")
            # 色块预览
            for key in ("bg", "accent", "success"):
                sw = tk.Frame(row, width=16, height=16, bg=t[key], highlightbackground=COLOR_BORDER,
                              highlightthickness=1)
                sw.pack(side="left", padx=2)
        hint = tk.Label(dlg, text="切换后需重启程序生效", font=("微软雅黑", 9),
                        fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)
        hint.pack(anchor="w", padx=20, pady=(6, 0))
        def ok():
            theme = var.get()
            self.current_config["ui_theme"] = theme
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.current_config, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            dlg.destroy()
            self._show_toast("配色已保存：%s（重启生效）" % theme, "success")
        btns = tk.Frame(dlg, bg=COLOR_PANEL)
        btns.pack(fill="x", padx=20, pady=(14, 12))
        tk.Button(btns, text="确定", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                  relief="flat", command=ok).pack(side="right", padx=4)
        tk.Button(btns, text="取消", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT_DIM,
                  relief="solid", bd=1,
                  command=dlg.destroy).pack(side="right", padx=4)

    def _show_license_dialog(self, blocking=False):
        """激活软件对话框：显示机器码 + 输入激活码 + 3次错误锁定。

        blocking=True 时（启动强制激活）：激活成功才恢复主窗口；未激活点退出=关闭程序。
        """
        from skills.license_guard import (verify_license, get_machine_code,
                                          remaining_errors, is_activated, LOCKOUT_AFTER)
        dlg = tk.Toplevel(self.root)
        dlg.title("激活 " + APP_NAME)
        dlg.configure(bg=COLOR_PANEL)
        # blocking 模式（root 已 withdraw）：不设 transient——transient 会跟随 owner 隐藏
        if not blocking:
            dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("560x380")
        dlg.resizable(False, False)
        # 置顶（强制激活模式）
        try:
            dlg.attributes("-topmost", True)
        except Exception:
            pass
        # 标题
        tk.Label(dlg, text="软件激活", font=("微软雅黑", 14, "bold"),
                 fg=COLOR_ACCENT_DARK, bg=COLOR_PANEL).pack(anchor="w", padx=24, pady=(18, 4))
        # 机器码
        mc = get_machine_code()
        tk.Label(dlg, text="本机机器码（点复制发给作者生成激活码）：", font=FONT_MAIN,
                 fg=COLOR_TEXT, bg=COLOR_PANEL).pack(anchor="w", padx=24, pady=(8, 2))
        mc_frame = tk.Frame(dlg, bg=COLOR_INPUT, highlightbackground=COLOR_BORDER, highlightthickness=1)
        mc_frame.pack(fill="x", padx=24, pady=(0, 6))
        tk.Label(mc_frame, text=mc, font=("Consolas", 11, "bold"),
                 fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(side="left", padx=10, pady=6)
        def _copy_mc():
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(mc)
                self._show_toast("机器码已复制", "success")
            except Exception:
                pass
        tk.Button(mc_frame, text="📋 复制", font=("微软雅黑", 9),
                  bg=COLOR_ACCENT, fg="white", relief="flat",
                  command=_copy_mc).pack(side="right", padx=8, pady=4)
        # 激活码输入
        tk.Label(dlg, text="激活码：", font=FONT_MAIN, fg=COLOR_TEXT,
                 bg=COLOR_PANEL).pack(anchor="w", padx=24, pady=(8, 2))
        self.entry_license = tk.Entry(dlg, font=("Consolas", 11), relief="solid", bd=1,
                                      bg=COLOR_INPUT, fg=COLOR_TEXT)
        self.entry_license.pack(fill="x", padx=24, pady=(0, 4))
        # 状态
        self.label_license_status = tk.Label(dlg, text="", font=("微软雅黑", 9),
                                             fg=COLOR_DANGER, bg=COLOR_PANEL)
        self.label_license_status.pack(anchor="w", padx=24, pady=(0, 2))
        # 剩余次数
        left = remaining_errors()
        if left <= 0:
            self.label_license_status.config(text="⚠ 已锁定：错误次数过多，请输入正确激活码解锁")
        else:
            tk.Label(dlg, text="剩余尝试次数：%d / %d" % (left, LOCKOUT_AFTER),
                     font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(anchor="w", padx=24)
        # 按钮
        btns = tk.Frame(dlg, bg=COLOR_PANEL)
        btns.pack(fill="x", padx=24, pady=(16, 12))
        def do_activate():
            code = self.entry_license.get().strip()
            ok, msg = verify_license(code)
            if ok:
                self.label_license_status.config(text=msg, fg=COLOR_SUCCESS)
                self._show_toast(msg, "success")
                # 激活成功：恢复主窗口 + 关闭对话框
                if blocking:
                    try:
                        self.root.deiconify()
                    except Exception:
                        pass
                dlg.after(800, dlg.destroy)
            else:
                self.label_license_status.config(text=msg, fg=COLOR_DANGER)
                left2 = remaining_errors()
                if left2 <= 0:
                    # 锁定：不允许退出，必须输对
                    try:
                        dlg.grab_set()
                    except Exception:
                        pass
        tk.Button(btns, text="激活", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                  relief="flat", command=do_activate).pack(side="right", padx=4)
        def do_quit():
            if is_activated():
                if blocking:
                    try:
                        self.root.deiconify()
                    except Exception:
                        pass
                dlg.destroy()
            else:
                # 未激活时退出整个程序
                try:
                    self._on_close()
                except Exception:
                    pass
                try:
                    self.root.destroy()
                except Exception:
                    pass
        tk.Button(btns, text="退出程序", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_DANGER,
                  relief="solid", bd=1, command=do_quit).pack(side="right", padx=4)
        self.entry_license.bind("<Return>", lambda e: do_activate())

    def _on_close(self):
        if self.current_project and self._project_dirty():
            r = messagebox.askyesnocancel(APP_NAME, "当前项目有未保存的修改，是否保存？")
            if r is None:
                return
            if r:
                self._save_project()
        self.root.destroy()

    # ============ 项目存储 ============
    def _project_path(self, name):
        if not os.path.exists(PROJECTS_DIR):
            try:
                os.makedirs(PROJECTS_DIR)
            except Exception:
                pass
        safe = re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "未命名项目"
        return os.path.join(PROJECTS_DIR, safe + ".json")

    def _assets_dir(self):
        """2026-08-21 资产图本地目录：projects/<项目名>/assets/"""
        try:
            if not self.current_project:
                return os.path.join(os.getcwd(), "assets")
            safe = re.sub(r'[\\/:*?"<>|]', "_", (self.current_project.get("name") or "未命名项目")).strip()
            base = os.path.join(PROJECTS_DIR, safe, "assets")
            os.makedirs(base, exist_ok=True)
            return base
        except Exception:
            return os.path.join(os.getcwd(), "assets")

    def _tail_frames_dir(self):
        """2026-08-21 尾帧本地目录：项目目录/assets/tail_frames/"""
        d = os.path.join(self._assets_dir(), "tail_frames")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def _videos_dir(self):
        """2026-08-21 生成视频本地目录：项目目录/videos/（生成完自动下载保存）"""
        try:
            if not self.current_project:
                return os.path.join(os.getcwd(), "videos")
            safe = re.sub(r'[\\/:*?"<>|]', "_", (self.current_project.get("name") or "未命名项目")).strip()
            base = os.path.join(PROJECTS_DIR, safe, "videos")
            os.makedirs(base, exist_ok=True)
            return base
        except Exception:
            return os.path.join(os.getcwd(), "videos")

    def _preview_frames_dir(self):
        """2026-08-21 hover 预览帧目录：项目目录/assets/video_previews/（ffmpeg 抽帧存 PNG）"""
        try:
            if not self.current_project:
                return os.path.join(os.getcwd(), "video_previews")
            safe = re.sub(r'[\\/:*?"<>|]', "_", (self.current_project.get("name") or "未命名项目")).strip()
            base = os.path.join(PROJECTS_DIR, safe, "assets", "video_previews")
            os.makedirs(base, exist_ok=True)
            return base
        except Exception:
            return os.path.join(os.getcwd(), "video_previews")

    def _list_projects(self):
        if not os.path.exists(PROJECTS_DIR):
            return []
        items = []
        try:
            for fn in sorted(os.listdir(PROJECTS_DIR)):
                if fn.endswith(".json"):
                    try:
                        with open(os.path.join(PROJECTS_DIR, fn), "r", encoding="utf-8") as f:
                            data = json.load(f)
                        items.append(data)
                    except Exception:
                        continue
        except Exception:
            pass
        return items

    def _project_dirty(self):
        if not self.current_project:
            return False
        cfg = self._get_api_config()
        return (cfg != self.current_project.get("last_saved_config")
                or self.text_input_novel.get("1.0", tk.END).strip() != self.current_project.get("novel", "")
                or self.text_input_command.get("1.0", tk.END).strip() != self.current_project.get("command", ""))

    def _new_project_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("新建项目")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        try:
            dlg.iconbitmap(resource_path("app.ico"))
        except Exception:
            pass
        tk.Label(dlg, text="项目名：", font=FONT_MAIN, bg=COLOR_PANEL).grid(row=0, column=0, padx=12, pady=(18, 4), sticky="w")
        e_name = tk.Entry(dlg, font=FONT_MAIN, width=36, relief="solid", bd=1,
                          bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        e_name.grid(row=0, column=1, padx=12, pady=(18, 4), sticky="ew")
        tk.Label(dlg, text="备注：", font=FONT_MAIN, bg=COLOR_PANEL).grid(row=1, column=0, padx=12, pady=4, sticky="nw")
        t_remark = tk.Text(dlg, font=FONT_MAIN, width=36, height=4, relief="solid", bd=1,
                           bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        t_remark.grid(row=1, column=1, padx=12, pady=4, sticky="ew")
        # 人物地域选择：决定资产图/视频人物的人种特征（中国=华人特征，海外=外国人特征）
        tk.Label(dlg, text="人物地域：", font=FONT_MAIN, bg=COLOR_PANEL).grid(row=2, column=0, padx=12, pady=4, sticky="w")
        # 2026-08-16 锁死中文：人物地域只保留"中国"（删除"海外"，杜绝英文链路）
        self._ethnicity_var = tk.StringVar(value="中国")
        ethnicity_combo = ttk.Combobox(dlg, textvariable=self._ethnicity_var,
                                       values=("中国",), state="readonly",
                                       width=10, font=FONT_MAIN)
        ethnicity_combo.grid(row=2, column=1, padx=12, pady=4, sticky="w")
        tip = tk.Label(dlg, text="提示：新建项目后将进入配置/控制台工作页", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)
        tip.grid(row=3, column=0, columnspan=2, padx=12, pady=(2, 8), sticky="w")

        def on_ok():
            name = e_name.get().strip()
            if not name:
                messagebox.showwarning(APP_NAME, "请填写项目名", parent=dlg)
                return
            if os.path.exists(self._project_path(name)):
                messagebox.showwarning(APP_NAME, "同名项目已存在，请换一个名字", parent=dlg)
                return
            remark = t_remark.get("1.0", tk.END).strip()
            ethnicity = self._ethnicity_var.get()
            dlg.destroy()
            self._create_project(name, remark, ethnicity)

        btn_ok = tk.Button(dlg, text="创建项目", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                           activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                           relief="flat", padx=18, pady=4, command=on_ok)
        btn_ok.grid(row=4, column=0, columnspan=2, pady=(4, 18))
        bind_hover(btn_ok, COLOR_ACCENT, COLOR_ACCENT_DARK)
        e_name.focus_set()
        dlg.update_idletasks()
        ww, wh = dlg.winfo_width(), dlg.winfo_height()
        dlg.geometry(f"+{self.root.winfo_rootx() + (self.root.winfo_width() - ww) // 2}+{self.root.winfo_rooty() + (self.root.winfo_height() - wh) // 3}")

    def _create_project(self, name, remark, ethnicity="中国"):
        # 2026-08-16 锁死中文：地域强制中国（即使调用方传"海外"也归一）
        ethnicity = "中国"
        # 2026-08-21 配置一次全局继承：新建项目优先继承 config.json 里的全局默认供应商
        #（含 api_key/角色），用户配置好一次后，之后所有新项目自动带配置，免重复配置
        _gv = self.current_config.get("global_vendors")
        if isinstance(_gv, list) and _gv:
            _vendors = [json.loads(json.dumps(v)) for v in _gv]
        else:
            _vendors = [json.loads(json.dumps(t)) for t in get_vendor_templates()]
        self.current_project = {
            "name": name, "remark": remark,
            "ethnicity": ethnicity,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "config": self._get_api_config(),
            "vendors": _vendors,
            "text_vendor_id": self.current_config.get("global_text_vendor_id", ""),
            "media_vendor_id": self.current_config.get("global_media_vendor_id", ""),
            "novel": "", "command": "",
            "sections": {k: "" for k in ("all", "script", "character", "scene", "prop", "global_plan", "storyboard", "editing")},
            "last_saved_config": self._get_api_config(),
        }
        self.project_start_time = time.time()
        self._enter_project_page()
        self._show_toast("项目已创建：" + name, "success")

    def _merge_vendor_templates(self, data):
        """把最新供应商模板的 models 合并进项目现有 vendors（旧项目自动获得新模型选项）。

        规则1：项目里已有的 models 保持原样（顺序+内容），模板里新增的 models 追加到末尾。
        规则2：模板里已删除的供应商（如火山引擎/OpenAI/Toonflow 中转）从项目 vendors 中过滤掉，
               仅保留模板 id 白名单内的供应商 + 用户自建的供应商（id 不在模板里的视为自建，保留）。
        """
        tpl_map = {}
        try:
            for t in get_vendor_templates():
                tpl_map[t.get("id")] = t
        except Exception:
            return
        vendors = data.get("vendors") if isinstance(data.get("vendors"), list) else []
        if not vendors:
            data["vendors"] = [json.loads(json.dumps(t)) for t in get_vendor_templates()]
            return
        # 模板 id 白名单（用于过滤旧供应商）；保留用户自建（不在模板中的 id）
        tpl_ids = set(tpl_map.keys())
        keep = []
        for v in vendors:
            vid = v.get("id")
            if vid in tpl_ids or not vid:
                keep.append(v)
            else:
                # 模板中已不存在的供应商：仅当是模板曾提供的才删；完全自建（无 id）保留
                # 判断依据：老模板供应商 id 固定为 volcengine/openai/toonflow，出现在模板历史中
                if vid in ("volcengine", "openai", "toonflow"):
                    continue  # 已从模板删除的旧供应商，过滤掉
                keep.append(v)  # 其他自建供应商保留
        vendors = keep
        data["vendors"] = vendors
        for v in vendors:
            tpl = tpl_map.get(v.get("id"))
            if not tpl or not isinstance(tpl.get("models"), list):
                continue
            existing = v.get("models") if isinstance(v.get("models"), list) else []
            seen = set()
            merged = []
            for m in existing:
                name = m.get("name") if isinstance(m, dict) else None
                if not name or name in seen:
                    continue
                seen.add(name)
                merged.append(m)
            # 追加模板里有、项目里没有的模型
            for m in tpl["models"]:
                name = m.get("name")
                if name and name not in seen:
                    seen.add(name)
                    merged.append(json.loads(json.dumps(m)))
            v["models"] = merged

    def _manage_projects_dialog(self):
        """管理项目：列出所有项目，支持打开/删除（删除前二次确认）"""
        projects = self._list_projects()
        if not projects:
            messagebox.showinfo(APP_NAME, "还没有保存过的项目。\n请先使用 文件→新建项目。")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("管理项目")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("620x460")
        try:
            dlg.iconbitmap(resource_path("app.ico"))
        except Exception:
            pass
        tk.Label(dlg, text="所有项目（双击打开，选中后可删除）：", font=FONT_TITLE,
                 bg=COLOR_PANEL, fg=COLOR_TEXT).pack(anchor="w", padx=14, pady=(14, 6))
        lb = tk.Listbox(dlg, font=FONT_MAIN, relief="solid", bd=1,
                        selectbackground=COLOR_ACCENT, activestyle="none",
                        bg=COLOR_INPUT, fg=COLOR_TEXT, selectforeground="white")
        lb.pack(fill="both", expand=True, padx=14, pady=6)
        lb.bind("<Double-Button-1>", lambda e: _open_selected())
        # 加载列表（按更新时间倒序：最新在前）
        projects.sort(key=lambda p: p.get('updated', ''), reverse=True)
        for p in projects:
            _name = p.get('name', '未命名')
            _upd = (p.get('updated') or '').strip()
            _mark = ' ★当前' if self.current_project and self.current_project.get('name') == _name else ''
            lb.insert(tk.END, "%s    [%s]%s" % (_name, _upd, _mark))
        info = tk.Label(dlg, text="双击打开项目；选中后点「删除所选项目」删除（不可恢复）",
                        font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)
        info.pack(anchor="w", padx=14)

        def _open_selected():
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning(APP_NAME, "请先选择项目", parent=dlg)
                return
            dlg.destroy()
            self._load_project(projects[sel[0]])

        def _delete_selected():
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning(APP_NAME, "请先选择要删除的项目", parent=dlg)
                return
            p = projects[sel[0]]
            _nm = p.get('name', '未命名')
            if not messagebox.askyesno(APP_NAME, "确定要删除项目 [%s] 吗？\n删除后不可恢复！" % _nm, parent=dlg):
                return
            # 删除项目文件
            try:
                path = self._project_path(_nm)
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                messagebox.showerror(APP_NAME, "删除失败：%s" % e, parent=dlg)
                return
            # 若删除的是当前打开的项目，清空当前项目状态
            if self.current_project and self.current_project.get('name') == _nm:
                try:
                    self.current_project = None
                    self.text_input_novel.delete("1.0", tk.END)
                    self.text_input_command.delete("1.0", tk.END)
                    for k in self.text_widgets:
                        w = self.text_widgets[k]
                        w.config(state=tk.NORMAL)
                        w.delete("1.0", tk.END)
                        w.config(state=tk.DISABLED)
                    self.image_history = []
                    self.video_history = []
                    self._video_local_paths = {}
                    self._video_preview_frames = {}
                    self.asset_images = {}
                    self.asset_voices = {}
                    self.story_asset_links = []
                    self._update_history_ui()
                    self._update_video_history_ui()
                    self.label_project_info.config(text="项目：未打开")
                except Exception:
                    pass
            self._show_toast("已删除项目：%s" % _nm, "success")
            # 刷新列表
            projects.pop(sel[0])
            lb.delete(sel[0])
            if not projects:
                dlg.destroy()

        btns = tk.Frame(dlg, bg=COLOR_PANEL)
        btns.pack(fill="x", padx=14, pady=(2, 12))
        btn_open = tk.Button(btns, text="打开所选项目", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                             relief="flat", padx=18, pady=4, command=_open_selected)
        btn_open.pack(side="left")
        bind_hover(btn_open, COLOR_ACCENT, COLOR_ACCENT_DARK)
        btn_del = tk.Button(btns, text="删除所选项目", font=FONT_MAIN, bg=COLOR_DANGER, fg="white",
                            relief="flat", padx=18, pady=4, command=_delete_selected)
        btn_del.pack(side="left", padx=(10, 0))
        bind_hover(btn_del, COLOR_DANGER, "#B3251D")

    def _open_project_dialog(self):
        projects = self._list_projects()
        if not projects:
            messagebox.showinfo(APP_NAME, "还没有保存过的项目。\n请先使用 文件→新建项目。")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("打开项目")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("560x420")
        try:
            dlg.iconbitmap(resource_path("app.ico"))
        except Exception:
            pass
        tk.Label(dlg, text="选择要打开的历史项目：", font=FONT_TITLE, bg=COLOR_PANEL).pack(anchor="w", padx=14, pady=(14, 6))
        lb = tk.Listbox(dlg, font=FONT_MAIN, relief="solid", bd=1, selectbackground=COLOR_ACCENT, activestyle="none",
                        bg=COLOR_INPUT, fg=COLOR_TEXT, selectforeground="white")
        lb.pack(fill="both", expand=True, padx=14, pady=6)
        lb.bind("<Double-Button-1>", lambda e: open_selected())
        for p in projects:
            lb.insert(tk.END, f"{p.get('name','')}    [{p.get('updated','')}]")
        info = tk.Label(dlg, text="双击或选中后点击打开；将恢复该项目保存的全部操作状态", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)
        info.pack(anchor="w", padx=14)

        def open_selected():
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning(APP_NAME, "请先选择项目", parent=dlg)
                return
            dlg.destroy()
            self._load_project(projects[sel[0]])

        btn = tk.Button(dlg, text="打开所选项目", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                        activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                        relief="flat", padx=18, pady=4, command=open_selected)
        btn.pack(pady=(4, 14))
        bind_hover(btn, COLOR_ACCENT, COLOR_ACCENT_DARK)

    def _load_project(self, data):
        # 2026-08-16 锁死中文：旧项目若是"海外"（英文链路）一律归一为"中国"
        if str(data.get("ethnicity") or "").strip() == "海外":
            data["ethnicity"] = "中国"
        self.current_project = data
        self.project_start_time = time.time()
        # 供应商（旧项目自动合并最新模板 models，如 comfyui-h3）
        self._merge_vendor_templates(data)
        if "sections" not in data:
            data["sections"] = {k: "" for k in ("all", "script", "character", "scene", "prop", "global_plan", "storyboard", "editing")}
        # 同步旧 config 字段
        cfg = data.get("config", {})
        self.current_config.update(cfg)
        self._enter_project_page()
        # 恢复界面
        self._load_config_to_ui()
        self.text_input_novel.delete("1.0", tk.END)
        self.text_input_novel.insert("1.0", data.get("novel", ""))
        # 重新解析章节（打开项目后章节下拉必须恢复，否则只剩"全部章节"）
        try:
            from skills.doc_reader import split_chapters
            _novel = (data.get("novel") or "").strip()
            _chs = split_chapters(_novel) if _novel else []
            self.novel_chapters = _chs
            _names = [c[0] for c in _chs]
            if _names:
                self.label_chapter_info.config(
                    text="共识别 %d 章：%s..." % (len(_names), "、".join(_names[:3])), fg=COLOR_SUCCESS)
                try:
                    self.combo_vid_chapter.config(values=["全部章节"] + _names)
                    # 恢复分镜所属章节（storyboard_chapter）：重开项目后下拉回到生成时的章节，
                    # 避免"选具体章节生成视频时全部被过滤"（修复章节归属丢失）
                    _sb_ch = (data.get("storyboard_chapter") or "全部章节")
                    self.combo_vid_chapter.set(_sb_ch if _sb_ch in (["全部章节"] + _names) else "全部章节")
                except Exception:
                    pass
            else:
                self.label_chapter_info.config(text="未识别到章节标题（按全文处理）", fg=COLOR_TEXT_DIM)
        except Exception:
            pass
        self.text_input_command.delete("1.0", tk.END)
        self.text_input_command.insert("1.0", data.get("command", ""))
        # 打开项目时同步已上传指令副本
        self.uploaded_command = data.get("command", "").strip()
        for k, v in data.get("sections", {}).items():
            if k in self.text_widgets:
                w = self.text_widgets[k]
                w.config(state=tk.NORMAL)
                w.delete("1.0", tk.END)
                if v:
                    w.insert("1.0", v)
                w.config(state=tk.DISABLED)
        # 恢复历史
        self.image_history = data.get("image_history", []) or []
        # 2026-08-21 本地资产恢复：有 local_path 且文件存在 → 直接从本地读图
        try:
            for _it in self.image_history:
                _lp = _it.get("local_path") or ""
                if _lp and os.path.exists(_lp):
                    try:
                        _it['img'] = Image.open(_lp)
                    except Exception:
                        _it['img'] = None
        except Exception:
            pass
        # 2026-08-09：清洗历史记录里的错乱资产名（旧 extract_assets 正则跨行吞内容，
        # 曾把"贴身宫女（贪嘴丫鬟）=====\n【中文AI提示词】..."整段存成 name）——
        # 含 ===== 或超长换行的 name 截断到标题行为止，保证后续匹配/跳过逻辑干净。
        import re as _re2
        for _it in self.image_history:
            _nm = str(_it.get("name") or "")
            if '=====' in _nm or len(_nm) > 30:
                _nm2 = _nm.split('=====')[0].strip()
                _nm2 = _re2.sub(r'^\*+|\*+$', '', _nm2).strip()
                if _nm2:
                    _it['name'] = _nm2
                else:
                    _it['name'] = _nm[:20]
        self.video_history = data.get("video_history", []) or []
        # 2026-08-21 恢复视频本地保存路径映射（只保留文件仍存在的；不在 video_history 的清理）
        try:
            self._video_local_paths = {}
            for _vk, _vp in (data.get("video_local_paths") or {}).items():
                if _vk in self.video_history and _vp and os.path.exists(_vp):
                    self._video_local_paths[_vk] = _vp
        except Exception:
            self._video_local_paths = {}
        # 2026-08-21 恢复视频预览帧目录映射（只保留目录仍存在的）
        try:
            self._video_preview_frames = {}
            for _vk, _vp in (data.get("video_preview_frames") or {}).items():
                if _vk in self.video_history and _vp and os.path.isdir(_vp):
                    self._video_preview_frames[_vk] = _vp
        except Exception:
            self._video_preview_frames = {}
        # 重开项目重建中文提示词映射（双击图片预览显示中文；不重建则 prompt_cn 空→回退英文）
        try:
            _full = data.get("sections", {}).get("all", "") or ""
            self._rebuild_cn_prompt_map(_full)
            # 把提取到的中文提示词回填进 image_history（双击预览直接用）
            for _it in self.image_history:
                _nm = _it.get("name") or ""
                _cn = (self._asset_prompt_cn_map or {}).get(_nm, "")
                if _cn and not _it.get("prompt_cn"):
                    _it["prompt_cn"] = _cn
        except Exception:
            pass
        # 恢复人物音色（仅保留仍存在的本地文件）
        self.asset_voices = {}
        for _k, _v in (data.get("asset_voices") or {}).items():
            try:
                if _v and os.path.exists(_v):
                    self.asset_voices[_k] = _v
            except Exception:
                pass
        # 2026-08-15 需求2：恢复分镜参考图编辑结果（用户手动增删的匹配）
        try:
            _saved_links = data.get("story_asset_links")
            if _saved_links:
                self.story_asset_links = [{'num': str(ln.get('num', '')), 'assets': list(ln.get('assets', []))}
                                          for ln in _saved_links]
                # 2026-08-15 修复：恢复手动编辑标记时**只保护 assets 非空的分镜**——
                # 若无条件标记全部分镜，重开项目后 _match_assets_to_storyboard 会认为
                # 所有分镜都被用户"编辑过"，导致重新生成资产图后智能匹配永远不生效
                # （分镜1-4 明明有匹配却显示"无参考图"的根因）。
                # 语义：用户手动勾选过图片（assets 非空）= 保护不覆盖；
                #       assets 为空 = 允许重新智能匹配。
                self._sb_ref_edited = {str(ln.get('num', '')): True for ln in _saved_links
                                       if list(ln.get('assets', []))}
        except Exception:
            pass
        self._update_history_ui()
        self._update_video_history_ui()
        # 打开项目后自动同步分镜提示词到视频 Tab
        try:
            self.root.after(600, self._safe_sync_storyboard)
        except Exception:
            pass
        self._show_toast("已打开项目：" + data.get("name", ""), "success")

    def _save_project(self):
        if not self.current_project:
            messagebox.showinfo(APP_NAME, "当前没有打开的项目。\n请先 文件→新建项目 或 打开项目。")
            return
        p = self.current_project
        cfg = self._get_api_config()
        # 全局风格随项目保存（用户选择风格 → 打开项目自动恢复）
        try:
            cfg['global_style'] = self.combo_global_style.get() if hasattr(self, 'combo_global_style') else DEFAULT_VIDEO_STYLE
        except Exception:
            cfg['global_style'] = DEFAULT_VIDEO_STYLE
        p["config"] = cfg
        p["last_saved_config"] = dict(cfg)
        p["novel"] = self.text_input_novel.get("1.0", tk.END).strip()
        p["command"] = self.text_input_command.get("1.0", tk.END).strip()
        for k in self.text_widgets:
            p["sections"][k] = self.text_widgets[k].get("1.0", tk.END).strip()
        # 记录分镜所属章节（重开项目后据此恢复，避免章节过滤失效）
        try:
            p["storyboard_chapter"] = self.combo_vid_chapter.get() if hasattr(self, 'combo_vid_chapter') else "全部章节"
        except Exception:
            p["storyboard_chapter"] = "全部章节"
        # 图片历史只存元信息（PIL Image 无法 JSON 序列化，加载时按 url 重新拉取）
        p["image_history"] = [{'url': it.get('url', ''), 'name': it.get('name', ''),
                               'type': it.get('type', ''), 'chapter': it.get('chapter', ''),
                               'prompt': it.get('prompt', ''), 'prompt_cn': it.get('prompt_cn', ''),
                               'local_path': it.get('local_path', '')}
                              for it in self.image_history]
        p["video_history"] = self.video_history
        # 2026-08-21 视频本地保存路径映射（url → 本地 mp4 路径），随项目保存
        try:
            p["video_local_paths"] = dict(getattr(self, '_video_local_paths', {}) or {})
        except Exception:
            p["video_local_paths"] = {}
        # 2026-08-21 视频预览帧目录映射（url → 帧 PNG 目录），随项目保存
        try:
            p["video_preview_frames"] = dict(getattr(self, '_video_preview_frames', {}) or {})
        except Exception:
            p["video_preview_frames"] = {}
        # 2026-08-15 需求2：分镜参考图编辑结果（用户手动增删的匹配）随项目保存，重开不丢失
        p["story_asset_links"] = [{'num': ln.get('num', ''), 'assets': list(ln.get('assets', []))}
                                  for ln in getattr(self, 'story_asset_links', [])]
        # 人物音色（资产核心名 → 本地音色文件路径），随项目保存
        p["asset_voices"] = dict(getattr(self, 'asset_voices', {}) or {})
        p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            path = self._project_path(p["name"])
            # 原子写：先写临时文件再替换，避免保存中断（杀进程/断电）导致项目 JSON 截断损坏
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            # 2026-08-21 配置一次全局继承：手动保存时同步全局默认供应商
            self._sync_global_vendor_defaults()
            self._show_toast("项目已保存", "success")
        except Exception as e:
            messagebox.showerror(APP_NAME, "保存失败：%s" % e)



    # ============ 主布局 ============
    def _build_ui(self):
        self.frame_bg = tk.Frame(self.root, bg=COLOR_BG)
        self.frame_bg.pack(fill="both", expand=True)

        # ===== 层1：全屏背景图 canvas（欢迎页可见） =====
        self.canvas_bg = tk.Canvas(self.frame_bg, highlightthickness=0, bd=0, bg=COLOR_BG)
        self.canvas_bg.pack(fill="both", expand=True)
        self._bg_photo_ref = None
        self._bg_img_id = None
        try:
            img_path = resource_path("bg.jpg")
            if os.path.exists(img_path):
                self.bg_full = Image.open(img_path).convert("RGB")
                self.bg_photo = ImageTk.PhotoImage(self.bg_full.resize(
                    (self.root.winfo_screenwidth(), self.root.winfo_screenheight()), Image.LANCZOS))
                self._bg_img_id = self.canvas_bg.create_image(0, 0, image=self.bg_photo, anchor="nw")
                self._bg_photo_ref = self.bg_photo
        except Exception:
            pass
        self.canvas_bg.bind("<Configure>", self._on_bg_resize)

        # 欢迎页品牌文字（画在背景图上）
        self._build_welcome_card()

        # ===== 层2：项目页（默认隐藏，进入项目后覆盖背景） =====
        self.frame_project = tk.Frame(self.frame_bg, bg=COLOR_BG)
        # 顶部品牌区
        self.frame_header = tk.Frame(self.frame_project, bg=COLOR_BG)
        self.frame_header.pack(fill="x", padx=18, pady=(12, 4))
        self._build_header()

        # 项目信息条
        self.frame_project_bar = tk.Frame(self.frame_project, bg=COLOR_PANEL, highlightbackground=COLOR_BORDER, highlightthickness=1)
        self.label_project_info = tk.Label(self.frame_project_bar, text="", font=FONT_MAIN, fg=COLOR_TEXT, bg=COLOR_PANEL)
        self.label_project_info.pack(side="left", padx=12, pady=6)
        self.btn_save_project = tk.Button(self.frame_project_bar, text="保存项目 (Ctrl+S)", font=FONT_MAIN,
                                          bg=COLOR_ACCENT, fg="white", relief="flat", padx=12, pady=2,
                                          activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                                          command=self._save_project)
        self.btn_save_project.pack(side="right", padx=12, pady=4)
        bind_hover(self.btn_save_project, COLOR_ACCENT, COLOR_ACCENT_DARK)

        # 主容器（双Tab）
        self.main_container = tk.Frame(self.frame_project, bg=COLOR_BG)
        self.main_container.pack(fill="both", expand=True)
        self._build_project_page(self.main_container)

    def _on_bg_resize(self, event):
        try:
            if not self.canvas_bg.winfo_exists():
                return
            w, h = event.width, event.height
            if w < 50 or h < 50:
                return
            if self._bg_photo_ref is not None and hasattr(self, 'bg_full'):
                try:
                    self.bg_photo = ImageTk.PhotoImage(self.bg_full.resize((w, h), Image.LANCZOS))
                    self.canvas_bg.itemconfig(self._bg_img_id, image=self.bg_photo)
                    self._bg_photo_ref = self.bg_photo
                except Exception:
                    pass
        except Exception:
            pass

    def _center_welcome_card(self):
        try:
            if hasattr(self, '_welcome_card_win'):
                cw = self.canvas_bg.winfo_width()
                ch = self.canvas_bg.winfo_height()
                self.canvas_bg.coords(self._welcome_card_win, cw // 2, int(ch * 0.48))
        except Exception:
            pass

    def _build_header(self):
        tk.Label(self.frame_header, text=APP_NAME, font=("微软雅黑", 18, "bold"),
                 fg=COLOR_ACCENT_DARK, bg=COLOR_BG).pack(side="left")
        tk.Label(self.frame_header, text=APP_SUBTITLE, font=FONT_MAIN,
                 fg=COLOR_TEXT_DIM, bg=COLOR_BG).pack(side="left", padx=(8, 0), pady=(7, 0))

    def _build_welcome_card(self):
        # 品牌标题（画在背景图上，无图片，文字一排）
        self.canvas_bg.create_text(30, 26, text=APP_NAME, font=("微软雅黑", 20, "bold"),
                                   fill=COLOR_ACCENT_DARK, anchor="nw")
        self.canvas_bg.create_text(30 + 24 + len(APP_NAME) * 20, 33, text=APP_SUBTITLE, font=FONT_MAIN,
                                   fill=COLOR_TEXT_DIM, anchor="nw")

    def _build_project_page(self, parent):
        # 双 Tab：配置 / 控制台
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Waves.TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure("Waves.TNotebook.Tab", font=FONT_MAIN, padding=(22, 8))
        style.map("Waves.TNotebook.Tab", background=[("selected", COLOR_PANEL)], foreground=[("selected", COLOR_ACCENT_DARK)])
        self.notebook = ttk.Notebook(parent, style="Waves.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(6, 14))

        self.frame_config = tk.Frame(self.notebook, bg=COLOR_PANEL)
        self.frame_console = tk.Frame(self.notebook, bg=COLOR_PANEL)
        self.frame_gen = tk.Frame(self.notebook, bg=COLOR_PANEL)
        self.frame_single = tk.Frame(self.notebook, bg=COLOR_PANEL)
        self.frame_edit = tk.Frame(self.notebook, bg=COLOR_PANEL)
        self.notebook.add(self.frame_config, text="配置")
        self.notebook.add(self.frame_console, text="控制台")
        self.notebook.add(self.frame_gen, text="生成器")
        self.notebook.add(self.frame_single, text="单镜工作台")
        # 2026-08-21 剪辑 tab 从 UI 取消（frame_edit 仍构建，代码保留；不再 add 到 notebook）
        # self.notebook.add(self.frame_edit, text="剪辑")
        self._build_config_area(self.frame_config)
        self._build_console_area(self.frame_console)
        self._build_generator_area(self.frame_gen)
        self._build_single_shot_tab(self.frame_single)
        self._build_edit_tab(self.frame_edit)   # 代码保留，UI 不显示
        # 2026-08-21 必须先配置供应商：除「配置」外全部 tab 禁用，配置完成后统一激活
        for _i in range(1, 4):
            self.notebook.tab(_i, state="disabled")

    def _enter_project_page(self):
        # 隐藏背景画布（欢迎页），显示项目页
        self.canvas_bg.pack_forget()
        self.frame_project.pack(fill="both", expand=True)
        p = self.current_project
        self.label_project_info.config(text=f"项目：{p.get('name','')}    备注：{p.get('remark','')}    创建：{p.get('created','')}")
        self._load_vendor_list()
        # 2026-08-21 继承的全局配置同步到旧 7 控件（生成链路兜底拿 key），
        # 否则新项目只解锁不填控件，走旧路径的模块会拿到空 key
        try:
            self._sync_compat_from_vendors()
        except Exception:
            pass
        self._update_console_state()

    # ============ 配置Tab：供应商管理 ============
    def _on_notebook_tab_changed(self, event=None):
        """切换 Tab 时：只在配置 Tab 绑滚轮，其他 Tab 解绑（避免滚轮串扰）"""
        try:
            sel = self.notebook.index(self.notebook.select()) if self.notebook.select() else 0
            is_cfg = (sel == 0 and str(self.notebook.tab(0, 'text')) == '配置')
            # 右侧配置页滚动
            if hasattr(self, '_cfg_canvas') and hasattr(self, '_cfg_wheel_handler'):
                if is_cfg:
                    self._cfg_canvas.bind_all("<MouseWheel>", self._cfg_wheel_handler)
                else:
                    try:
                        self._cfg_canvas.unbind_all("<MouseWheel>")
                    except Exception:
                        pass
            # 2026-08-21 左侧供应商列表滚动（含 AI 遥控）
            if hasattr(self, '_left_canvas') and hasattr(self, '_left_wheel_handler'):
                if is_cfg:
                    # 合并两个 handler：优先滚左侧（鼠标在左列时），否则滚右侧
                    def _combined(e):
                        try:
                            # 判断鼠标位置是否在左列内
                            mx, my = self.root.winfo_pointerxy()
                            lx, ly = self._left_canvas.winfo_rootx(), self._left_canvas.winfo_rooty()
                            lw, lh = self._left_canvas.winfo_width(), self._left_canvas.winfo_height()
                            if lx <= mx <= lx + lw and ly <= my <= ly + lh:
                                self._left_wheel_handler(e)
                            else:
                                self._cfg_wheel_handler(e)
                        except Exception:
                            pass
                    self._left_canvas.bind_all("<MouseWheel>", _combined)
                    self._left_canvas.unbind_all("<Shift-MouseWheel>")
                else:
                    try:
                        self._left_canvas.unbind_all("<MouseWheel>")
                    except Exception:
                        pass
        except Exception:
            pass

    def _build_config_area(self, parent):
        # 2026-08-20 修复：配置页内容超高被窗口裁剪（保存遥控配置按钮看不见）。
        # 包一层 Canvas 滚动容器：垂直滚动条 + 鼠标滚轮 + 支持触控板/触摸屏。
        cfg_canvas = tk.Canvas(parent, bg=COLOR_PANEL, highlightthickness=0)
        cfg_vsb = ttk.Scrollbar(parent, orient="vertical", command=cfg_canvas.yview)
        cfg_canvas.configure(yscrollcommand=cfg_vsb.set)
        cfg_canvas.pack(side="left", fill="both", expand=True)
        cfg_vsb.pack(side="right", fill="y")
        cfg_inner = tk.Frame(cfg_canvas, bg=COLOR_PANEL)
        cfg_win = cfg_canvas.create_window((0, 0), window=cfg_inner, anchor="nw")

        def _on_cfg_configure(e):
            cfg_canvas.configure(scrollregion=cfg_canvas.bbox("all"))
            # 宽度跟随画布（不出现横向滚动）
            cfg_canvas.itemconfigure(cfg_win, width=e.width)

        cfg_inner.bind("<Configure>", _on_cfg_configure)
        cfg_canvas.bind("<Configure>", lambda e: cfg_canvas.itemconfigure(cfg_win, width=e.width))

        def _on_cfg_wheel(e):
            try:
                cfg_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
            except Exception:
                pass

        cfg_canvas.bind_all("<MouseWheel>", _on_cfg_wheel)  # Windows 滚轮
        # 触控板/触摸屏（macOS/两指滑动）
        try:
            cfg_canvas.bind_all("<Shift-MouseWheel>", lambda e: None)
        except Exception:
            pass

        # 记住引用，切 Tab 时解绑滚轮，避免影响其他 Tab
        self._cfg_canvas = cfg_canvas
        self._cfg_wheel_handler = _on_cfg_wheel
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed)

        # 所有配置内容都挂到 cfg_inner（原 parent）上
        parent = cfg_inner
        # 左：供应商列表（含固定条目「AI 遥控」）
        frame_left = tk.Frame(parent, bg=COLOR_PANEL, width=240)
        frame_left.pack(side="left", fill="y", padx=(14, 8), pady=14)
        frame_left.pack_propagate(False)
        tk.Label(frame_left, text="供应商列表", font=FONT_TITLE, bg=COLOR_PANEL, fg=COLOR_TEXT).pack(anchor="w", pady=(0, 6))
        self.vendor_listbox = tk.Listbox(frame_left, font=FONT_MAIN, relief="solid", bd=1,
                                         selectbackground=COLOR_ACCENT, activestyle="none",
                                         bg=COLOR_INPUT, fg=COLOR_TEXT, selectforeground="white")
        self.vendor_listbox.pack(fill="both", expand=True)
        self.vendor_listbox.bind("<<ListboxSelect>>", self._on_vendor_select)
        tk.Label(frame_left, text="添加供应商：", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(anchor="w", pady=(10, 2))
        btn_row = tk.Frame(frame_left, bg=COLOR_PANEL)
        btn_row.pack(fill="x")
        def _mk_btn(txt, cmd):
            b = tk.Button(btn_row, text=txt, font=("微软雅黑", 9), bg=COLOR_PANEL, fg=COLOR_ACCENT,
                          relief="solid", bd=1, highlightbackground=COLOR_BORDER, command=cmd)
            b.pack(side="left", fill="x", expand=True, padx=(0, 4))
            return b
        _mk_btn("模板", self._add_vendor_from_template)
        _mk_btn("链接", self._add_vendor_from_link)
        _mk_btn("文件", self._add_vendor_from_file)
        btn_row2 = tk.Frame(frame_left, bg=COLOR_PANEL)
        btn_row2.pack(fill="x", pady=(6, 0))
        b_del = tk.Button(btn_row2, text="删除选中供应商", font=("微软雅黑", 9), bg=COLOR_DANGER, fg="white",
                          relief="flat", command=self._delete_vendor)
        b_del.pack(side="left", fill="x", expand=True, padx=(0, 4))
        bind_hover(b_del, COLOR_DANGER, "#CC2B22")

        # 右：供应商详情 / AI 遥控面板（2026-08-21 双面板切换）
        frame_right = tk.Frame(parent, bg=COLOR_PANEL)
        frame_right.pack(side="left", fill="both", expand=True, padx=(8, 14), pady=14)
        self._vendor_panel = tk.Frame(frame_right, bg=COLOR_PANEL)
        self._vendor_panel.pack(fill="both", expand=True)
        self._remote_panel = tk.Frame(frame_right, bg=COLOR_PANEL)
        # 遥控面板默认隐藏，选中「AI 遥控」条目时显示
        self._remote_panel.pack_forget()
        self.vendor_detail = {}
        tk.Label(self._vendor_panel, text="供应商详情", font=FONT_TITLE, bg=COLOR_PANEL, fg=COLOR_TEXT).pack(anchor="w", pady=(0, 6))
        g = tk.Frame(self._vendor_panel, bg=COLOR_PANEL)
        g.pack(fill="x")
        g.columnconfigure(1, weight=1)
        tk.Label(g, text="名称：", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.vendor_detail["name"] = tk.Entry(g, font=FONT_MAIN, relief="solid", bd=1, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.vendor_detail["name"].grid(row=0, column=1, sticky="ew", pady=4)
        self.vendor_detail["name"].bind("<KeyRelease>", self._on_vendor_field_edit)
        self.vendor_detail["name"].bind("<FocusOut>", self._on_vendor_field_edit)
        tk.Label(g, text="Base URL：", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.vendor_detail["base_url"] = tk.Entry(g, font=FONT_MAIN, relief="solid", bd=1, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.vendor_detail["base_url"].grid(row=1, column=1, sticky="ew", pady=4)
        self.vendor_detail["base_url"].bind("<KeyRelease>", self._on_vendor_field_edit)
        self.vendor_detail["base_url"].bind("<FocusOut>", self._on_vendor_field_edit)
        tk.Label(g, text="API Key：", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.vendor_detail["api_key"] = tk.Entry(g, font=FONT_MAIN, relief="solid", bd=1, bg=COLOR_INPUT, fg=COLOR_TEXT, show="*", insertbackground=COLOR_TEXT)
        self.vendor_detail["api_key"].grid(row=2, column=1, sticky="ew", pady=4)
        self.vendor_detail["api_key"].bind("<KeyRelease>", self._on_vendor_field_edit)
        self.vendor_detail["api_key"].bind("<FocusOut>", self._on_vendor_field_edit)
        btn_showkey = tk.Button(g, text="显示", font=("微软雅黑", 9), bg=COLOR_PANEL, fg=COLOR_TEXT_DIM,
                                relief="solid", bd=1, highlightbackground=COLOR_BORDER,
                                command=self._toggle_vendor_key_show)
        btn_showkey.grid(row=2, column=2, padx=(6, 0))
        # 类型与角色
        tk.Label(g, text="用途：", font=FONT_MAIN, bg=COLOR_PANEL).grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        self.vendor_detail["role"] = tk.Label(g, text="未指定", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT_DIM)
        self.vendor_detail["role"].grid(row=3, column=1, sticky="w", pady=4)

        # 模型列表
        tk.Label(self._vendor_panel, text="模型列表（该供应商提供的模型）", font=FONT_TITLE, bg=COLOR_PANEL, fg=COLOR_TEXT).pack(anchor="w", pady=(12, 6))
        tv_frame = tk.Frame(self._vendor_panel, bg=COLOR_PANEL)
        tv_frame.pack(fill="both", expand=True)
        self.vendor_tree = ttk.Treeview(tv_frame, columns=("type", "name", "display"), show="headings", height=6)
        self.vendor_tree.heading("type", text="类型")
        self.vendor_tree.heading("name", text="模型名")
        self.vendor_tree.heading("display", text="显示名")
        self.vendor_tree.column("type", width=70, anchor="center")
        self.vendor_tree.column("name", width=260)
        self.vendor_tree.column("display", width=220)
        vs = ttk.Scrollbar(tv_frame, orient="vertical", command=self.vendor_tree.yview)
        self.vendor_tree.configure(yscrollcommand=vs.set)
        self.vendor_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.vendor_tree.bind("<Double-1>", self._on_model_double_click)

        # 底部操作区
        bottom = tk.Frame(self._vendor_panel, bg=COLOR_PANEL)
        bottom.pack(fill="x", pady=(10, 0))
        btn_add_model = tk.Button(bottom, text="＋ 添加模型", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_ACCENT,
                                  relief="solid", bd=1, highlightbackground=COLOR_BORDER, command=self._add_model_dialog)
        btn_add_model.pack(side="left", padx=(0, 8))
        btn_edit_model = tk.Button(bottom, text="✎ 编辑选中模型", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_ACCENT,
                                   relief="solid", bd=1, highlightbackground=COLOR_BORDER, command=self._edit_selected_model)
        btn_edit_model.pack(side="left", padx=(0, 8))
        btn_del_model = tk.Button(bottom, text="删除选中模型", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_DANGER,
                                  relief="solid", bd=1, highlightbackground=COLOR_BORDER, command=self._delete_model)
        btn_del_model.pack(side="left", padx=(0, 8))
        btn_test = tk.Button(bottom, text="测试连接", font=FONT_MAIN, bg=COLOR_SUCCESS, fg="white",
                             relief="flat", command=self._test_vendor_conn)
        btn_test.pack(side="left", padx=(0, 8))
        bind_hover(btn_test, COLOR_SUCCESS, "#2BA24C")
        btn_role_text = tk.Button(bottom, text="设为文本供应商", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                                  relief="flat", command=lambda: self._set_vendor_role("text"))
        btn_role_text.pack(side="right", padx=(8, 0))
        bind_hover(btn_role_text, COLOR_ACCENT, COLOR_ACCENT_DARK)
        btn_role_media = tk.Button(bottom, text="设为媒体供应商", font=FONT_MAIN, bg=COLOR_ACCENT_DARK, fg="white",
                                   relief="flat", command=lambda: self._set_vendor_role("media"))
        btn_role_media.pack(side="right")
        bind_hover(btn_role_media, COLOR_ACCENT_DARK, "#00449B")
        tk.Label(self._vendor_panel, text="提示：文本供应商负责小说→剧本/分镜的 LLM 生成；媒体供应商负责图片/视频生成。\n设为文本/媒体供应商后即映射到控制台使用的模型配置，配置完成即可激活控制台。",
                 font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(anchor="w", pady=(8, 0))

        # ===== 兼容层（7 个核心控件，供 _get_api_config 等旧逻辑使用）=====
        self.entry_api_key = tk.Entry(self._vendor_panel, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.entry_base_url = tk.Entry(self._vendor_panel, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.combo_text_model = ttk.Combobox(self._vendor_panel, width=18, font=FONT_MAIN)
        self.entry_media_api_key = tk.Entry(self._vendor_panel, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.entry_media_base_url = tk.Entry(self._vendor_panel, bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.combo_img_model = ttk.Combobox(self._vendor_panel, width=18, font=FONT_MAIN)
        self.combo_vid_model = ttk.Combobox(self._vendor_panel, width=18, font=FONT_MAIN)

        # ===== AI 遥控面板（2026-08-21 作为列表「AI 遥控」条目的右侧详情）=====
        self._build_remote_panel(self._remote_panel)

    # ============ AI 遥控配置 UI（QQ 机器人 + AutoDL，2026-08-21 作为列表「AI 遥控」条目右侧详情）============
    def _build_remote_panel(self, parent):
        """AI 遥控配置面板：选中左侧列表「AI 遥控」条目时在右侧显示"""
        tk.Label(parent, text="🎛 AI 遥控配置（QQ 机器人 + AutoDL 开关；选填，不填不影响 wave漫流 使用）",
                 font=("微软雅黑", 11, "bold"), fg=COLOR_ACCENT_DARK, bg=COLOR_PANEL).pack(anchor="w", pady=(0, 6))
        rc = tk.Frame(parent, bg=COLOR_PANEL)
        rc.pack(fill="x", pady=(4, 0))
        rc.columnconfigure(1, weight=1)

        tk.Label(rc, text="QQ 机器人（在 q.qq.com 注册后填写，用于手机 QQ 遥控）：",
                 font=("微软雅黑", 9, "bold"), fg=COLOR_TEXT, bg=COLOR_PANEL
                 ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(6, 2))
        tk.Label(rc, text="AppID：", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT
                 ).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.qq_appid = tk.Entry(rc, font=FONT_MAIN, relief="solid", bd=1,
                                 bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.qq_appid.grid(row=1, column=1, sticky="ew", pady=3)
        tk.Label(rc, text="AppSecret：", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT
                 ).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        self.qq_appsecret = tk.Entry(rc, font=FONT_MAIN, relief="solid", bd=1, show="*",
                                     bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.qq_appsecret.grid(row=2, column=1, sticky="ew", pady=3)
        tk.Label(rc, text="Token：", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT
                 ).grid(row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        self.qq_token = tk.Entry(rc, font=FONT_MAIN, relief="solid", bd=1, show="*",
                                 bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.qq_token.grid(row=3, column=1, sticky="ew", pady=3)
        self.qq_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(rc, text="启用 QQ 对话", variable=self.qq_enabled, font=FONT_MAIN,
                       bg=COLOR_PANEL, fg=COLOR_TEXT, selectcolor=COLOR_INPUT,
                       activebackground=COLOR_PANEL, activeforeground=COLOR_TEXT
                       ).grid(row=4, column=0, sticky="w", pady=(4, 2))

        # AI 助手大脑（MiniMax API Key，客户自填；OpenClaw 智能对话用，不填则 QQ 遥控走固定指令路由）
        tk.Label(rc, text="AI 助手大脑（MiniMax API Key，在 platform.minimaxi.com 获取；OpenClaw 智能对话用）：",
                 font=("微软雅黑", 9, "bold"), fg=COLOR_TEXT, bg=COLOR_PANEL
                 ).grid(row=4, column=1, columnspan=2, sticky="w", pady=(12, 2))
        tk.Label(rc, text="MiniMax Key：", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT
                 ).grid(row=5, column=0, sticky="w", padx=(0, 8), pady=3)
        self.minimax_key = tk.Entry(rc, font=FONT_MAIN, relief="solid", bd=1, show="*",
                                    bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.minimax_key.grid(row=5, column=1, sticky="ew", pady=3)

        tk.Label(rc, text="AutoDL 实例（可选，QQ 远程开关你的 GPU 实例）：",
                 font=("微软雅黑", 9, "bold"), fg=COLOR_TEXT, bg=COLOR_PANEL
                 ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(12, 2))
        tk.Label(rc, text="API Token：", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT
                 ).grid(row=7, column=0, sticky="w", padx=(0, 8), pady=3)
        self.adl_token = tk.Entry(rc, font=FONT_MAIN, relief="solid", bd=1, show="*",
                                  bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.adl_token.grid(row=7, column=1, sticky="ew", pady=3)
        tk.Label(rc, text="实例 ID：", font=FONT_MAIN, bg=COLOR_PANEL, fg=COLOR_TEXT
                 ).grid(row=8, column=0, sticky="w", padx=(0, 8), pady=3)
        self.adl_instance = tk.Entry(rc, font=FONT_MAIN, relief="solid", bd=1,
                                     bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.adl_instance.grid(row=8, column=1, sticky="ew", pady=3)
        self.adl_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(rc, text="启用 AutoDL 开关", variable=self.adl_enabled, font=FONT_MAIN,
                       bg=COLOR_PANEL, fg=COLOR_TEXT, selectcolor=COLOR_INPUT,
                       activebackground=COLOR_PANEL, activeforeground=COLOR_TEXT
                       ).grid(row=9, column=0, sticky="w", pady=(4, 2))

        btn_row = tk.Frame(rc, bg=COLOR_PANEL)
        btn_row.grid(row=10, column=0, columnspan=3, sticky="w", pady=(8, 2))
        btn_save_rc = tk.Button(btn_row, text="💾 保存遥控配置", font=FONT_MAIN,
                                bg=COLOR_ACCENT, fg="white", relief="flat",
                                command=self._save_remote_config)
        btn_save_rc.pack(side="left", padx=(0, 8))
        bind_hover(btn_save_rc, COLOR_ACCENT, COLOR_ACCENT_DARK)
        btn_test_qq = tk.Button(btn_row, text="测试 QQ 连接", font=FONT_MAIN,
                                bg=COLOR_PANEL, fg=COLOR_ACCENT, relief="solid", bd=1,
                                highlightbackground=COLOR_BORDER, command=self._test_qq_config)
        btn_test_qq.pack(side="left", padx=(0, 8))
        btn_test_adl = tk.Button(btn_row, text="测试 AutoDL", font=FONT_MAIN,
                                 bg=COLOR_PANEL, fg=COLOR_ACCENT, relief="solid", bd=1,
                                 highlightbackground=COLOR_BORDER, command=self._test_autodl_config)
        btn_test_adl.pack(side="left")
        self.lbl_rc_status = tk.Label(rc, text="", font=("微软雅黑", 9), fg=COLOR_SUCCESS, bg=COLOR_PANEL)
        self.lbl_rc_status.grid(row=10, column=0, columnspan=3, sticky="w", pady=(2, 4))

        self._load_remote_config()

    # ============ AI 遥控配置逻辑（QQ 机器人 + AutoDL）============
    def _load_remote_config(self):
        """从 config.json（self.current_config）回填遥控配置"""
        try:
            cfg = self.current_config or {}
            qq = cfg.get("qq_bot", {}) or {}
            adl = cfg.get("autodl", {}) or {}
            self.qq_appid.delete(0, tk.END)
            self.qq_appid.insert(0, qq.get("appid", ""))
            self.qq_appsecret.delete(0, tk.END)
            self.qq_appsecret.insert(0, qq.get("appsecret", ""))
            self.qq_token.delete(0, tk.END)
            self.qq_token.insert(0, qq.get("token", ""))
            self.qq_enabled.set(bool(qq.get("enabled", False)))
            self.minimax_key.delete(0, tk.END)
            self.minimax_key.insert(0, adl.get("minimax_key", ""))
            self.adl_token.delete(0, tk.END)
            self.adl_token.insert(0, adl.get("api_token", ""))
            self.adl_instance.delete(0, tk.END)
            self.adl_instance.insert(0, adl.get("instance_id", ""))
            self.adl_enabled.set(bool(adl.get("enabled", False)))
        except Exception:
            pass

    def _save_remote_config(self):
        try:
            cfg = self.current_config or {}
            cfg["qq_bot"] = {
                "appid": self.qq_appid.get().strip(),
                "appsecret": self.qq_appsecret.get().strip(),
                "token": self.qq_token.get().strip(),
                "enabled": bool(self.qq_enabled.get()),
            }
            cfg["autodl"] = {
                "minimax_key": self.minimax_key.get().strip(),
                "api_token": self.adl_token.get().strip(),
                "instance_id": self.adl_instance.get().strip(),
                "enabled": bool(self.adl_enabled.get()),
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.lbl_rc_status.config(text="✔ 遥控配置已保存", fg=COLOR_SUCCESS)
            self._show_toast("遥控配置已保存", "success")
        except Exception as e:
            self.lbl_rc_status.config(text="保存失败: %s" % e, fg=COLOR_DANGER)

    def _test_qq_config(self):
        appid = self.qq_appid.get().strip()
        appsecret = self.qq_appsecret.get().strip()
        # token 仅 Webhook 模式用；WebSocket 模式只需 AppID+AppSecret，token 可留空
        if not appid or not appsecret:
            self.lbl_rc_status.config(text="QQ 配置不完整：AppID/AppSecret 必填（Token 可留空）", fg=COLOR_DANGER)
            return
        # 本地无法真正连 QQ（需 botpy + 网络），只做格式校验 + 提示
        self.lbl_rc_status.config(
            text="QQ 配置已填（AppID=%s）。保存后重启软件，启用 QQ 对话将自动拉起机器人。" % appid,
            fg=COLOR_SUCCESS)

    def _test_autodl_config(self):
        token = self.adl_token.get().strip()
        inst = self.adl_instance.get().strip()
        if not token:
            self.lbl_rc_status.config(text="AutoDL API Token 未填", fg=COLOR_DANGER)
            return
        if not inst:
            self.lbl_rc_status.config(text="AutoDL 实例 ID 未填", fg=COLOR_DANGER)
            return
        try:
            from autodl_control import query_instance_status
            result = query_instance_status(token, inst)
            if result.get("ok"):
                self.lbl_rc_status.config(text="AutoDL 连接成功：实例 %s 状态=%s" % (inst, result.get("status", "?")), fg=COLOR_SUCCESS)
            else:
                self.lbl_rc_status.config(text="AutoDL 连接失败：%s" % result.get("error", "未知错误"), fg=COLOR_DANGER)
        except Exception as e:
            self.lbl_rc_status.config(text="AutoDL 测试异常: %s" % e, fg=COLOR_DANGER)



    # ============ 供应商管理逻辑 ============
    def _current_vendors(self):
        return self.current_project["vendors"] if self.current_project else []

    def _load_vendor_list(self):
        self.vendor_listbox.delete(0, tk.END)
        for i, v in enumerate(self._current_vendors()):
            self.vendor_listbox.insert(tk.END, v.get("name", "未命名"))
            # 标记角色
            if self.current_project.get("text_vendor_id") == v.get("id"):
                self.vendor_listbox.itemconfig(i, fg=COLOR_SUCCESS)
            elif self.current_project.get("media_vendor_id") == v.get("id"):
                self.vendor_listbox.itemconfig(i, fg=COLOR_ACCENT)
        # 2026-08-21 固定条目「AI 遥控」：像供应商一样可点，选中后右侧显示遥控配置
        _ai_idx = self.vendor_listbox.size()
        self.vendor_listbox.insert(tk.END, "🎛 AI 遥控")
        self.vendor_listbox.itemconfig(_ai_idx, fg=COLOR_ACCENT_DARK)
        if self.vendor_listbox.size() > 0:
            self.vendor_listbox.selection_set(0)
            self._on_vendor_select()

    def _is_ai_remote_item(self, idx):
        """判断列表索引是否指向固定条目「AI 遥控」（在 vendors 之后）"""
        try:
            return idx >= len(self._current_vendors())
        except Exception:
            return False

    def _on_vendor_select(self, event=None):
        sel = self.vendor_listbox.curselection()
        if not sel:
            return
        # 2026-08-21 AI 遥控条目：右侧显示遥控配置面板
        if self._is_ai_remote_item(sel[0]):
            self._selected_vendor_idx = sel[0]
            self._show_remote_panel()
            return
        vendors = self._current_vendors()
        if sel[0] >= len(vendors):
            return
        self._selected_vendor_idx = sel[0]
        v = vendors[sel[0]]
        self._show_vendor_panel()
        self.vendor_detail["name"].delete(0, tk.END)
        self.vendor_detail["name"].insert(0, v.get("name", ""))
        self.vendor_detail["base_url"].delete(0, tk.END)
        self.vendor_detail["base_url"].insert(0, v.get("base_url", ""))
        self.vendor_detail["api_key"].delete(0, tk.END)
        self.vendor_detail["api_key"].insert(0, v.get("api_key", ""))
        if self.current_project.get("text_vendor_id") == v.get("id"):
            self.vendor_detail["role"].config(text="文本供应商", fg=COLOR_SUCCESS)
        elif self.current_project.get("media_vendor_id") == v.get("id"):
            self.vendor_detail["role"].config(text="媒体供应商", fg=COLOR_ACCENT)
        else:
            self.vendor_detail["role"].config(text="未指定", fg=COLOR_TEXT_DIM)
        # 模型列表
        for item in self.vendor_tree.get_children():
            self.vendor_tree.delete(item)
        for m in v.get("models", []):
            self.vendor_tree.insert("", tk.END, values=(m.get("type", ""), m.get("name", ""), m.get("display", "")))

    def _show_vendor_panel(self):
        """2026-08-21 右侧显示供应商详情面板（隐藏 AI 遥控面板）"""
        try:
            self._remote_panel.pack_forget()
            self._vendor_panel.pack(fill="both", expand=True)
        except Exception:
            pass

    def _show_remote_panel(self):
        """2026-08-21 右侧显示 AI 遥控配置面板（隐藏供应商详情面板）"""
        try:
            self._vendor_panel.pack_forget()
            self._remote_panel.pack(fill="both", expand=True)
            # 回填最新配置（确保显示的是保存过的值）
            self._load_remote_config()
        except Exception:
            pass

    def _apply_vendor_edits(self, idx=None):
        """把右侧详情写回供应商对象"""
        vendors = self._current_vendors()
        if idx is None:
            sel = self.vendor_listbox.curselection()
            if not sel or sel[0] >= len(vendors):
                return
            idx = sel[0]
        # 2026-08-21 防止 AI 遥控条目越界
        if idx >= len(vendors):
            return
        v = vendors[idx]
        v["name"] = self.vendor_detail["name"].get().strip() or v.get("name", "未命名")
        v["base_url"] = self.vendor_detail["base_url"].get().strip()
        v["api_key"] = sanitize_api_key(self.vendor_detail["api_key"].get())
        # 同步列表显示（仅在名称变化时更新，避免闪烁/丢颜色）
        old_display = self.vendor_listbox.get(idx) if idx < self.vendor_listbox.size() else None
        if old_display != v["name"]:
            self.vendor_listbox.delete(idx)
            self.vendor_listbox.insert(idx, v["name"])
            self.vendor_listbox.selection_set(idx)
            # 恢复角色颜色标记
            if self.current_project.get("text_vendor_id") == v.get("id"):
                self.vendor_listbox.itemconfig(idx, fg=COLOR_SUCCESS)
            elif self.current_project.get("media_vendor_id") == v.get("id"):
                self.vendor_listbox.itemconfig(idx, fg=COLOR_ACCENT)

    def _on_vendor_field_edit(self, event=None):
        """供应商详情输入框内容变化 → 自动写回 + 同步 + 防抖自动保存"""
        if not self.current_project:
            return
        idx = getattr(self, "_selected_vendor_idx", -1)
        if idx < 0:
            return
        try:
            # 固定用切换时记录的索引，避免 FocusOut 时 curselection 已指向新供应商
            self._apply_vendor_edits(idx=idx)
            self._sync_compat_from_vendors()
            self._update_console_state()
            # 防抖：连续输入时只保存最后一次
            if hasattr(self, "_vendor_save_after") and self._vendor_save_after:
                try:
                    self.root.after_cancel(self._vendor_save_after)
                except Exception:
                    pass
            self._vendor_save_after = self.root.after(800, self._auto_save_project)
        except Exception:
            pass

    def _sync_global_vendor_defaults(self):
        """2026-08-21 配置一次全局继承：把当前项目的供应商配置（vendors+角色）同步为全局默认，
        写入 config.json。之后新建项目自动继承，用户无需重复配置。
        保留 config.json 其他字段（遥控配置等），只更新 3 个全局字段。"""
        try:
            p = self.current_project
            if not p:
                return
            cfg = load_config()   # 合并现有文件 + 默认值，避免丢遥控配置
            cfg["global_vendors"] = [json.loads(json.dumps(v)) for v in p.get("vendors", [])]
            cfg["global_text_vendor_id"] = p.get("text_vendor_id", "")
            cfg["global_media_vendor_id"] = p.get("media_vendor_id", "")
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self.current_config = cfg   # 内存同步，下次新建项目立即可继承
        except Exception:
            pass

    def _auto_save_project(self):
        """自动保存项目（静默，无提示）"""
        self._vendor_save_after = None
        if not self.current_project:
            return
        try:
            p = self.current_project
            cfg = self._get_api_config()
            p["config"] = cfg
            p["last_saved_config"] = dict(cfg)
            p["novel"] = self.text_input_novel.get("1.0", tk.END).strip()
            p["command"] = self.text_input_command.get("1.0", tk.END).strip()
            for k in self.text_widgets:
                p["sections"][k] = self.text_widgets[k].get("1.0", tk.END).strip()
            # 记录分镜所属章节（重开项目后据此恢复，避免章节过滤失效）
            try:
                p["storyboard_chapter"] = self.combo_vid_chapter.get() if hasattr(self, 'combo_vid_chapter') else "全部章节"
            except Exception:
                p["storyboard_chapter"] = "全部章节"
            p["image_history"] = [{'url': it.get('url', ''), 'name': it.get('name', ''),
                                   'type': it.get('type', ''), 'chapter': it.get('chapter', ''),
                                   'prompt': it.get('prompt', ''), 'prompt_cn': it.get('prompt_cn', ''),
                                   'local_path': it.get('local_path', '')}
                                  for it in self.image_history]
            p["video_history"] = self.video_history
            # 2026-08-21 视频本地保存路径映射（url → 本地 mp4 路径），随项目保存
            try:
                p["video_local_paths"] = dict(getattr(self, '_video_local_paths', {}) or {})
            except Exception:
                p["video_local_paths"] = {}
            # 2026-08-21 视频预览帧目录映射（url → 帧 PNG 目录），随项目保存
            try:
                p["video_preview_frames"] = dict(getattr(self, '_video_preview_frames', {}) or {})
            except Exception:
                p["video_preview_frames"] = {}
            p["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            path = self._project_path(p["name"])
            with open(path, "w", encoding="utf-8") as f:
                json.dump(p, f, ensure_ascii=False, indent=2)
            # 2026-08-21 配置一次全局继承：自动保存时同步全局默认供应商
            self._sync_global_vendor_defaults()
        except Exception:
            pass

    def _toggle_vendor_key_show(self):
        e = self.vendor_detail["api_key"]
        e.config(show="" if e.cget("show") == "*" else "*")

    def _delete_vendor(self):
        sel = self.vendor_listbox.curselection()
        if not sel:
            messagebox.showinfo(APP_NAME, "请先选择要删除的供应商")
            return
        # 2026-08-21 AI 遥控条目不可删除
        if self._is_ai_remote_item(sel[0]):
            messagebox.showinfo(APP_NAME, "「AI 遥控」是固定配置项，不可删除")
            return
        vendors = self._current_vendors()
        idx = sel[0]
        vid = vendors[idx].get("id")
        if self.current_project.get("text_vendor_id") == vid or self.current_project.get("media_vendor_id") == vid:
            messagebox.showwarning(APP_NAME, "该供应商正在被使用（文本/媒体），请先更换角色再删除。")
            return
        if messagebox.askyesno(APP_NAME, "确定删除供应商「%s」？" % vendors[idx].get("name", "")):
            vendors.pop(idx)
            self._load_vendor_list()
            self._sync_compat_from_vendors()
            self._update_console_state()

    # ---- 添加供应商：三种方式 ----
    def _add_vendor_from_template(self):
        """方式一：从内置模板库添加"""
        templates = get_vendor_templates()
        dlg = tk.Toplevel(self.root)
        dlg.title("从模板添加供应商")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("480x360")
        try:
            dlg.iconbitmap(resource_path("app.ico"))
        except Exception:
            pass
        tk.Label(dlg, text="选择供应商模板：", font=FONT_TITLE, bg=COLOR_PANEL).pack(anchor="w", padx=14, pady=(14, 6))
        lb = tk.Listbox(dlg, font=FONT_MAIN, relief="solid", bd=1, selectbackground=COLOR_ACCENT,
                        activestyle="none", bg=COLOR_INPUT, fg=COLOR_TEXT, selectforeground="white")
        lb.pack(fill="both", expand=True, padx=14, pady=6)
        lb.bind("<Double-Button-1>", lambda e: pick())
        for t in templates:
            models = "、".join(m.get("display", m.get("name", "")) for m in t.get("models", []) if m.get("type") == "text")
            imgs = "、".join(m.get("display", m.get("name", "")) for m in t.get("models", []) if m.get("type") == "image")
            vids = "、".join(m.get("display", m.get("name", "")) for m in t.get("models", []) if m.get("type") == "video")
            lb.insert(tk.END, "%s  |  %s" % (t.get("name", ""), " / ".join(x for x in (models, imgs, vids) if x)))
        tk.Label(dlg, text="模板仅提供供应商结构与模型清单，API Key 需自行填写", font=("微软雅黑", 9),
                 fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(anchor="w", padx=14)

        def pick():
            sel = lb.curselection()
            if not sel:
                messagebox.showwarning(APP_NAME, "请先选择模板", parent=dlg)
                return
            t = templates[sel[0]]
            dlg.destroy()
            vendors = self._current_vendors()
            new_id = t["id"] + "_" + str(int(time.time()))[-5:]
            v = {"id": new_id, "name": t.get("name", "新供应商"),
                 "base_url": t.get("base_url", ""), "api_key": "",
                 "type": t.get("type", ""),
                 "models": [json.loads(json.dumps(m)) for m in t.get("models", [])]}
            vendors.append(v)
            self._load_vendor_list()
            self.vendor_listbox.selection_clear(0, tk.END)
            self.vendor_listbox.selection_set(tk.END)
            self._on_vendor_select()
            self._show_toast("已从模板添加：%s（请填写 API Key）" % v["name"], "success")

        btn = tk.Button(dlg, text="添加此模板", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                        relief="flat", padx=18, pady=4, command=pick)
        btn.pack(pady=(4, 14))
        bind_hover(btn, COLOR_ACCENT, COLOR_ACCENT_DARK)

    def _add_vendor_from_link(self):
        """方式二：从链接导入供应商配置（链接需返回供应商 JSON）"""
        dlg = tk.Toplevel(self.root)
        dlg.title("从链接导入供应商")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        try:
            dlg.iconbitmap(resource_path("app.ico"))
        except Exception:
            pass
        tk.Label(dlg, text="输入供应商配置链接（URL 需返回供应商 JSON）：", font=FONT_MAIN,
                 bg=COLOR_PANEL).pack(anchor="w", padx=14, pady=(16, 4))
        e_url = tk.Entry(dlg, font=FONT_MAIN, width=52, relief="solid", bd=1, bg=COLOR_INPUT,
                         fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        e_url.pack(padx=14, fill="x")
        tk.Label(dlg, text="JSON 格式：{\"name\":\"供应商名\",\"base_url\":\"https://...\",\"models\":[{\"name\":\"模型名\",\"type\":\"text|image|video\"}]}",
                 font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(anchor="w", padx=14, pady=(6, 10))
        st = tk.Label(dlg, text="", font=FONT_MAIN, fg=COLOR_SUCCESS, bg=COLOR_PANEL)
        st.pack(anchor="w", padx=14)

        def fetch():
            url = e_url.get().strip()
            if not url:
                messagebox.showwarning(APP_NAME, "请输入链接", parent=dlg)
                return
            try:
                st.config(text="正在获取...", fg=COLOR_TEXT_DIM)
                dlg.update_idletasks()
                r = requests.get(url, timeout=15, verify=False)
                r.raise_for_status()
                data = r.json()
                if not isinstance(data, dict) or not data.get("name"):
                    raise ValueError("返回内容不是有效的供应商配置")
                vendors = self._current_vendors()
                v = {"id": "link_" + str(int(time.time()))[-5:],
                     "name": data["name"], "base_url": data.get("base_url", ""),
                     "api_key": data.get("api_key", ""),
                     "models": data.get("models", [])}
                vendors.append(v)
                dlg.destroy()
                self._load_vendor_list()
                self.vendor_listbox.selection_clear(0, tk.END)
                self.vendor_listbox.selection_set(tk.END)
                self._on_vendor_select()
                self._show_toast("已从链接导入：%s" % v["name"], "success")
            except Exception as e:
                st.config(text="获取失败：%s" % e, fg=COLOR_DANGER)

        btn = tk.Button(dlg, text="获取并导入", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                        relief="flat", padx=18, pady=4, command=fetch)
        btn.pack(pady=(4, 16))
        bind_hover(btn, COLOR_ACCENT, COLOR_ACCENT_DARK)
        e_url.focus_set()

    def _add_vendor_from_file(self):
        """方式三：从本地文件导入供应商配置（JSON）"""
        path = filedialog.askopenfilename(
            title="选择供应商配置文件", filetypes=[("JSON 配置文件", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                data = data[0] if data else None
            if not data or not data.get("name"):
                raise ValueError("文件内容不是有效的供应商配置")
            vendors = self._current_vendors()
            v = {"id": "file_" + str(int(time.time()))[-5:],
                 "name": data["name"], "base_url": data.get("base_url", ""),
                 "api_key": data.get("api_key", ""),
                 "models": data.get("models", [])}
            vendors.append(v)
            self._load_vendor_list()
            self.vendor_listbox.selection_clear(0, tk.END)
            self.vendor_listbox.selection_set(tk.END)
            self._on_vendor_select()
            self._show_toast("已从文件导入：%s" % v["name"], "success")
        except Exception as e:
            messagebox.showerror(APP_NAME, "导入失败：%s" % e)

    # ---- 模型管理 ----
    def _add_model_dialog(self, edit_idx=None):
        sel = self.vendor_listbox.curselection()
        if not sel:
            messagebox.showinfo(APP_NAME, "请先选择供应商")
            return
        vendors = self._current_vendors()
        if sel[0] >= len(vendors):
            return
        v = vendors[sel[0]]
        is_edit = edit_idx is not None
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑模型" if is_edit else "添加模型")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        try:
            dlg.iconbitmap(resource_path("app.ico"))
        except Exception:
            pass
        tk.Label(dlg, text="模型名：", font=FONT_MAIN, bg=COLOR_PANEL).grid(row=0, column=0, padx=12, pady=(16, 4), sticky="w")
        e_name = tk.Entry(dlg, font=FONT_MAIN, width=34, relief="solid", bd=1, bg=COLOR_INPUT,
                          fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        e_name.grid(row=0, column=1, padx=12, pady=(16, 4))
        tk.Label(dlg, text="显示名：", font=FONT_MAIN, bg=COLOR_PANEL).grid(row=1, column=0, padx=12, pady=4, sticky="w")
        e_display = tk.Entry(dlg, font=FONT_MAIN, width=34, relief="solid", bd=1, bg=COLOR_INPUT,
                             fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        e_display.grid(row=1, column=1, padx=12, pady=4)
        tk.Label(dlg, text="类型：", font=FONT_MAIN, bg=COLOR_PANEL).grid(row=2, column=0, padx=12, pady=4, sticky="w")
        c_type = ttk.Combobox(dlg, values=("text", "image", "video"), width=10, font=FONT_MAIN, state="readonly")
        c_type.set("text")
        c_type.grid(row=2, column=1, padx=12, pady=4, sticky="w")
        tk.Label(dlg, text="提示：模型名需与供应商实际提供的名称一致", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).grid(row=3, column=0, columnspan=2, padx=12, pady=(2, 8), sticky="w")
        # 编辑模式预填
        if is_edit:
            m = v.get("models", [])[edit_idx]
            e_name.insert(0, m.get("name", ""))
            e_display.insert(0, m.get("display", ""))
            c_type.set(m.get("type", "text"))

        def on_ok():
            name = e_name.get().strip()
            if not name:
                messagebox.showwarning(APP_NAME, "请填写模型名", parent=dlg)
                return
            entry = {"name": name, "type": c_type.get(),
                     "display": e_display.get().strip() or name}
            if is_edit:
                v.setdefault("models", [])[edit_idx] = entry
            else:
                v.setdefault("models", []).append(entry)
            dlg.destroy()
            self._on_vendor_select()
            self._sync_compat_from_vendors()
            self._show_toast(("模型已更新：" if is_edit else "模型已添加：") + name, "success")

        btn = tk.Button(dlg, text="确定保存" if is_edit else "确定添加", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                        relief="flat", padx=18, pady=4, command=on_ok)
        btn.grid(row=4, column=0, columnspan=2, pady=(8, 16))
        bind_hover(btn, COLOR_ACCENT, COLOR_ACCENT_DARK)

    def _on_model_double_click(self, event=None):
        """双击模型列表行 -> 打开编辑对话框（用于填写接入点等）"""
        sel = self.vendor_listbox.curselection()
        cur = self.vendor_tree.selection()
        if not sel or not cur:
            return
        idx = self.vendor_tree.index(cur[0])
        self._add_model_dialog(edit_idx=idx)

    def _edit_selected_model(self):
        """「✎ 编辑选中模型」按钮：打开编辑对话框填写模型名/接入点"""
        sel = self.vendor_listbox.curselection()
        if not sel:
            messagebox.showinfo(APP_NAME, "请先选择供应商")
            return
        cur = self.vendor_tree.selection()
        if not cur:
            messagebox.showinfo(APP_NAME, "请先在模型列表中选择要编辑的模型")
            return
        idx = self.vendor_tree.index(cur[0])
        self._add_model_dialog(edit_idx=idx)

    def _delete_model(self):
        sel = self.vendor_listbox.curselection()
        if not sel:
            return
        vendors = self._current_vendors()
        v = vendors[sel[0]]
        cur = self.vendor_tree.selection()
        if not cur:
            messagebox.showinfo(APP_NAME, "请先在模型列表中选择要删除的模型")
            return
        idx = self.vendor_tree.index(cur[0])
        m = v.get("models", [])[idx]
        if messagebox.askyesno(APP_NAME, "确定删除模型「%s」？" % m.get("display", m.get("name", ""))):
            v.get("models", []).pop(idx)
            self._on_vendor_select()
            self._sync_compat_from_vendors()
            self._update_console_state()

    # ---- 角色映射与测试 ----
    def _set_vendor_role(self, role):
        self._apply_vendor_edits()
        sel = self.vendor_listbox.curselection()
        if not sel:
            return
        # 2026-08-21 AI 遥控条目不可设角色
        if self._is_ai_remote_item(sel[0]):
            self._show_toast("「AI 遥控」不是供应商，不能设为文本/媒体供应商", "warning")
            return
        vendors = self._current_vendors()
        vid = vendors[sel[0]].get("id")
        if role == "text":
            self.current_project["text_vendor_id"] = vid
        else:
            self.current_project["media_vendor_id"] = vid
        self._load_vendor_list()
        self._sync_compat_from_vendors()
        self._update_console_state()
        self._show_toast("已设为" + ("文本供应商" if role == "text" else "媒体供应商"), "success")

    def _sync_compat_from_vendors(self):
        """把 文本/媒体 供应商映射到 7 个核心控件（旧逻辑兼容层）"""
        vendors = self._current_vendors()
        if not self.current_project:
            return
        tv = next((v for v in vendors if v.get("id") == self.current_project.get("text_vendor_id")), None)
        mv = next((v for v in vendors if v.get("id") == self.current_project.get("media_vendor_id")), None)
        if tv:
            text_model = next((m for m in tv.get("models", []) if m.get("type") == "text"), None)
            self.entry_api_key.delete(0, tk.END); self.entry_api_key.insert(0, tv.get("api_key", ""))
            self.entry_base_url.delete(0, tk.END); self.entry_base_url.insert(0, tv.get("base_url", ""))
            self.combo_text_model["values"] = [m.get("name", "") for m in tv.get("models", []) if m.get("type") == "text"]
            if text_model:
                self.combo_text_model.delete(0, tk.END)
                self.combo_text_model.insert(0, text_model.get("name", ""))
        if mv:
            img_model = next((m for m in mv.get("models", []) if m.get("type") == "image"), None)
            vid_model = next((m for m in mv.get("models", []) if m.get("type") == "video"), None)
            self.entry_media_api_key.delete(0, tk.END); self.entry_media_api_key.insert(0, mv.get("api_key", ""))
            self.entry_media_base_url.delete(0, tk.END); self.entry_media_base_url.insert(0, mv.get("base_url", ""))
            self.combo_img_model["values"] = [m.get("name", "") for m in mv.get("models", []) if m.get("type") == "image"]
            self.combo_vid_model["values"] = [m.get("name", "") for m in mv.get("models", []) if m.get("type") == "video"]
            # 图像模型：无则填第一个
            if img_model:
                cur = self.combo_img_model.get().strip()
                if cur not in [m.get("name", "") for m in mv.get("models", []) if m.get("type") == "image"]:
                    self.combo_img_model.delete(0, tk.END)
                    self.combo_img_model.insert(0, img_model.get("name", ""))
            # 视频模型：保持用户当前选择（避免 sync 把 h3 强制改回 ltx23），仅当选择失效时才回填第一个
            cur_vid = self.combo_vid_model.get().strip()
            vid_names = [m.get("name", "") for m in mv.get("models", []) if m.get("type") == "video"]
            if cur_vid not in vid_names:
                if vid_model:
                    self.combo_vid_model.delete(0, tk.END)
                    self.combo_vid_model.insert(0, vid_model.get("name", ""))
                else:
                    self.combo_vid_model.delete(0, tk.END)

    def _test_vendor_conn(self):
        """测试当前供应商连接（ComfyUI 走 /system_stats；其他走 /models）"""
        self._apply_vendor_edits()
        sel = self.vendor_listbox.curselection()
        if not sel:
            return
        vendors = self._current_vendors()
        v = vendors[sel[0]]
        base = v.get("base_url", "").strip()
        key = sanitize_api_key(v.get("api_key", ""))
        try:
            if self._is_comfyui_vendor(v):
                # ComfyUI：GET /system_stats 验证连接（无需 API Key，端口含在地址里）
                url = base.rstrip("/") + "/system_stats"
                r = requests.get(url, timeout=15, verify=False)
                if r.status_code == 200:
                    data = r.json()
                    ver = (data.get("system") or {}).get("comfyui_version", "未知")
                    messagebox.showinfo(APP_NAME, "ComfyUI 连接成功！\n服务地址（含端口）：%s\nComfyUI 版本：%s" % (base, ver))
                else:
                    messagebox.showerror(APP_NAME, "连接失败（HTTP %s）\n%s" % (r.status_code, r.text[:300]))
                return
            if not key:
                messagebox.showwarning(APP_NAME, "请先填写该供应商的 API Key")
                return
            url = base.rstrip("/") + "/models"
            r = requests.get(url, headers={"Authorization": "Bearer " + key}, timeout=15, verify=False)
            if r.status_code == 200:
                data = r.json()
                models = []
                if isinstance(data, dict):
                    models = data.get("data", []) or data.get("models", [])
                names = [m.get("id", m.get("name", "")) for m in models][:12] if isinstance(models, list) else []
                messagebox.showinfo(APP_NAME, "连接成功！\n供应商：%s\n返回模型数：%s\n示例：%s" % (
                    v.get("name", ""), len(names), "、".join(names) if names else "（该接口未返回模型列表，可手动添加）"))
            else:
                messagebox.showerror(APP_NAME, "连接失败（HTTP %s）\n%s" % (r.status_code, r.text[:300]))
        except Exception as e:
            messagebox.showerror(APP_NAME, "连接失败：%s" % e)

    def _is_comfyui_vendor(self, v):
        """判断供应商是否为云端 ComfyUI（优先显式 type 标记，其次地址/模型名兜底）"""
        if (v.get("type") or "").strip().lower() == "comfyui":
            return True
        base = (v.get("base_url") or "").strip().lower()
        names = " ".join((m.get("name") or "") for m in v.get("models", [])).lower()
        return any(k in base for k in ("8188", "15794", "8800", "comfy")) or "comfyui" in names

    def _update_console_state(self):
        """控制台激活条件：文本供应商 + 媒体供应商 均已配置（ComfyUI 无需 API Key）"""
        if not self.current_project:
            return
        vendors = self._current_vendors()
        tv = next((v for v in vendors if v.get("id") == self.current_project.get("text_vendor_id")), None)
        mv = next((v for v in vendors if v.get("id") == self.current_project.get("media_vendor_id")), None)
        text_ok = bool(tv and sanitize_api_key(tv.get("api_key", "")))
        media_ok = bool(mv and (self._is_comfyui_vendor(mv) or sanitize_api_key(mv.get("api_key", ""))))
        if text_ok and media_ok:
            # 2026-08-21 配置完成后统一激活：控制台/生成器/单镜工作台（剪辑 tab 已隐藏）
            for _i in range(1, 4):
                self.notebook.tab(_i, state="normal")
        else:
            for _i in range(1, 4):
                self.notebook.tab(_i, state="disabled")
            # 未配置完成时强制停在「配置」页，不允许停留在其他功能页
            try:
                if self.notebook.index(self.notebook.select()) != 0:
                    self.notebook.select(0)
            except Exception:
                pass

    def _start_btn_timeout_watch(self):
        """2026-08-21 需求2：批量生成按钮超时自动恢复看门狗（每 15 秒查一次，3 分钟强制恢复）"""
        try:
            def _tick():
                try:
                    now = time.time()
                    for _k, _ts in list(self._btn_lock_times.items()):
                        if now - _ts > self._btn_timeout_seconds:
                            # 超时强制恢复按钮
                            if _k == 'gen_img':
                                for _b in (self.btn_gen_img, self.btn_gen_images_batch):
                                    try:
                                        _b.config(state=tk.NORMAL)
                                    except Exception:
                                        pass
                            elif _k == 'gen_vid':
                                for _b in (self.btn_gen_vid, self.btn_gen_sb_all):
                                    try:
                                        _b.config(state=tk.NORMAL)
                                    except Exception:
                                        pass
                            self._btn_lock_times.pop(_k, None)
                            self._show_toast('生成任务疑似卡死（超时 %d 秒），按钮已重新激活，可重新提交' % self._btn_timeout_seconds, 'warning')
                except Exception:
                    pass
                try:
                    self.root.after(15000, _tick)
                except Exception:
                    pass
            self.root.after(15000, _tick)
        except Exception:
            pass



    # ============ 控制台Tab：布局 ============
    def _build_console_area(self, parent):
        # 底部按钮栏（固定在控制台底部，始终可见）
        self._build_bottom_area(parent)
        # 主分栏
        self.console_split = tk.PanedWindow(parent, orient=tk.HORIZONTAL, bg=COLOR_PANEL,
                                            sashwidth=6, sashrelief=tk.FLAT)
        self.console_split.pack(fill="both", expand=True, padx=10, pady=6)
        self._build_input_area(self.console_split)
        self._build_output_area(self.console_split)
        self.console_split.paneconfig(self.frame_input_area, width=380)
        self.console_split.paneconfig(self.frame_output_area, width=900)

    def _build_input_area(self, parent):
        self.frame_input_area = tk.Frame(parent, bg=COLOR_PANEL, highlightbackground=COLOR_BORDER,
                                         highlightthickness=1)
        # 垂直分栏：上=小说输入，下=附加指令（拖动分隔条调节高度，两个输入框永远可见）
        self.input_paned = tk.PanedWindow(self.frame_input_area, orient=tk.VERTICAL,
                                          bg=COLOR_PANEL, sashwidth=6, sashrelief=tk.FLAT)
        self.input_paned.pack(fill="both", expand=True, padx=2, pady=2)

        # 上：小说文本输入
        frame_novel = tk.Frame(self.input_paned, bg=COLOR_PANEL)
        self.input_paned.add(frame_novel, minsize=120)
        novel_bar = tk.Frame(frame_novel, bg=COLOR_PANEL)
        novel_bar.pack(fill="x", anchor="w", padx=8, pady=(8, 4))
        tk.Label(novel_bar, text="▼ 小说文本输入", font=FONT_TITLE, bg=COLOR_PANEL,
                 fg=COLOR_TEXT).pack(side="left")
        # 2026-08-13 按需求创作模式：用户不提供小说，只输入创作需求（如"生成红果短剧风格小说"），
        # LLM 自己创作剧本正文 + 后续资产。选中后标签变"创作需求输入"。
        self._create_mode_var = tk.BooleanVar(value=False)
        self._create_mode_chk = tk.Checkbutton(novel_bar, text="✍️ 按需求创作（无小说）",
                                               font=("微软雅黑", 9), bg=COLOR_PANEL,
                                               fg=COLOR_ACCENT, selectcolor=COLOR_PANEL,
                                               activebackground=COLOR_PANEL,
                                               variable=self._create_mode_var,
                                               command=self._on_create_mode_toggle)
        self._create_mode_chk.pack(side="left", padx=(10, 0))
        # 上传小说文件（doc/docx/txt → 解析章节 → 填入输入框）
        self.btn_upload_novel = tk.Button(novel_bar, text="📄 上传小说文件", font=("微软雅黑", 9),
                                          bg=COLOR_ACCENT, fg="white", relief="flat",
                                          padx=10, pady=1, command=self._upload_novel_file)
        self.btn_upload_novel.pack(side="left", padx=(10, 0))
        bind_hover(self.btn_upload_novel, COLOR_ACCENT, COLOR_ACCENT_DARK)
        # 章节状态标签（上传后显示识别到的章节数；章节选择在视频生成Tab）
        self.label_chapter_info = tk.Label(novel_bar, text="", font=("微软雅黑", 9),
                                           bg=COLOR_PANEL, fg=COLOR_SUCCESS)
        self.label_chapter_info.pack(side="left", padx=(10, 0))
        # 题材选择器（Toonflow 导演技法集成）
        tk.Label(novel_bar, text="  题材：", font=("微软雅黑", 9), bg=COLOR_PANEL,
                 fg=COLOR_TEXT_DIM).pack(side="left", padx=(16, 0))
        self._genre_var = tk.StringVar(value="通用")
        genre_values = ["通用"] + list(GENRE_DIRECTOR_SKILLS.keys())
        self._genre_combo = ttk.Combobox(novel_bar, textvariable=self._genre_var,
                                         values=genre_values, state="readonly",
                                         width=10, font=("微软雅黑", 9))
        self._genre_combo.pack(side="left")
        tk.Label(novel_bar, text="（导演手法随生成自动注入）", font=("微软雅黑", 8),
                 bg=COLOR_PANEL, fg=COLOR_TEXT_DIM).pack(side="left", padx=(6, 0))
        # 全局风格选择器（用户要求：风格放小说旁，全局有效——图片/视频/提示词统一遵循）
        tk.Label(novel_bar, text="  风格：", font=("微软雅黑", 9), bg=COLOR_PANEL,
                 fg=COLOR_TEXT_DIM).pack(side="left", padx=(16, 0))
        self._style_var = tk.StringVar(value=DEFAULT_VIDEO_STYLE)
        self.combo_global_style = ttk.Combobox(novel_bar, textvariable=self._style_var,
                                               values=list(VIDEO_STYLE_PRESETS.keys()),
                                               state="readonly", width=10, font=("微软雅黑", 9))
        self.combo_global_style.pack(side="left")
        tk.Label(novel_bar, text="（全局风格：图片+视频+提示词统一生效）", font=("微软雅黑", 8),
                 bg=COLOR_PANEL, fg=COLOR_TEXT_DIM).pack(side="left", padx=(6, 0))
        self.text_input_novel = scrolledtext.ScrolledText(
            frame_novel, font=FONT_MAIN, wrap=tk.WORD, height=12, relief="solid", bd=1,
            bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.text_input_novel.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # 下：附加指令（标签 + 上传按钮 + 输入框）
        frame_cmd = tk.Frame(self.input_paned, bg=COLOR_PANEL)
        self.input_paned.add(frame_cmd, minsize=120)
        tk.Label(frame_cmd, text="▼ 附加指令/诉求", font=FONT_TITLE, bg=COLOR_PANEL,
                 fg=COLOR_TEXT).pack(anchor="w", padx=8, pady=(6, 4))
        cmd_bar = tk.Frame(frame_cmd, bg=COLOR_PANEL)
        cmd_bar.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(cmd_bar, text="填写后点击上传，随小说一起发送给模型",
                 font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(side="left")
        self.btn_upload_command = tk.Button(cmd_bar, text="▲ 上传指令", font=("微软雅黑", 9),
                                            bg=COLOR_ACCENT, fg="white", relief="flat",
                                            padx=12, pady=1, command=self._upload_command)
        self.btn_upload_command.pack(side="right")
        bind_hover(self.btn_upload_command, COLOR_ACCENT, COLOR_ACCENT_DARK)
        self.text_input_command = scrolledtext.ScrolledText(
            frame_cmd, font=FONT_MAIN, wrap=tk.WORD, height=8, relief="solid", bd=1,
            bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.text_input_command.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _on_create_mode_toggle(self):
        """按需求创作模式开关：切换小说输入框的标签提示，并同步章节下拉为"全部章节"。"""
        try:
            _on = bool(getattr(self, '_create_mode_var', None) and self._create_mode_var.get())
            # 更新标题标签（找到 novel_bar 的第一个 Label）
            _parent = self._create_mode_chk.master
            for _w in _parent.winfo_children():
                if isinstance(_w, tk.Label) and '小说' in str(_w.cget('text')):
                    _w.config(text='▼ 创作需求输入' if _on else '▼ 小说文本输入')
                    break
            # 创作模式下章节无意义，强制"全部章节"
            try:
                if _on and hasattr(self, 'combo_vid_chapter'):
                    self.combo_vid_chapter.set('全部章节')
            except Exception:
                pass
        except Exception:
            pass

    def _upload_novel_file(self):
        """上传小说文件（doc/docx/txt）：解析全文 → 识别章节 → 填入输入框 + 章节下拉"""
        path = filedialog.askopenfilename(title="选择小说文件", filetypes=[
            ('小说文件', '*.docx *.doc *.txt'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            # 后台线程读文件（docx 解析可能稍慢）
            def _worker():
                try:
                    from skills.doc_reader import read_novel_file, split_chapters
                    text = read_novel_file(path)
                    chapters = split_chapters(text)
                    self.root.after(0, lambda: self._apply_novel_file(path, text, chapters))
                except Exception as e:
                    self.root.after(0, lambda: self._show_toast('小说解析失败: %s' % e, 'error'))
            threading.Thread(target=_worker, daemon=True).start()
            self._show_toast('正在解析小说文件...', 'info')
        except Exception as e:
            self._show_toast('读取失败: %s' % e, 'error')

    def _apply_novel_file(self, path, text, chapters):
        """主线程：把解析结果填入输入框 + 刷新视频Tab章节下拉"""
        self.text_input_novel.delete('1.0', tk.END)
        self.text_input_novel.insert('1.0', text)
        # 记录章节信息（供视频Tab章节选择/图片章节标记）
        self.novel_chapters = chapters
        names = [c[0] for c in chapters]
        if names:
            self.label_chapter_info.config(text="共识别 %d 章：%s..." % (len(names), "、".join(names[:3])),
                                           fg=COLOR_SUCCESS)
            # 刷新视频Tab的章节下拉（章节选择只在这里）
            try:
                self.combo_vid_chapter.config(values=["全部章节"] + names)
                self.combo_vid_chapter.set("全部章节")
            except Exception:
                pass
        else:
            self.label_chapter_info.config(text="未识别到章节标题（按全文处理）", fg=COLOR_TEXT_DIM)
            try:
                self.combo_vid_chapter.config(values=["全部章节"])
                self.combo_vid_chapter.set("全部章节")
            except Exception:
                pass
        self._show_toast('小说已导入：%s（%d 章）' % (os.path.basename(path), len(chapters) or 1), 'success')

    def _current_chapter_text(self):
        """取当前章节选择对应的正文（全部章节=全文；选具体章=该章正文）。
        章节选择在视频Tab（combo_vid_chapter）。"""
        sel = self.combo_vid_chapter.get() if hasattr(self, 'combo_vid_chapter') else "全部章节"
        chs = getattr(self, 'novel_chapters', None)
        if not chs or sel == "全部章节":
            return self.text_input_novel.get('1.0', tk.END).strip()
        for title, body in chs:
            if title == sel:
                return body
        return self.text_input_novel.get('1.0', tk.END).strip()

    def _upload_command(self):
        """上传附加指令：写回项目 + 保存副本 + 提示"""
        if not self.current_project:
            self._show_toast("请先打开项目", "warning")
            return
        cmd = self.text_input_command.get("1.0", tk.END).strip()
        self.current_project["command"] = cmd
        # 保存上传副本（生成时优先使用已上传的指令）
        self.uploaded_command = cmd
        self._auto_save_project()
        if cmd:
            preview = cmd if len(cmd) <= 30 else cmd[:30] + "…"
            self._show_toast("✅ 指令已上传：" + preview, "success")
        else:
            self._show_toast("指令已上传（内容为空，生成时无附加指令）", "info")

    def _build_bottom_area(self, parent):
        frame = tk.Frame(parent, bg=COLOR_PANEL)
        frame.pack(fill="x", side="bottom", padx=10, pady=(0, 10))
        # 2026-08-21 续写下一集：勾选后点「开始转化」→ 检测上一集资产已生成 → 自动开始第 N+1 集生成
        self._continue_var = tk.BooleanVar(value=False)
        self.chk_continue = tk.Checkbutton(frame, text="⏭ 续写下一集", font=("微软雅黑", 10),
                                           bg=COLOR_PANEL, fg=COLOR_ACCENT, selectcolor=COLOR_PANEL,
                                           activebackground=COLOR_PANEL, activeforeground=COLOR_ACCENT,
                                           variable=self._continue_var,
                                           command=self._on_continue_toggle)
        self.chk_continue.pack(side="left", padx=(0, 8))
        self.btn_generate = tk.Button(frame, text="▶ 开始转化", font=FONT_TITLE, bg=COLOR_ACCENT,
                                      fg="white", relief="flat", padx=16, pady=2,
                                      activebackground=COLOR_ACCENT_DARK, activeforeground="white",
                                      command=self._on_generate_click)
        self.btn_generate.pack(side="left", fill="x", expand=True)
        bind_hover(self.btn_generate, COLOR_ACCENT, COLOR_ACCENT_DARK)
        self.btn_clear_assets = tk.Button(frame, text="🧹 清除资产", font=FONT_TITLE, bg="#8E8E93",
                                          fg="white", relief="flat", padx=16, pady=2,
                                          activebackground="#6E6E73", activeforeground="white",
                                          command=self._clear_all_assets)
        self.btn_clear_assets.pack(side="left", padx=(8, 0))
        bind_hover(self.btn_clear_assets, "#8E8E93", "#6E6E73")
        self.btn_stop = tk.Button(frame, text="■ 停止生成", font=FONT_TITLE, bg="#D63027", fg="white",
                                  relief="flat", padx=16, pady=2, state=tk.DISABLED,
                                  activebackground="#A82820", activeforeground="white",
                                  command=self._on_stop_click)
        self.btn_stop.pack(side="left", padx=(8, 0))
        bind_hover(self.btn_stop, "#D63027", "#A82820")
        bar_frame = tk.Frame(frame, bg=COLOR_PANEL)
        bar_frame.pack(fill="x", pady=(8, 0))
        self.progress_bar = ttk.Progressbar(bar_frame, mode="indeterminate", style="Light.Horizontal.TProgressbar")
        self.progress_bar.pack(fill="x")
        self.label_gen_time = tk.Label(bar_frame, text="就绪", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM,
                                       bg=COLOR_PANEL)
        self.label_gen_time.pack(anchor="w", pady=(2, 0))

    def _on_continue_toggle(self):
        """2026-08-21 续写复选框交互提示：勾选时检查是否有上一集资产可续写"""
        try:
            if self._continue_var.get():
                _ep = int((self.current_project or {}).get('episode', 0) or 0)
                _secs = (self.current_project or {}).get('sections', {}) or {}
                _assets_done = any(
                    ((_secs.get(k) or '').strip() or
                     (self.text_widgets.get(k).get('1.0', tk.END).strip() if self.text_widgets.get(k) else ''))
                    for k in ('character', 'scene', 'prop'))
                if _assets_done:
                    self._show_toast('⏭ 续写模式已开启：检测到第 %d 集资产已生成，开始转化后将自动生成第 %d 集'
                                     % (_ep if _ep >= 1 else 1, (_ep if _ep >= 1 else 1) + 1), 'info')
                else:
                    self._show_toast('⚠️ 当前未检测到已生成的资产（角色/场景/道具），续写将无法开始。\n'
                                     '请先完成第 1 集的全链路生成，再勾选续写。', 'warning')
            else:
                self._show_toast('续写已关闭：开始转化将从第 1 集（小说开头）生成', 'info')
        except Exception:
            pass

    def _build_output_area(self, parent):
        self.frame_output_area = tk.Frame(parent, bg=COLOR_PANEL, highlightbackground=COLOR_BORDER,
                                          highlightthickness=1)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Out.TNotebook", background=COLOR_PANEL, borderwidth=0)
        style.configure("Out.TNotebook.Tab", font=FONT_MAIN, padding=(12, 6))
        self.notebook_out = ttk.Notebook(self.frame_output_area, style="Out.TNotebook")
        self.notebook_out.pack(fill="both", expand=True)

        sections = [
            ("all", "全文展示"), ("script", "剧本正文"), ("character", "角色资产"),
            ("scene", "场景资产"), ("prop", "道具资产"), ("global_plan", "全局分镜规划"),
            ("storyboard", "分镜资产"), ("editing", "剪辑方案"),
        ]
        for key, label in sections:
            tab = tk.Frame(self.notebook_out, bg=COLOR_PANEL)
            self.notebook_out.add(tab, text="  " + label + "  ")
            if key == "all":
                top = tk.Frame(tab, bg=COLOR_PANEL)
                top.pack(fill="x", padx=6, pady=(6, 2))
                btn_copy = tk.Button(top, text="一键复制全文", font=("微软雅黑", 9), bg=COLOR_PANEL,
                                     fg=COLOR_TEXT_DIM, relief="solid", bd=1, highlightbackground="#D0D0D0",
                                     command=self._copy_all_text)
                btn_copy.pack(side="right")
            txt = scrolledtext.ScrolledText(tab, font=FONT_CODE, wrap=tk.WORD, relief="solid", bd=1,
                                            bg=COLOR_INPUT, fg=COLOR_TEXT, state=tk.DISABLED,
                                            insertbackground=COLOR_TEXT)
            txt.pack(fill="both", expand=True, padx=6, pady=6)
            self.text_widgets[key] = txt

    # ---- 生成器 Tab：左右分栏 = 图片生成(左) + 视频生成(右) ----
    def _build_generator_area(self, parent):
        paned_gen = tk.PanedWindow(parent, orient=tk.HORIZONTAL, sashwidth=8, sashrelief=tk.RAISED,
                                   bg=COLOR_INPUT)
        paned_gen.pack(fill="both", expand=True, padx=5, pady=5)
        # 左半屏：图片生成（含音色匹配）
        self.frame_img = tk.Frame(paned_gen, bg=COLOR_PANEL)
        paned_gen.add(self.frame_img, minsize=420)
        self._build_image_tab(self.frame_img)
        # 右半屏：视频生成（分镜分区：左参考图 + 右提示词）
        self.frame_vid = tk.Frame(paned_gen, bg=COLOR_PANEL)
        paned_gen.add(self.frame_vid, minsize=500)
        self._build_video_tab(self.frame_vid)

    # ============================================================
    # 剪辑工作台（分镜视频 → 轨道列表 → FCP XML / SRT 导出）
    # ============================================================
    def _build_edit_tab(self, parent):
        """剪辑工作台：剪映式三区布局（素材区/预览区/属性区 + 底部时间线）。
        2026-08-17 重构：替换原表单式布局为 EditStudio（对齐 Cosmius/剪映）"""
        if EditStudio is None:
            # 回退：旧表单式布局
            self._build_edit_tab_legacy(parent)
            return
        try:
            self.edit_studio = EditStudio(
                parent, self,
                colors={
                    'panel': COLOR_PANEL, 'input': COLOR_INPUT, 'text': COLOR_TEXT,
                    'dim': COLOR_TEXT_DIM, 'border': COLOR_BORDER, 'accent': COLOR_ACCENT,
                    'accent_dark': COLOR_ACCENT_DARK, 'credits': COLOR_CREDITS,
                },
                fonts={'main': FONT_MAIN},
                bind_hover=bind_hover,
            )
            # 首次进入自动同步轨道 + 刷新素材
            self.edit_studio.sync_tracks()
        except Exception as e:
            self.ctx.log("[系统日志] 剪辑工作台初始化失败，回退旧版: %s\n" % e)
            self._build_edit_tab_legacy(parent)

    def _build_edit_tab_legacy(self, parent):
        """旧版剪辑 Tab（回退用）"""
        frm = tk.Frame(parent, bg=COLOR_PANEL)
        frm.pack(fill="both", expand=True, padx=12, pady=10)
        tk.Label(frm, text="▼ 剪辑工作台（分镜视频按序成片 → 时间线编辑 → 导出 FCP XML/字幕给剪映/Pr/达芬奇）",
                 font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(anchor="w")
        # 操作按钮行
        btns = tk.Frame(frm, bg=COLOR_PANEL)
        btns.pack(fill="x", pady=(6, 4))
        self.btn_edit_sync = tk.Button(btns, text="🔄 同步轨道", font=("微软雅黑", 9),
                                       bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                       command=self._sync_edit_tracks)
        self.btn_edit_sync.pack(side="left", padx=(0, 6))
        bind_hover(self.btn_edit_sync, COLOR_BORDER, "#D0D0D0")
        self.btn_edit_export = tk.Button(btns, text="🎬 导出成片（FCP XML）", font=("微软雅黑", 9),
                                         bg="#28A745", fg="white", relief=tk.FLAT,
                                         command=self._export_fcpxml)
        self.btn_edit_export.pack(side="left", padx=(0, 6))
        bind_hover(self.btn_edit_export, "#28A745", "#1F8B38")
        self.btn_edit_srt = tk.Button(btns, text="💬 导出字幕（SRT）", font=("微软雅黑", 9),
                                      bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                      command=self._export_srt)
        self.btn_edit_srt.pack(side="left", padx=(0, 6))
        bind_hover(self.btn_edit_srt, COLOR_BORDER, "#D0D0D0")
        self.btn_edit_import = tk.Button(btns, text="📂 导入 FCP XML", font=("微软雅黑", 9),
                                         bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                         command=self._import_fcpxml)
        self.btn_edit_import.pack(side="left")
        bind_hover(self.btn_edit_import, COLOR_BORDER, "#D0D0D0")
        self.btn_edit_srt_import = tk.Button(btns, text="💬 导入 SRT 字幕", font=("微软雅黑", 9),
                                             bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                             command=self._import_srt)
        self.btn_edit_srt_import.pack(side="left", padx=(6, 0))
        bind_hover(self.btn_edit_srt_import, COLOR_BORDER, "#D0D0D0")
        tk.Label(btns, text="  帧率:", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(side="left")
        self.combo_edit_fps = ttk.Combobox(btns, values=("24", "25", "30"), width=4,
                                           state="readonly", font=FONT_MAIN)
        self.combo_edit_fps.set("25")
        self.combo_edit_fps.pack(side="left")
        # 片段属性编辑行（选中片段后显示）
        prop_row = tk.Frame(frm, bg=COLOR_PANEL)
        prop_row.pack(fill="x", pady=2)
        tk.Label(prop_row, text="选中片段：", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM,
                 bg=COLOR_PANEL).pack(side="left")
        self.label_edit_sel = tk.Label(prop_row, text="（未选中）", font=("微软雅黑", 9),
                                       fg=COLOR_TEXT, bg=COLOR_PANEL, width=20, anchor="w")
        self.label_edit_sel.pack(side="left")
        tk.Label(prop_row, text="裁剪起点(s):", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM,
                 bg=COLOR_PANEL).pack(side="left", padx=(8, 2))
        self.entry_edit_trim = tk.Entry(prop_row, width=5, font=FONT_MAIN, bg=COLOR_INPUT,
                                        fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.entry_edit_trim.pack(side="left")
        tk.Label(prop_row, text="变速(x):", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM,
                 bg=COLOR_PANEL).pack(side="left", padx=(8, 2))
        self.entry_edit_speed = tk.Entry(prop_row, width=5, font=FONT_MAIN, bg=COLOR_INPUT,
                                         fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.entry_edit_speed.pack(side="left")
        tk.Label(prop_row, text="音量(%):", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM,
                 bg=COLOR_PANEL).pack(side="left", padx=(8, 2))
        self.entry_edit_vol = tk.Entry(prop_row, width=5, font=FONT_MAIN, bg=COLOR_INPUT,
                                       fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.entry_edit_vol.pack(side="left")
        self.btn_edit_apply = tk.Button(prop_row, text="应用", font=("微软雅黑", 9),
                                        bg=COLOR_ACCENT, fg="white", relief=tk.FLAT,
                                        command=self._apply_clip_props)
        self.btn_edit_apply.pack(side="left", padx=(8, 0))
        bind_hover(self.btn_edit_apply, COLOR_ACCENT, COLOR_ACCENT_DARK)
        # 静音勾选（对齐 Cosmius：mute 音频）
        self.var_edit_mute = tk.BooleanVar(value=False)
        self.chk_edit_mute = tk.Checkbutton(prop_row, text="静音", variable=self.var_edit_mute,
                                            font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL,
                                            activebackground=COLOR_PANEL, selectcolor=COLOR_INPUT,
                                            command=self._apply_clip_props)
        self.chk_edit_mute.pack(side="left", padx=(8, 0))
        # 转场类型（对齐 Cosmius：transitionIn/Out，dissolve）
        tk.Label(prop_row, text="转场:", font=("微软雅黑", 9), fg=COLOR_TEXT_DIM,
                 bg=COLOR_PANEL).pack(side="left", padx=(8, 2))
        self.combo_edit_trans = ttk.Combobox(prop_row, values=("无", "交叉溶解"), width=8,
                                             state="readonly", font=FONT_MAIN)
        self.combo_edit_trans.set("无")
        self.combo_edit_trans.pack(side="left")
        self.btn_edit_dup = tk.Button(prop_row, text="📄 复制片段", font=("微软雅黑", 9),
                                      bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                      command=self._duplicate_clip)
        self.btn_edit_dup.pack(side="left", padx=(8, 0))
        bind_hover(self.btn_edit_dup, COLOR_BORDER, "#D0D0D0")
        self.btn_edit_del = tk.Button(prop_row, text="🗑 删除片段", font=("微软雅黑", 9),
                                      bg=COLOR_DANGER, fg="white", relief=tk.FLAT,
                                      command=self._delete_clip)
        self.btn_edit_del.pack(side="left", padx=(6, 0))
        bind_hover(self.btn_edit_del, COLOR_DANGER, "#C0392B")
        # 时间线 Canvas（横向轨道条 + 片段块）
        tl_frame = tk.Frame(frm, bg=COLOR_PANEL)
        tl_frame.pack(fill="both", expand=True, pady=4)
        self.edit_canvas = tk.Canvas(tl_frame, bg=COLOR_INPUT, highlightthickness=0, height=180)
        self.edit_canvas.pack(side="left", fill="both", expand=True)
        self.edit_canvas.bind("<Button-1>", self._on_timeline_click)
        self.edit_canvas.bind("<MouseWheel>", self._on_edit_wheel)
        # 垂直滚动条
        vs = ttk.Scrollbar(tl_frame, orient="vertical", command=self.edit_canvas.yview)
        self.edit_canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        # 时间刻度
        self.label_edit_status = tk.Label(frm, text="点击「同步轨道」从分镜+视频历史生成时间线；点片段可选中编辑（裁剪/变速/音量/删除）",
                                          font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)
        self.label_edit_status.pack(anchor="w", pady=(2, 0))
        # 数据模型：edit_tracks = [{num, prompt, dialogue, video_url, duration,
        #                           trim_start, speed, volume, enabled, type}]
        self.edit_tracks = []
        self._edit_selected = None  # 选中的轨道索引
        self._edit_tl_x0 = 80       # 时间线左侧标签区宽度
        self._edit_tl_pps = 12.0    # 每像素秒数（缩放）

    def _on_edit_wheel(self, event):
        try:
            self.edit_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _sync_edit_tracks(self):
        """从分镜 + 视频历史生成时间线轨道（分镜 N ↔ 第 N 个视频，台词进字幕）"""
        prompts = list(getattr(self, "storyboard_prompts", []) or [])
        videos = list(getattr(self, "video_history", []) or [])
        _default_dur = 5
        try:
            if hasattr(self, "combo_vid_duration") and getattr(self, "combo_vid_duration", None):
                _default_dur = int(self.combo_vid_duration.get())
        except Exception:
            pass
        tracks = []
        for idx, p in enumerate(prompts):
            url = videos[idx] if idx < len(videos) else ""
            tracks.append({
                "num": p.get("num", idx + 1),
                "prompt": str(p.get("prompt", ""))[:40],
                "dialogue": str(p.get("dialogue", "") or ""),
                "video_url": url,
                "duration": _default_dur,
                "trim_start": 0.0,     # 裁剪起点（秒）
                "speed": 1.0,           # 变速
                "volume": 100,          # 音量 %
                "muted": False,         # 静音（对齐 Cosmius mute）
                "transition": "无",     # 转场类型：无/交叉溶解（对齐 Cosmius transitionIn）
                "enabled": True,        # 轨道启用
                "type": "video",
            })
        self.edit_tracks = tracks
        self._edit_selected = None
        self._render_edit_tracks()
        self.label_edit_status.config(
            text="时间线 %d 条（视频 %d 个；未生成视频的分镜显示「无视频」）—— 点片段选中，右侧可裁剪/变速/音量/删除" % (len(tracks), len(videos)))

    def _render_edit_tracks(self):
        """Canvas 绘制时间线：左侧轨道名 + 右侧片段块（横向）"""
        c = self.edit_canvas
        c.delete("all")
        if not self.edit_tracks:
            c.create_text(10, 20, anchor="w", text="暂无时间线，点击「同步轨道」生成",
                          font=("微软雅黑", 10), fill=COLOR_TEXT_DIM)
            return
        # 轨道高度/行距
        row_h = 34
        x0 = self._edit_tl_x0
        pps = self._edit_tl_pps
        # 时间刻度（顶部）
        total_dur = sum(max(0.5, (t["duration"] / max(0.1, t["speed"]))) if t["enabled"] else 0 for t in self.edit_tracks)
        c.create_text(x0 + 10, 8, anchor="w", text="时间 →", font=("微软雅黑", 8), fill=COLOR_TEXT_DIM)
        for sec in range(0, int(total_dur) + 2, 5):
            px = x0 + sec * pps
            c.create_line(px, 18, px, 24, fill=COLOR_BORDER)
            c.create_text(px + 2, 26, anchor="w", text="%ds" % sec, font=("微软雅黑", 7), fill=COLOR_TEXT_DIM)
        # 轨道
        cursor = 0.0
        for idx, tr in enumerate(self.edit_tracks):
            y = 40 + idx * row_h
            # 轨道标签
            c.create_text(6, y + row_h // 2, anchor="w",
                          text="分镜%s" % tr["num"], font=("微软雅黑", 9, "bold"),
                          fill=COLOR_ACCENT if tr["enabled"] else COLOR_TEXT_DIM)
            c.create_text(6, y + row_h // 2 + 12, anchor="w",
                          text="%ss" % tr["duration"], font=("微软雅黑", 7), fill=COLOR_TEXT_DIM)
            # 轨道分隔线
            c.create_line(x0, y + row_h, x0 + max(200, total_dur * pps), y + row_h, fill=COLOR_BORDER)
            if not tr["enabled"]:
                c.create_text(x0 + 10, y + row_h // 2, anchor="w", text="（已禁用）",
                              font=("微软雅黑", 9), fill=COLOR_TEXT_DIM)
                continue
            # 片段块
            dur_px = max(20, tr["duration"] / max(0.1, tr["speed"]) * pps)
            bx = x0 + cursor * pps
            by = y + 4
            bh = row_h - 8
            fill = "#8B5CF6" if idx == self._edit_selected else "#3B3F6E"
            c.create_rectangle(bx, by, bx + dur_px, by + bh, fill=fill,
                               outline=COLOR_ACCENT if idx == self._edit_selected else COLOR_BORDER,
                               width=2 if idx == self._edit_selected else 1)
            c.create_text(bx + 6, by + 6, anchor="w", text="分镜%s" % tr["num"],
                          font=("微软雅黑", 8, "bold"), fill="#FFFFFF")
            spd = "" if abs(tr["speed"] - 1.0) < 0.01 else " x%.1f" % tr["speed"]
            c.create_text(bx + 6, by + bh - 12, anchor="w",
                          text="%ss%s%s" % (tr["duration"], spd, " 🔇" if tr.get("muted") else ""),
                          font=("微软雅黑", 7), fill="#C9CCE8")
            # 转场标记（对齐 Cosmius：transitionIn 在片段左侧绘制重叠过渡条）
            if tr.get("transition", "无") != "无" and idx > 0:
                trans_w = min(18, dur_px / 2)
                c.create_rectangle(bx - trans_w, by + bh - 6, bx, by + bh,
                                   fill="#F59E0B", outline="")
                c.create_text(bx - trans_w / 2, by + bh - 4, text="⇄",
                              font=("微软雅黑", 6), fill="#1A1A2E")
            cursor += tr["duration"] / max(0.1, tr["speed"])
        # 总时长
        c.create_text(6, 40 + len(self.edit_tracks) * row_h + 10, anchor="w",
                      text="总时长：%.1fs" % total_dur, font=("微软雅黑", 9),
                      fill=COLOR_CREDITS)
        c.configure(scrollregion=(0, 0, x0 + max(300, total_dur * pps), 60 + len(self.edit_tracks) * row_h))

    def _on_timeline_click(self, event):
        """点击时间线：命中片段块则选中（用于属性编辑）"""
        x, y = event.x, event.y
        if not self.edit_tracks:
            return
        row_h = 34
        x0 = self._edit_tl_x0
        pps = self._edit_tl_pps
        # 找点击的行
        row_idx = (y - 40) // row_h
        if not (0 <= row_idx < len(self.edit_tracks)):
            self._edit_selected = None
            self.label_edit_sel.config(text="（未选中）")
            return
        tr = self.edit_tracks[row_idx]
        if not tr["enabled"] or not tr["video_url"]:
            self._edit_selected = None
            self.label_edit_sel.config(text="（未选中）")
            self._render_edit_tracks()
            return
        # 计算该轨道片段 x 范围（累计）
        cursor = 0.0
        for i in range(row_idx):
            t2 = self.edit_tracks[i]
            if t2["enabled"]:
                cursor += t2["duration"] / max(0.1, t2["speed"])
        bx = x0 + cursor * pps
        dur_px = max(20, tr["duration"] / max(0.1, tr["speed"]) * pps)
        if bx <= x <= bx + dur_px:
            self._edit_selected = row_idx
            self.label_edit_sel.config(text="分镜%s（%ss）" % (tr["num"], tr["duration"]))
            self.entry_edit_trim.delete(0, tk.END)
            self.entry_edit_trim.insert(0, "%.1f" % tr["trim_start"])
            self.entry_edit_speed.delete(0, tk.END)
            self.entry_edit_speed.insert(0, "%.1f" % tr["speed"])
            self.entry_edit_vol.delete(0, tk.END)
            self.entry_edit_vol.insert(0, str(tr["volume"]))
            # 静音/转场控件同步
            try:
                self.var_edit_mute.set(bool(tr.get("muted", False)))
                self.combo_edit_trans.set(tr.get("transition", "无"))
            except Exception:
                pass
        else:
            self._edit_selected = None
            self.label_edit_sel.config(text="（未选中）")
        self._render_edit_tracks()

    def _apply_clip_props(self):
        """应用选中片段的 裁剪/变速/音量 属性"""
        if self._edit_selected is None:
            self._show_toast("请先点击时间线选中一个片段", "warning")
            return
        tr = self.edit_tracks[self._edit_selected]
        try:
            trim = float(self.entry_edit_trim.get() or 0)
            speed = float(self.entry_edit_speed.get() or 1)
            vol = int(float(self.entry_edit_vol.get() or 100))
        except ValueError:
            self._show_toast("属性格式错误（裁剪/变速填数字，音量填 0-100）", "warning")
            return
        tr["trim_start"] = max(0.0, trim)
        tr["speed"] = max(0.1, min(4.0, speed))
        tr["volume"] = max(0, min(200, vol))
        # 静音/转场（对齐 Cosmius：mute + transitionIn）
        try:
            tr["muted"] = bool(self.var_edit_mute.get())
            tr["transition"] = self.combo_edit_trans.get() or "无"
        except Exception:
            pass
        self._render_edit_tracks()
        self._show_toast("✅ 已应用：分镜%s（裁剪%.1fs，变速x%.1f，音量%d%%%s%s）" % (
            tr["num"], tr["trim_start"], tr["speed"], tr["volume"],
            "，静音" if tr.get("muted") else "",
            "，转场:" + tr["transition"] if tr.get("transition", "无") != "无" else ""), "success")

    def _duplicate_clip(self):
        """复制选中片段（对齐 Cosmius：duplicate，插到其后）"""
        if self._edit_selected is None:
            self._show_toast("请先点击时间线选中一个片段", "warning")
            return
        src = self.edit_tracks[self._edit_selected]
        dup = dict(src)
        dup["num"] = str(src["num"]) + "′"  # 复制片段标记
        self.edit_tracks.insert(self._edit_selected + 1, dup)
        self._edit_selected = self._edit_selected + 1
        self._render_edit_tracks()
        self._show_toast("📄 已复制分镜%s → 分镜%s" % (src["num"], dup["num"]), "info")

    def _delete_clip(self):
        """删除选中片段"""
        if self._edit_selected is None:
            self._show_toast("请先点击时间线选中一个片段", "warning")
            return
        tr = self.edit_tracks.pop(self._edit_selected)
        self._edit_selected = None
        self.label_edit_sel.config(text="（未选中）")
        self._render_edit_tracks()
        self._show_toast("已删除分镜%s" % tr["num"], "info")

    def _import_srt(self):
        """导入 SRT 字幕：解析时间轴与文本，更新对应分镜台词"""
        path = filedialog.askopenfilename(title="选择 SRT 字幕文件", filetypes=[("SRT 字幕", "*.srt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            import re as _re_srt
            cues = []  # (start_ms, end_ms, text)
            with open(path, "r", encoding="utf-8-sig") as f:
                content = f.read()
            blocks = _re_srt.split(r"\n\s*\n", content.strip())
            for block in blocks:
                lines = [l.strip() for l in block.split("\n") if l.strip()]
                if len(lines) < 2:
                    continue
                time_line = next((l for l in lines if "-->" in l), None)
                if not time_line:
                    continue
                m = _re_srt.match(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})", time_line)
                if not m:
                    continue
                h1, m1, s1, ms1, h2, m2, s2, ms2 = map(int, m.groups())
                start = ((h1 * 3600 + m1 * 60 + s1) * 1000 + ms1)
                end = ((h2 * 3600 + m2 * 60 + s2) * 1000 + ms2)
                text = " ".join(l for l in lines if "-->" not in l and not l.strip().isdigit())
                if text:
                    cues.append((start, end, text))
            if not cues:
                self._show_toast("SRT 中未解析到有效字幕", "warning")
                return
            # 按时间轴匹配到轨道（累计时长）
            if self.edit_tracks:
                t = 0
                for tr in self.edit_tracks:
                    dur_ms = max(1, int(tr["duration"])) * 1000
                    # 找落在该片段时间窗内的第一条字幕
                    hit = next(((c[2]) for c in cues if t <= c[0] < t + dur_ms), None)
                    if hit:
                        tr["dialogue"] = hit
                    t += dur_ms
            self._render_edit_tracks()
            self._show_toast("✅ 已导入 %d 条字幕并匹配到分镜" % len(cues), "success")
        except Exception as e:
            self._show_toast("SRT 解析失败: %s" % e, "warning")

    def _export_fcpxml(self):
        """把轨道导出为 FCP 7 XML（剪映/Pr/达芬奇可导入）：先下载视频到本地目录，再生成 XML"""
        if not self.edit_tracks:
            self._show_toast("轨道为空，请先「同步轨道」", "warning")
            return
        out_dir = filedialog.askdirectory(title="选择导出目录（视频将下载到该目录）")
        if not out_dir:
            return
        fps = int(self.combo_edit_fps.get())
        self.btn_edit_export.config(state=tk.DISABLED)
        self.label_edit_status.config(text="正在下载分镜视频并生成 FCP XML...")
        threading.Thread(target=self._export_fcpxml_worker, args=(out_dir, fps), daemon=True).start()

    def _export_fcpxml_worker(self, out_dir, fps):
        try:
            clips = []
            for i, tr in enumerate(self.edit_tracks):
                if not tr.get("enabled", True):
                    continue  # 禁用的轨道不导出
                local = ""
                if tr["video_url"]:
                    try:
                        r = requests.get(tr["video_url"], timeout=120,
                                         headers={"User-Agent": "Mozilla/5.0"}, **getattr(self, "REQ_KW", {}))
                        r.raise_for_status()
                        local = os.path.join(out_dir, "分镜%02d.mp4" % int(tr["num"]))
                        with open(local, "wb") as f:
                            f.write(r.content)
                    except Exception as e:
                        self.ctx.log("[系统日志] 分镜 %s 视频下载失败: %s\n" % (tr["num"], e))
                clips.append({
                    "num": tr["num"], "local": local,
                    "duration": max(1, int(tr["duration"])),
                    "trim_start": max(0.0, float(tr.get("trim_start", 0) or 0)),
                    "speed": max(0.1, min(4.0, float(tr.get("speed", 1) or 1))),
                    "volume": max(0, min(200, int(tr.get("volume", 100) or 100))),
                    "muted": bool(tr.get("muted", False)),
                    "transition": tr.get("transition", "无"),
                    "dialogue": tr["dialogue"],
                })
            # 生成 FCP 7 XML（xmeml v4）：duration 受 speed 影响（有效时长=原时长/speed），
            # trim_start 记入 in 点（对齐 Cosmius：trimStart/speed 进 XML）；muted→音量 0；
            # transition（交叉溶解）→ transitionitem（对齐 Cosmius transitionIn）
            dur_frames = [int(c["duration"] / c["speed"] * fps) for c in clips]
            total_frames = sum(dur_frames)
            xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                         '<!DOCTYPE xmeml>',
                         '<xmeml version="4">',
                         '  <sequence id="seq-main">',
                         '    <name>wave漫流成片</name>',
                         '    <duration>%d</duration>' % total_frames,
                         '    <rate><timebase>%d</timebase></rate>' % fps,
                         '    <media>',
                         '      <video>',
                         '        <format><samplecharacteristics><rate><timebase>%d</timebase></rate><width>1920</width><height>1080</height></samplecharacteristics></format>' % fps,
                         '        <track>']
            offset = 0
            for i, c in enumerate(clips):
                d = dur_frames[i]
                name = "分镜%02d" % int(c["num"])
                pathurl = ""
                if c["local"]:
                    pathurl = "file://localhost/" + c["local"].replace("\\", "/")
                xml_parts += [
                    '          <clipitem id="clip-%d">' % i,
                    '            <name>%s</name>' % name,
                    '            <duration>%d</duration>' % d,
                    '            <in>%d</in>' % int(c["trim_start"] * fps),
                    '            <out>%d</out>' % (int(c["trim_start"] * fps) + d),
                    '            <start>%d</start>' % offset,
                    '            <end>%d</end>' % (offset + d),
                    '            <rate><timebase>%d</timebase></rate>' % fps,
                    '            <file id="file-%d"><name>%s</name><pathurl>%s</pathurl></file>' % (i, name, pathurl),
                    '          </clipitem>']
                # 转场：当前片段与上一片段之间的 transitionitem（交叉溶解）
                if i > 0 and c["transition"] not in (None, "", "无"):
                    trans_frames = min(int(0.5 * fps), d // 2)  # 0.5s 溶解，不超过片段一半
                    if trans_frames > 0:
                        xml_parts += [
                            '          <transitionitem id="trans-%d">' % i,
                            '            <rate><timebase>%d</timebase></rate>' % fps,
                            '            <start>%d</start>' % (offset - trans_frames),
                            '            <end>%d</end>' % (offset + trans_frames),
                            '            <alignment>center</alignment>',
                            '            <effect><name>Cross Dissolve</name><effectid>Cross Dissolve</effectid></effect>',
                            '            <filter><effect><name>Cross Dissolve</name><effectid>Cross Dissolve</effectid></effect></filter>',
                            '          </transitionitem>']
                offset += d
            xml_parts += ['        </track>', '      </video>',
                          '      <audio><track>']
            # 音频轨（对齐 Cosmius：video + audio 双轨；muted 片段音量=0）
            aoffset = 0
            for i, c in enumerate(clips):
                d = dur_frames[i]
                name = "分镜%02d" % int(c["num"])
                pathurl = ""
                if c["local"]:
                    pathurl = "file://localhost/" + c["local"].replace("\\", "/")
                vol = 0 if c["muted"] else max(0, min(200, c["volume"]))
                xml_parts += [
                    '          <clipitem id="aclip-%d">' % i,
                    '            <name>%s</name>' % name,
                    '            <duration>%d</duration>' % d,
                    '            <in>%d</in>' % int(c["trim_start"] * fps),
                    '            <out>%d</out>' % (int(c["trim_start"] * fps) + d),
                    '            <start>%d</start>' % aoffset,
                    '            <end>%d</end>' % (aoffset + d),
                    '            <rate><timebase>%d</timebase></rate>' % fps,
                    '            <file id="afile-%d"><name>%s</name><pathurl>%s</pathurl></file>' % (i, name, pathurl),
                    '            <volume><level>%.2f</level></volume>' % (vol / 100.0),
                    '          </clipitem>']
                aoffset += d
            xml_parts += ['        </track></audio>',
                          '    </media>',
                          '  </sequence>',
                          '</xmeml>']
            xml_path = os.path.join(out_dir, "wave漫流成片.fcpxml")
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write("\n".join(xml_parts))
            # 提示
            done = sum(1 for c in clips if c["local"])
            self.root.after(0, lambda: self._edit_export_done(
                "✅ FCP XML 导出完成：%s\n已下载 %d/%d 个视频到：%s\n用剪映/Pr 导入该 XML 即成片" % (
                    xml_path, done, len(clips), out_dir)))
        except Exception as e:
            self.root.after(0, lambda: self._edit_export_done("❌ 导出失败: %s" % e))

    def _edit_export_done(self, msg):
        self.btn_edit_export.config(state=tk.NORMAL)
        self.label_edit_status.config(text=msg)
        self._show_toast(msg.split("\n")[0], "success" if "✅" in msg else "warning")

    def _export_srt(self):
        """分镜台词 → SRT 字幕文件（按轨道顺序+时长分配时间）"""
        if not self.edit_tracks:
            self._show_toast("轨道为空，请先「同步轨道」", "warning")
            return
        out_path = filedialog.asksaveasfilename(title="保存字幕文件", defaultextension=".srt",
                                                filetypes=[("SRT 字幕", "*.srt")])
        if not out_path:
            return
        fps = 25  # SRT 用毫秒，与 fps 无关
        lines = []
        idx = 1
        t = 0
        for tr in self.edit_tracks:
            if not tr.get("enabled", True):
                continue  # 禁用的轨道不参与字幕时间轴
            # 有效时长受变速影响（与时间线/XML 一致）
            dur_ms = max(1, int(tr["duration"] / max(0.1, float(tr.get("speed", 1) or 1)))) * 1000
            dialogue = str(tr["dialogue"] or "").strip()
            if dialogue:
                def _fmt(ms):
                    h, rem = divmod(ms, 3600000)
                    m, rem = divmod(rem, 60000)
                    s, ms = divmod(rem, 1000)
                    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)
                lines.append("%d\n%s --> %s\n%s\n" % (idx, _fmt(t), _fmt(t + dur_ms), dialogue))
                idx += 1
            t += dur_ms
        try:
            with open(out_path, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines))
            self._show_toast("✅ SRT 字幕已导出：%s（%d 条）" % (out_path, idx - 1), "success")
        except Exception as e:
            self._show_toast("导出失败: %s" % e, "warning")

    def _import_fcpxml(self):
        """解析 FCP XML（xmeml v4），恢复轨道信息（基础版：读取 clip 列表）"""
        path = filedialog.askopenfilename(title="选择 FCP XML", filetypes=[("FCP XML", "*.xml *.fcpxml"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(path)
            root = tree.getroot()
            clips = []
            for clip in root.iter("clipitem"):
                name_el = clip.find("name")
                dur_el = clip.find("duration")
                name = name_el.text if name_el is not None and name_el.text else "clip"
                dur = dur_el.text if dur_el is not None and dur_el.text else "0"
                clips.append("%s（%s 帧）" % (name, dur))
            if clips:
                self.label_edit_status.config(text="✅ 导入 %d 个片段：%s" % (len(clips), "、".join(clips[:10])))
                self._show_toast("导入 %d 个片段" % len(clips), "success")
            else:
                self.label_edit_status.config(text="未在 XML 中找到 clipitem")
                self._show_toast("未找到片段", "warning")
        except Exception as e:
            self._show_toast("解析失败: %s" % e, "warning")

    # ============================================================
    # 单镜工作台（独立于小说项目，直接提示词 + 参考图 → H3 出片）
    # ============================================================
    def _build_single_shot_tab(self, parent):
        frm = tk.Frame(parent, bg=COLOR_PANEL)
        frm.pack(fill="both", expand=True, padx=12, pady=10)
        tk.Label(frm, text="▼ 单镜工作台（不依赖小说/分镜，直接输入提示词生成单个视频）",
                 font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(anchor="w")
        # 提示词
        tk.Label(frm, text="提示词（支持中英双语，H3 原生中文）：", font=FONT_MAIN,
                 fg=COLOR_TEXT, bg=COLOR_PANEL).pack(anchor="w", pady=(8, 2))
        self.single_prompt = scrolledtext.ScrolledText(frm, font=FONT_MAIN, height=6, wrap=tk.WORD,
                                                       relief="solid", bd=1, bg=COLOR_INPUT,
                                                       fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.single_prompt.pack(fill="x", pady=(2, 6))
        # 参数行
        opt = tk.Frame(frm, bg=COLOR_PANEL)
        opt.pack(fill="x", pady=2)
        tk.Label(opt, text="时长:", font=FONT_MAIN, bg=COLOR_PANEL).pack(side="left")
        self.single_dur = ttk.Combobox(opt, values=tuple(str(i) for i in range(5, 16)), width=5,
                                       state="readonly", font=FONT_MAIN)
        self.single_dur.set("5")
        self.single_dur.pack(side="left", padx=(2, 10))
        tk.Label(opt, text="比例:", font=FONT_MAIN, bg=COLOR_PANEL).pack(side="left")
        self.single_ratio = ttk.Combobox(opt, values=("16:9", "9:16"), width=6,
                                         state="readonly", font=FONT_MAIN)
        self.single_ratio.set("16:9")
        self.single_ratio.pack(side="left", padx=(2, 10))
        tk.Label(opt, text="分辨率:", font=FONT_MAIN, bg=COLOR_PANEL).pack(side="left")
        self.single_res = ttk.Combobox(opt, values=("480p", "720p", "1080p", "2k", "4k", "8k"),
                                       width=6, state="readonly", font=FONT_MAIN)
        self.single_res.set("1080p")
        self.single_res.pack(side="left", padx=(2, 10))
        tk.Label(opt, text="语言:", font=FONT_MAIN, bg=COLOR_PANEL).pack(side="left")
        self.single_lang = ttk.Combobox(opt, values=("自动", "普通话", "粤语", "英语"), width=6,
                                        state="readonly", font=FONT_MAIN)
        self.single_lang.set("自动")
        self.single_lang.pack(side="left", padx=(2, 10))
        # 参考图区
        ref_head = tk.Frame(frm, bg=COLOR_PANEL)
        ref_head.pack(fill="x", pady=(8, 2))
        tk.Label(ref_head, text="参考图（最多 9 张，从图片历史勾选；无参考图=纯文生视频）：",
                 font=FONT_MAIN, fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(side="left")
        self.btn_single_pick_ref = tk.Button(ref_head, text="🖼 选择参考图", font=("微软雅黑", 9),
                                             bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                             command=self._single_shot_pick_refs)
        self.btn_single_pick_ref.pack(side="right")
        bind_hover(self.btn_single_pick_ref, COLOR_BORDER, "#D0D0D0")
        # 2026-08-17 任务3：主界面直接上传本地图片（不必先进选择对话框；≤9 张）
        self.btn_single_upload_main = tk.Button(ref_head, text="📁 上传本地图", font=("微软雅黑", 9),
                                                bg="#28A745", fg="white", relief=tk.FLAT,
                                                command=self._single_shot_upload_local_main)
        self.btn_single_upload_main.pack(side="right", padx=(0, 6))
        bind_hover(self.btn_single_upload_main, "#28A745", "#1F8B38")
        self.btn_single_clear_ref = tk.Button(ref_head, text="清空", font=("微软雅黑", 9),
                                              bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                              command=lambda: self._single_shot_set_refs([]))
        self.btn_single_clear_ref.pack(side="right", padx=(0, 6))
        bind_hover(self.btn_single_clear_ref, COLOR_BORDER, "#D0D0D0")
        # 已选参考图显示
        self.single_ref_frame = tk.Frame(frm, bg=COLOR_PANEL)
        self.single_ref_frame.pack(fill="x", pady=2)
        self.single_ref_label = tk.Label(self.single_ref_frame, text="未选择参考图", font=("微软雅黑", 9),
                                         fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)
        self.single_ref_label.pack(anchor="w")
        # 生成按钮
        self.btn_single_gen = tk.Button(frm, text="🎬 生成视频", font=("微软雅黑", 11),
                                        bg=COLOR_ACCENT, fg="white", relief=tk.FLAT,
                                        command=self._on_single_shot_gen)
        self.btn_single_gen.pack(fill="x", pady=(10, 4), ipady=4)
        bind_hover(self.btn_single_gen, COLOR_ACCENT, COLOR_ACCENT_DARK)
        self.label_single_status = tk.Label(frm, text="就绪", font=FONT_MAIN,
                                            fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)
        self.label_single_status.pack(anchor="w")
        # 初始化参考图状态
        self.single_shot_refs = []
        self.single_shot_busy = False

    def _single_shot_set_refs(self, refs):
        self.single_shot_refs = list(refs or [])
        if not self.single_shot_refs:
            self.single_ref_label.config(text="未选择参考图")
        else:
            self.single_ref_label.config(
                text="已选 %d 张参考图：%s" % (len(self.single_shot_refs),
                                             ", ".join(os.path.basename(u.split("?")[0])[-24:] for u in self.single_shot_refs)))
        self._single_shot_render_ref_thumbs()

    def _single_shot_render_ref_thumbs(self):
        for w in self.single_ref_frame.winfo_children():
            w.destroy()
        refs = self.single_shot_refs
        if not refs:
            self.single_ref_label = tk.Label(self.single_ref_frame, text="未选择参考图", font=("微软雅黑", 9),
                                             fg=COLOR_TEXT_DIM, bg=COLOR_PANEL)
            self.single_ref_label.pack(anchor="w")
            return
        row = tk.Frame(self.single_ref_frame, bg=COLOR_PANEL)
        row.pack(fill="x")
        for i, url in enumerate(refs[:9]):
            thumb = tk.Label(row, text="图%d" % (i + 1), font=("微软雅黑", 8), width=6, height=2,
                             bg=COLOR_INPUT, fg=COLOR_TEXT, relief="solid", bd=1)
            thumb.pack(side="left", padx=2)
            try:
                img = None
                for it in reversed(self.image_history):
                    if it.get("url") == url and it.get("img") is not None:
                        img = it["img"]
                        break
                if img is not None:
                    c = img.copy()
                    c.thumbnail((56, 42))
                    tkimg = ImageTk.PhotoImage(c)
                    thumb.config(image=tkimg, text="", width=56, height=42)
                    thumb._tkimg = tkimg
            except Exception:
                pass

    def _single_shot_pick_refs(self):
        """从图片历史多选参考图 + 支持上传本地图片（合计 ≤9 张）"""
        candidates = [it for it in reversed(self.image_history) if it.get("url")]
        dlg = tk.Toplevel(self.root)
        dlg.title("选择参考图（可多选 / 可上传本地）")
        dlg.geometry("680x480")
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        head = tk.Frame(dlg, bg=COLOR_PANEL)
        head.pack(fill="x", padx=8, pady=6)
        tk.Label(head, text="勾选参考图（最多 9 张）：", font=FONT_MAIN,
                 fg=COLOR_TEXT, bg=COLOR_PANEL).pack(side="left")
        # 上传本地图片按钮
        self._btn_single_upload = tk.Button(head, text="📁 上传本地图片", font=("微软雅黑", 9),
                                            bg="#28A745", fg="white", relief=tk.FLAT,
                                            command=lambda: self._single_shot_upload_local(dlg))
        self._btn_single_upload.pack(side="right")
        bind_hover(self._btn_single_upload, "#28A745", "#1F8B38")
        self._single_pick_status = tk.Label(head, text="", font=("微软雅黑", 8),
                                            fg=COLOR_CREDITS, bg=COLOR_PANEL)
        self._single_pick_status.pack(side="right", padx=(0, 8))
        canvas = tk.Canvas(dlg, bg=COLOR_PANEL, highlightthickness=0)
        vs = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vs.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=4)
        vs.pack(side="right", fill="y", pady=4)
        inner = tk.Frame(canvas, bg=COLOR_PANEL)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        vars_map = {}
        for it in candidates[:60]:
            url = it["url"]
            name = it.get("name", "")
            var = tk.BooleanVar(value=url in self.single_shot_refs)
            vars_map[url] = var
            cell = tk.Frame(inner, bg=COLOR_PANEL)
            cell.pack(fill="x", padx=4, pady=2)
            tk.Checkbutton(cell, variable=var, bg=COLOR_PANEL, fg=COLOR_TEXT,
                           activebackground=COLOR_PANEL).pack(side="left")
            img = it.get("img")
            if img is not None:
                try:
                    c = img.copy()
                    c.thumbnail((80, 60))
                    tkimg = ImageTk.PhotoImage(c)
                    lbl = tk.Label(cell, image=tkimg, bg=COLOR_PANEL)
                    lbl.image = tkimg
                    lbl.pack(side="left", padx=4)
                except Exception:
                    pass
            tk.Label(cell, text=name or os.path.basename(url.split("?")[0]),
                     font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(side="left")
        def _confirm():
            sel = [u for u, v in vars_map.items() if v.get()]
            dlg.destroy()
            self._single_shot_set_refs(sel[:9])
        def _cancel():
            dlg.destroy()
        btns = tk.Frame(dlg, bg=COLOR_PANEL)
        btns.pack(fill="x", padx=8, pady=6)
        tk.Button(btns, text="确定", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white", relief=tk.FLAT,
                  command=_confirm).pack(side="right", padx=(6, 0))
        bind_hover(btns.winfo_children()[-1], COLOR_ACCENT, COLOR_ACCENT_DARK)
        tk.Button(btns, text="取消", font=FONT_MAIN, bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                  command=_cancel).pack(side="right")

    def _single_shot_upload_local_main(self):
        """主界面直接上传本地图片（不打开选择对话框；复用上传逻辑，≤9 张）"""
        self._single_shot_upload_local(None)

    def _single_shot_upload_local(self, dlg):
        """上传本地图片到 ComfyUI，加入参考图候选（累计 ≤9 张）。
        dlg 为 None 时（主界面直接上传）用主界面状态标签显示结果。"""
        def _status(txt):
            try:
                if dlg is not None:
                    self._single_pick_status.config(text=txt)
                else:
                    self.label_single_status.config(text=txt)
            except Exception:
                pass
        paths = filedialog.askopenfilenames(title="选择本地图片（可多选）", filetypes=[
            ('图片文件', '*.png *.jpg *.jpeg *.webp'), ('所有文件', '*.*')])
        if not paths:
            return
        try:
            cfg = self._get_api_config()
            base = (cfg.get('media_base_url') or '').strip().rstrip('/')
            if not base:
                _status("❌ 未配置 ComfyUI 地址")
                return
            added = 0
            for path in paths[:9]:
                try:
                    img = Image.open(path)
                    img.load()
                    img = img.convert('RGB')
                except Exception as e:
                    _status("❌ 读取失败: %s" % os.path.basename(path))
                    continue
                # 上传到 ComfyUI
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                buf.seek(0)
                fname = 'single_%d.png' % int(time.time() * 1000)
                files = {'image': (fname, buf, 'image/png')}
                try:
                    r = requests.post(base + '/upload/image', files=files,
                                      data={'overwrite': 'true'}, timeout=60, verify=False)
                    if r.status_code != 200:
                        _status("❌ 上传失败 HTTP %d" % r.status_code)
                        continue
                    up_name = (r.json() or {}).get('name') or fname
                    url = base + '/view?filename=' + up_name.replace(' ', '%20') + '&type=input'
                    # 加入 image_history（这样它出现在候选列表并可被 video_skill 下载）
                    self.image_history.append({'url': url, 'img': img, 'name': os.path.basename(path)})
                    # 自动加入已选参考图（不超过 9 张）
                    if url not in self.single_shot_refs and len(self.single_shot_refs) < 9:
                        self.single_shot_refs.append(url)
                    added += 1
                except Exception as e:
                    _status("❌ 上传异常: %s" % e)
            _status("✅ 已上传 %d 张（当前已选 %d/9）" % (added, len(self.single_shot_refs)))
            # 刷新主界面已选显示 + 缩略图
            self._single_shot_set_refs(self.single_shot_refs)
            # 刷新对话框列表（对话框打开时重建）
            if dlg is not None:
                self._single_shot_refresh_pick_dlg(dlg)
        except Exception as e:
            _status("❌ %s" % e)

    def _single_shot_refresh_pick_dlg(self, dlg):
        """重新打开参考图选择（上传后刷新候选列表）"""
        dlg.destroy()
        self._single_shot_pick_refs()
        # 更新主界面已选显示
        self._single_shot_set_refs(self.single_shot_refs)

    def _on_single_shot_gen(self):
        """单镜工作台：独立生成一个视频（不依赖项目分镜）"""
        if getattr(self, "single_shot_busy", False):
            self._show_toast("正在生成中，请稍候", "info")
            return
        prompt = self.single_prompt.get("1.0", tk.END).strip()
        if not prompt:
            self._show_toast("请输入提示词", "warning")
            return
        cfg = self._get_api_config()
        if not (cfg.get("media_base_url") or "").strip():
            self._show_toast("请先在配置中填写 ComfyUI 地址", "warning")
            return
        dur = int(self.single_dur.get())
        ratio = self.single_ratio.get()
        res = self.single_res.get()
        lang = self.single_lang.get()
        refs = list(getattr(self, "single_shot_refs", []))
        self.single_shot_busy = True
        self.btn_single_gen.config(state=tk.DISABLED)
        self.label_single_status.config(text="生成中...（H3 出片约 1-5 分钟）")
        self.ctx.log("\n[系统日志] 单镜工作台开始生成视频（时长 %ds，%s，%s，参考图 %d 张）...\n" % (dur, ratio, res, len(refs)))
        threading.Thread(target=self._single_shot_worker,
                         args=(prompt, cfg, dur, ratio, res, refs, lang),
                         daemon=True).start()

    def _single_shot_worker(self, prompt, cfg, dur, ratio, res, refs, lang):
        """后台线程：提示词加执行要求前缀 → agent.generate_video → 等待完成"""
        try:
            base = self._story_batch_done
            _local_refs = []
            try:
                for _u in (refs or []):
                    _lp = ''
                    for _it in self.image_history:
                        if _it.get('url') == _u and _it.get('local_path') and os.path.exists(_it.get('local_path', '')):
                            _lp = _it.get('local_path')
                            break
                    _local_refs.append(_lp)
            except Exception:
                pass
            self.agent.generate_video(prompt, cfg, dur, ratio, res, list(refs), local_refs=_local_refs)
            deadline = time.time() + 2400
            while time.time() < deadline and self._story_batch_done == base:
                if getattr(self.ctx, "stop_flag", False):
                    break
                time.sleep(1)
            ok = self._story_batch_done > base
            self.root.after(0, lambda ok=ok: self._single_shot_finish(ok))
        except Exception as e:
            self.ctx.log("\n[系统日志] 单镜工作台生成异常: %s\n" % e)
            self.root.after(0, lambda: self._single_shot_finish(False, str(e)))

    def _single_shot_finish(self, ok, err=""):
        self.single_shot_busy = False
        self.btn_single_gen.config(state=tk.NORMAL)
        if ok:
            self.label_single_status.config(text="✅ 生成成功！可在下方视频历史中播放/下载")
            self._show_toast("单镜视频生成成功！", "success")
        else:
            self.label_single_status.config(text="❌ 生成失败" + (": " + err if err else ""))
            self._show_toast("生成失败" + (": " + err if err else ""), "warning")

    # ---- 图片 tab ----
    def _build_image_tab(self, parent):
        frm = tk.Frame(parent, bg=COLOR_PANEL)
        frm.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Label(frm, text="提示词 (支持中英双语):", font=FONT_MAIN, fg=COLOR_TEXT, bg=COLOR_PANEL).pack(anchor="w")
        self.entry_img_prompt = scrolledtext.ScrolledText(frm, font=FONT_MAIN, height=4, wrap=tk.WORD,
                                                          relief="solid", bd=1, bg=COLOR_INPUT,
                                                          fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        self.entry_img_prompt.pack(fill="x", pady=(4, 6))
        opt = tk.Frame(frm, bg=COLOR_PANEL)
        opt.pack(fill="x", pady=2)
        tk.Label(opt, text="比例:", font=FONT_MAIN, bg=COLOR_PANEL).pack(side="left")
        self.combo_img_ratio = ttk.Combobox(opt, values=("16:9", "9:16"), width=8,
                                            font=FONT_MAIN, state="readonly")
        self.combo_img_ratio.set("16:9")
        self.combo_img_ratio.pack(side="left", padx=(4, 14))
        self.combo_img_ratio.bind("<<ComboboxSelected>>", lambda e: self._update_image_credits())
        tk.Label(opt, text="分辨率:", font=FONT_MAIN, bg=COLOR_PANEL).pack(side="left")
        self.combo_img_res = ttk.Combobox(opt, values=("1k", "2k", "4k", "8k"), width=8,
                                          font=FONT_MAIN, state="readonly")
        self.combo_img_res.set("1k")
        self.combo_img_res.pack(side="left", padx=(4, 14))
        self.combo_img_res.bind("<<ComboboxSelected>>", lambda e: self._update_image_credits())
        self.label_img_credits = tk.Label(opt, text="预计消耗: 4 积分", font=FONT_MAIN, fg=COLOR_CREDITS,
                                          bg=COLOR_PANEL)
        self.label_img_credits.pack(side="left")
        btn_row = tk.Frame(frm, bg=COLOR_PANEL)
        btn_row.pack(fill="x", pady=(8, 4))
        self.btn_extract_prompt = tk.Button(btn_row, text="提取提示词", font=FONT_MAIN, bg=COLOR_PANEL,
                                            fg=COLOR_TEXT_DIM, relief="solid", bd=1,
                                            highlightbackground="#D0D0D0", command=self._extract_latest_prompt)
        self.btn_extract_prompt.pack(side="left", padx=(0, 8))
        self.btn_gen_img = tk.Button(btn_row, text="生成单张图片", font=FONT_MAIN, bg=COLOR_ACCENT, fg="white",
                                     relief="flat", command=self._on_gen_single_image_click)
        self.btn_gen_img.pack(side="left", padx=(0, 8))
        bind_hover(self.btn_gen_img, COLOR_ACCENT, COLOR_ACCENT_DARK)
        self.btn_gen_images_batch = tk.Button(btn_row, text="🚀 一键并发生成所有资产", font=FONT_MAIN,
                                              bg="#28A745", fg="white", relief="flat",
                                              command=self._on_gen_images_batch_click)
        self.btn_gen_images_batch.pack(side="left")
        bind_hover(self.btn_gen_images_batch, "#28A745", "#1F8B38")
        # 跨章节资产复用开关：勾选=跳过已生成过的同名资产（默认不勾选=全部生成，2026-08-09 全资产生成要求）；取消=强制全部重新生成
        self._var_skip_existing = tk.BooleanVar(value=False)
        tk.Checkbutton(btn_row, text="跳过已生成", font=("微软雅黑", 8), bg=COLOR_PANEL,
                       fg=COLOR_TEXT_DIM, activebackground=COLOR_PANEL,
                       variable=self._var_skip_existing).pack(side="left", padx=(8, 0))
        # 音色匹配区（生成完资产图后，为每个角色上传专属音色；生成视频时对应人物自动使用）
        self._build_voice_area(frm)
        hist_head = tk.Frame(frm, bg=COLOR_PANEL)
        hist_head.pack(anchor="w", fill="x", pady=(8, 2))
        tk.Label(hist_head, text="▼ 图片历史记录 (单击选中/取消，双击放大预览)", font=("微软雅黑", 9),
                 fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(side="left")
        # 2026-08-15 需求1：上传本地图片到历史记录（供视频参考图使用）
        self.btn_upload_hist = tk.Button(hist_head, text="📤 上传图片", font=("微软雅黑", 9),
                                         bg="#6C8EBF", fg="white", relief="flat",
                                         command=self._upload_history_image)
        self.btn_upload_hist.pack(side="right", padx=(0, 6))
        bind_hover(self.btn_upload_hist, "#6C8EBF", "#5578A8")
        self.btn_del_hist = tk.Button(hist_head, text="🗑 删除选中图片", font=("微软雅黑", 9),
                                      bg=COLOR_DANGER, fg="white", relief="flat",
                                      command=self._delete_selected_images)
        self.btn_del_hist.pack(side="right")
        bind_hover(self.btn_del_hist, COLOR_DANGER, "#D92B21")
        hist = tk.Frame(frm, bg=COLOR_PANEL)
        hist.pack(fill="both", expand=True)
        self.history_canvas = tk.Canvas(hist, bg=COLOR_PANEL, highlightthickness=0)
        vs = ttk.Scrollbar(hist, orient="vertical", command=self.history_canvas.yview)
        self.history_canvas.configure(yscrollcommand=vs.set)
        self.history_canvas.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.history_frame_inner = tk.Frame(self.history_canvas, bg=COLOR_PANEL)
        self._win_hist = self.history_canvas.create_window((0, 0), window=self.history_frame_inner, anchor="nw")
        self.history_frame_inner.bind("<Configure>", lambda e: self.history_canvas.configure(scrollregion=self.history_canvas.bbox("all")))
        self.history_canvas.bind("<Configure>", lambda e: self.history_canvas.itemconfig(self._win_hist, width=e.width))
        self.history_canvas.bind("<MouseWheel>", self._on_hist_wheel)
        self.image_history_images = []

    def _on_hist_wheel(self, event):
        self.history_canvas.yview_scroll(int(-event.delta / 120), "units")

    # ---- 音色匹配区（图片生成下方）：生成完资产图后为每个角色上传专属音色 ----
    def _build_voice_area(self, parent):
        voice_head = tk.Frame(parent, bg=COLOR_PANEL)
        voice_head.pack(anchor="w", fill="x", pady=(8, 2))
        tk.Label(voice_head, text="▼ 音色匹配 (人物资产 · 为每个角色上传专属音色，生成视频时自动使用)",
                 font=("微软雅黑", 9), fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(side="left")
        self.btn_refresh_voice = tk.Button(voice_head, text="🔄 刷新", font=("微软雅黑", 8),
                                           bg=COLOR_PANEL, fg=COLOR_TEXT_DIM, relief="solid", bd=1,
                                           highlightbackground="#D0D0D0",
                                           command=self._rebuild_voice_area)
        self.btn_refresh_voice.pack(side="right")
        vf = tk.Frame(parent, bg=COLOR_PANEL)
        vf.pack(fill="x", pady=2)
        self.voice_canvas = tk.Canvas(vf, bg=COLOR_PANEL, highlightthickness=0, height=170)
        vvs = ttk.Scrollbar(vf, orient="vertical", command=self.voice_canvas.yview)
        self.voice_canvas.configure(yscrollcommand=vvs.set)
        self.voice_canvas.pack(side="left", fill="both", expand=True)
        vvs.pack(side="right", fill="y")
        self.voice_inner = tk.Frame(self.voice_canvas, bg=COLOR_PANEL)
        self._win_voice = self.voice_canvas.create_window((0, 0), window=self.voice_inner, anchor="nw")
        self.voice_inner.bind("<Configure>",
                              lambda e: self.voice_canvas.configure(scrollregion=self.voice_canvas.bbox("all")))
        self.voice_canvas.bind("<Configure>",
                               lambda e: self.voice_canvas.itemconfig(self._win_voice, width=e.width))
        self.voice_canvas.bind("<MouseWheel>", self._on_voice_wheel)
        self._voice_photo_refs = {}
        self._rebuild_voice_area()

    def _on_voice_wheel(self, event):
        try:
            self.voice_canvas.yview_scroll(int(-event.delta / 120), "units")
        except Exception:
            pass

    def _rebuild_voice_area(self):
        """重建音色匹配区：列出全部人物资产缩略图 + 🎵 音色按钮（生成视频时按分镜人物自动用）"""
        try:
            if not hasattr(self, 'voice_inner'):
                return
            for w in self.voice_inner.winfo_children():
                w.destroy()
            self._voice_photo_refs = {}
            # 收集人物资产（image_history 里 type=character，且名字不含道具特征词）
            chars = []
            seen = set()
            for it in self.image_history:
                if it.get('type') != 'character':
                    continue
                nm = str(it.get('name') or '')
                if not nm:
                    continue
                core = self._asset_core_name(nm)
                if not core or core in seen:
                    continue
                # 道具特征词过滤（防"手机人形"类误判成人物）
                if any(_w in core for _w in ('手机', '耳环', '雨伞', '高跟鞋', '戒指', '项链', '手链',
                                              '手表', '眼镜', '背包', '钱包', '钥匙', '捧花', '花束',
                                              '酒杯', '茶杯', '咖啡', '相机', '镜子', '口红', '香水',
                                              '文件', '信封', '红包', '礼物', '道具', '鞋', '包',
                                              '伞', '瓶', '杯', '戒')):
                    continue
                seen.add(core)
                chars.append((core, it))
            if not chars:
                tk.Label(self.voice_inner,
                         text='（暂无人物资产图。\n生成完资产图后，这里会列出每个角色，可为每个角色上传专属音色，\n生成视频时对应人物自动使用该音色。）',
                         font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL,
                         justify="left").pack(anchor="w", pady=8, padx=10)
                self.voice_canvas.configure(scrollregion=self.voice_canvas.bbox("all"))
                return
            # 按行平铺（每行 5 个）
            row_frame = None
            for i, (core, it) in enumerate(chars):
                if i % 5 == 0:
                    row_frame = tk.Frame(self.voice_inner, bg=COLOR_PANEL)
                    row_frame.pack(fill="x", padx=6, pady=2)
                cell = tk.Frame(row_frame, bg=COLOR_PANEL)
                cell.grid(row=0, column=i % 5, padx=4, pady=2)
                self._render_voice_cell(cell, core, it)
            self.voice_canvas.configure(scrollregion=self.voice_canvas.bbox("all"))
        except Exception:
            pass

    def _render_voice_cell(self, cell, core, item):
        """渲染一个人物音色单元格：缩略图 + 名称 + 🎵 音色按钮/✕ 清除"""
        try:
            ph = None
            img = item.get('img')
            if img is not None:
                try:
                    t = img.copy()
                    t.thumbnail((64, 64), Image.LANCZOS)
                    ph = ImageTk.PhotoImage(t)
                    self._voice_photo_refs[core] = ph
                except Exception:
                    ph = None
            cv = tk.Canvas(cell, width=68, height=68, bg=COLOR_PANEL,
                           highlightthickness=1, highlightbackground=COLOR_BORDER)
            cv.pack(side="top")
            if ph:
                cv.create_image(34, 30, image=ph)
            else:
                cv.create_text(34, 30, text="无图", fill=COLOR_TEXT_DIM, font=("微软雅黑", 8))
            cv.create_text(34, 64, text=core[:8], fill=COLOR_TEXT_DIM, font=("微软雅黑", 7), anchor="s")
            vrow = tk.Frame(cell, bg=COLOR_PANEL)
            vrow.pack(side="top", pady=(2, 0))
            _vpath = (self.asset_voices or {}).get(core, '')
            if _vpath and os.path.exists(_vpath):
                tk.Label(vrow, text='🎵 ' + os.path.basename(_vpath)[:8], font=("微软雅黑", 7),
                         fg=COLOR_SUCCESS, bg=COLOR_PANEL).pack(side="left")
                tk.Button(vrow, text="✕", font=("微软雅黑", 7), bg=COLOR_PANEL,
                          fg=COLOR_DANGER, relief="flat", padx=2,
                          command=lambda c=core: self._clear_asset_voice(c)).pack(side="left")
            else:
                tk.Button(vrow, text="🎵 音色", font=("微软雅黑", 7), bg=COLOR_PANEL,
                          fg=COLOR_ACCENT, relief="solid", bd=1, highlightbackground=COLOR_BORDER,
                          padx=4, command=lambda c=core: self._upload_asset_voice(c)).pack(side="left")
        except Exception:
            pass

    # ---- 视频 tab ----
    def _build_video_tab(self, parent):
        # 垂直分栏：上=分镜分区列表(每个分镜：左参考图缩略图 + 右提示词)+参数+按钮；下=视频历史记录
        paned_vid_right = tk.PanedWindow(parent, orient=tk.VERTICAL, sashwidth=8,
                                         sashrelief=tk.RAISED, bg=COLOR_INPUT)
        paned_vid_right.pack(fill="both", expand=True)

        # 上：视频提示词（分镜列表）+ 参数 + 生成按钮
        frame_vid_top = tk.Frame(paned_vid_right, bg=COLOR_INPUT)
        paned_vid_right.add(frame_vid_top)
        # ---- 视频提示词 = 分镜列表（自动同步自分镜资产，每个分镜前有选择框，可编辑）----
        sb_head = tk.Frame(frame_vid_top, bg=COLOR_INPUT)
        sb_head.pack(fill="x", pady=(5, 2))
        tk.Label(sb_head, text="▼ 视频提示词（分镜 · 自动同步自分镜资产 · 可编辑 · 勾选后生成视频）",
                 font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(side="left")
        # 2026-08-15 需求：全选/取消全选按钮（一键勾选或取消所有分镜复选框）
        self.btn_sb_select_all = tk.Button(sb_head, text="☑ 全选", font=("微软雅黑", 8),
                                           bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                           command=lambda: self._set_sb_all_checked(True))
        self.btn_sb_select_all.pack(side="right", padx=(0, 6))
        bind_hover(self.btn_sb_select_all, COLOR_BORDER, "#D0D0D0")
        self.btn_sb_unselect_all = tk.Button(sb_head, text="□ 取消全选", font=("微软雅黑", 8),
                                             bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                             command=lambda: self._set_sb_all_checked(False))
        self.btn_sb_unselect_all.pack(side="right")
        bind_hover(self.btn_sb_unselect_all, COLOR_BORDER, "#D0D0D0")
        btn_sync_sb = tk.Button(sb_head, text="🔄 重新同步", font=("微软雅黑", 8), bg=COLOR_BORDER,
                                fg=COLOR_TEXT, relief=tk.FLAT, command=self._sync_storyboard_all)
        btn_sync_sb.pack(side="right")
        bind_hover(btn_sync_sb, COLOR_BORDER, "#D0D0D0")
        sb_frame = tk.Frame(frame_vid_top, bg=COLOR_INPUT)
        sb_frame.pack(fill="x", pady=2)
        self.sb_canvas = tk.Canvas(sb_frame, bg=COLOR_PANEL, highlightthickness=0, height=200)
        sb_vs = ttk.Scrollbar(sb_frame, orient="vertical", command=self.sb_canvas.yview)
        self.sb_canvas.configure(yscrollcommand=sb_vs.set)
        self.sb_canvas.pack(side="left", fill="both", expand=True)
        sb_vs.pack(side="right", fill="y")
        self.sb_inner = tk.Frame(self.sb_canvas, bg=COLOR_PANEL)
        self._win_sb = self.sb_canvas.create_window((0, 0), window=self.sb_inner, anchor="nw")
        self.sb_inner.bind("<Configure>",
                           lambda e: self.sb_canvas.configure(scrollregion=self.sb_canvas.bbox("all")))
        self.sb_canvas.bind("<Configure>",
                            lambda e: self.sb_canvas.itemconfig(self._win_sb, width=e.width))
        self.sb_canvas.bind("<MouseWheel>", self._on_sb_wheel)
        sb_btns = tk.Frame(frame_vid_top, bg=COLOR_INPUT)
        sb_btns.pack(fill="x", pady=4)
        self.btn_gen_vid = tk.Button(sb_btns, text="🎬 生成选中分镜视频", font=("微软雅黑", 9),
                                     bg=COLOR_ACCENT, fg="white", relief=tk.FLAT,
                                     command=self._on_gen_selected_sb_videos)
        self.btn_gen_vid.pack(side="left", expand=True, fill="x", padx=(0, 3), ipady=3)
        bind_hover(self.btn_gen_vid, COLOR_ACCENT, COLOR_ACCENT_DARK)
        self.btn_gen_sb_all = tk.Button(sb_btns, text="🚀 生成全部分镜视频", font=("微软雅黑", 9),
                                        bg="#28A745", fg="white", relief=tk.FLAT,
                                        command=self._on_gen_all_sb_videos)
        self.btn_gen_sb_all.pack(side="left", expand=True, fill="x", padx=(3, 0), ipady=3)
        bind_hover(self.btn_gen_sb_all, "#28A745", "#1F8B38")

        frame_vid_settings = tk.Frame(frame_vid_top, bg=COLOR_INPUT)
        frame_vid_settings.pack(fill="x", pady=5)
        tk.Label(frame_vid_settings, text="时长:", font=FONT_MAIN, fg=COLOR_TEXT_DIM,
                 bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
        self.combo_vid_duration = ttk.Combobox(frame_vid_settings,
                                              values=tuple(str(i) for i in range(5, 16)), width=6,
                                              state="readonly", font=FONT_MAIN)
        self.combo_vid_duration.set("5")
        self.combo_vid_duration.pack(side=tk.LEFT, padx=5)
        self.combo_vid_duration.bind("<<ComboboxSelected>>", lambda e: self._update_video_credits())
        tk.Label(frame_vid_settings, text="比例:", font=FONT_MAIN, fg=COLOR_TEXT_DIM,
                 bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
        self.combo_vid_ratio = ttk.Combobox(frame_vid_settings, values=("16:9", "9:16"), width=8,
                                            state="readonly", font=FONT_MAIN)
        self.combo_vid_ratio.set("16:9")
        self.combo_vid_ratio.pack(side=tk.LEFT, padx=5)
        self.combo_vid_ratio.bind("<<ComboboxSelected>>", lambda e: self._update_video_credits())
        tk.Label(frame_vid_settings, text="分辨率:", font=FONT_MAIN, fg=COLOR_TEXT_DIM,
                 bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
        self.combo_vid_res = ttk.Combobox(frame_vid_settings,
                                          values=("480p", "720p", "1080p", "2k", "4k", "8k"),
                                          width=8, state="readonly", font=FONT_MAIN)
        self.combo_vid_res.set("1080p")
        self.combo_vid_res.pack(side=tk.LEFT, padx=5)
        self.combo_vid_res.bind("<<ComboboxSelected>>", lambda e: self._update_video_credits())
        # 风格已移到小说文本旁（全局风格，图片+视频+提示词统一生效）；此处显示当前全局风格只读标签
        tk.Label(frame_vid_settings, text="风格:", font=FONT_MAIN, fg=COLOR_TEXT_DIM,
                 bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
        self.label_vid_style = tk.Label(frame_vid_settings,
                                        text=DEFAULT_VIDEO_STYLE, font=FONT_MAIN,
                                        fg=COLOR_ACCENT, bg=COLOR_INPUT)
        self.label_vid_style.pack(side=tk.LEFT, padx=5)
        # 台词语言：生成视频时人物说话语言（自动=跟随分镜台词原文）
        tk.Label(frame_vid_settings, text="语言:", font=FONT_MAIN, fg=COLOR_TEXT_DIM,
                 bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
        self.combo_vid_lang = ttk.Combobox(frame_vid_settings,
                                           values=tuple(DIALECT_LANGS.keys()), width=7,
                                           state="readonly", font=FONT_MAIN)
        # 2026-08-16 锁死中文：默认且唯一选项=中文（普通话）
        self.combo_vid_lang.set("中文（普通话）")
        self.combo_vid_lang.pack(side=tk.LEFT, padx=5)
        # 章节选择：只生成选定章节的分镜视频（全部章节=不限）
        tk.Label(frame_vid_settings, text="章节:", font=FONT_MAIN, fg=COLOR_TEXT_DIM,
                 bg=COLOR_INPUT).pack(side=tk.LEFT, padx=2)
        self.combo_vid_chapter = ttk.Combobox(frame_vid_settings,
                                              values=("全部章节",), width=10,
                                              state="readonly", font=FONT_MAIN)
        self.combo_vid_chapter.set("全部章节")
        self.combo_vid_chapter.pack(side=tk.LEFT, padx=5)
        self.label_vid_credits = tk.Label(frame_vid_settings, text="预计消耗: 24 积分", font=FONT_MAIN,
                                          fg=COLOR_CREDITS, bg=COLOR_INPUT)
        self.label_vid_credits.pack(side=tk.LEFT, padx=15)
        # 2026-08-21 隐藏状态行：下拉菜单行下方的"分镜视频生成进度"区域占面积，用户要求隐藏。
        # （进度改由视频历史列表顶部的跑马灯行显示；label 保留创建但不再 pack——config 调用仍安全）
        self.label_vid_status = tk.Label(frame_vid_top, text="等待生成...", font=FONT_MAIN,
                                         fg=COLOR_TEXT_DIM, bg=COLOR_INPUT)
        # self.label_vid_status.pack(anchor="w", pady=2)

        # 下：视频历史记录展示区
        frame_vid_history = tk.Frame(paned_vid_right, bg=COLOR_INPUT)
        paned_vid_right.add(frame_vid_history)
        tk.Label(frame_vid_history, text="▼ 视频历史记录 (可拖拽上方边界调整大小)", font=FONT_MAIN,
                 fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w", pady=5)
        hist = tk.Frame(frame_vid_history, bg=COLOR_INPUT)
        hist.pack(fill="both", expand=True)
        self.history_vid_canvas = tk.Canvas(hist, bg=COLOR_PANEL, highlightthickness=0)
        vs = ttk.Scrollbar(hist, orient="vertical", command=self.history_vid_canvas.yview)
        self.history_vid_canvas.configure(yscrollcommand=vs.set)
        self.history_vid_canvas.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.frame_vid_history_inner = tk.Frame(self.history_vid_canvas, bg=COLOR_PANEL)
        self._win_vid_hist = self.history_vid_canvas.create_window((0, 0), window=self.frame_vid_history_inner, anchor="nw")
        self.frame_vid_history_inner.bind("<Configure>", lambda e: self.history_vid_canvas.configure(scrollregion=self.history_vid_canvas.bbox("all")))
        self.history_vid_canvas.bind("<Configure>", lambda e: self.history_vid_canvas.itemconfig(self._win_vid_hist, width=e.width))
        self.history_vid_canvas.bind("<MouseWheel>", self._on_vid_hist_wheel)
        self.video_history_videos = []
        # 初始化积分显示
        self._update_video_credits()

    def _update_video_credits(self):
        try:
            duration = int(self.combo_vid_duration.get())
        except Exception:
            duration = 5
        res = self.combo_vid_res.get()
        ratio = self.combo_vid_ratio.get()
        base_per_sec = 5
        res_mult = {'480p': 1, '720p': 2, '1080p': 4, '2k': 8, '4k': 16, '8k': 32}.get(res, 4)
        ratio_mult = {'16:9': 1.2, '9:16': 1.0}.get(ratio, 1.0)
        credits = int(base_per_sec * duration * res_mult * ratio_mult)
        self.label_vid_credits.config(text="预计消耗: %d 积分" % credits)

    def _update_image_credits(self):
        res = self.combo_img_res.get()
        ratio = self.combo_img_ratio.get()
        base = 4
        res_mult = {'1k': 1, '2k': 2, '4k': 4, '8k': 8}.get(res, 1)
        ratio_mult = {'16:9': 1.2, '9:16': 1.0}.get(ratio, 1.0)
        credits = int(base * res_mult * ratio_mult)
        self.label_img_credits.config(text="预计消耗: %d 积分" % credits)

    def _on_vid_hist_wheel(self, event):
        self.history_vid_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _on_sb_wheel(self, event):
        self.sb_canvas.yview_scroll(int(-event.delta / 120), "units")

    # ============ 分镜提示词 ============
    # 渲染技术字段中可拼入提示词的自然现象词（写实风格下挑出；渲染器术语/特效词忽略）
    RENDER_NATURE_WORDS = (
        '体积光', '体积雾', '光线追踪', '光晕', '丁达尔', '散射', '次表面', 'SSS',
        '雾气', '薄雾', '晨雾', '雾气弥漫', '尘埃', '粒子', '飘雪', '雨丝', '雨滴',
        '水花', '浪花', '火焰', '火花', '烟尘', '硝烟', '蒸汽', '水雾', '萤火',
        '光束', '光柱', '夕阳余晖', '月光', '星光', '霓虹光', '灯光', '烛光',
        '反光', '折射', '透光', '逆光', '轮廓光', '背光', '闪光', '辉光', '斑驳光影',
    )

    # 机位+视角标准化词库（用户提供：AI视频生成专用，适配 MiniMax H3 等）。
    # 每项: (关键词组, 标准句式, 说明)
    CAMERA_VIEW_LIB = [
        # 一、基础平视系列
        (('独白', '证件', '念信', '宣读', '正式宣布'),
         '固定机位，正面平视视角，人物直面镜头',
         '单人独白/证件式镜头；少用于双人对话'),
        (('对话', '交谈', '聊天', '聊天', '讨论', '商议', '商量', '对峙', '争吵', '拌嘴', '谈话', '问话'),
         '固定机位，3/4斜侧平视视角，中近景',
         '绝大多数对话/剧情叙事首选；AI五官最稳定，减少崩坏'),
        (('过肩', '正反打', '对手戏'),
         '固定机位，过肩平视视角（透过角色A肩膀拍对面角色B）',
         '双人对话冲突/聊天对手戏；H3识别好'),
        (('行走', '走路', '赶路', '漫步', '奔跑', '跑', '巡逻', '背影', '剪影'),
         '固定机位，纯侧面平视视角',
         '行走动作/剪影/对峙镜头；只见半边轮廓'),
        # 二、高低角度
        (('登场', '降临', '威压', '霸气', '强者', '君临', '俯视众生', 'boss', '反派登场'),
         '低位机位，仰视角（相机低于人物腰部向上拍）',
         '放大气场/强势/威严；强者登场、对峙、霸气台词'),
        (('晕倒', '昏倒', '受委屈', '被困', '被关', '囚禁', '跪倒', '跪地', '崩溃', '绝望', '无力'),
         '高位机位，俯视角（相机高于头顶向下拍）',
         '凸显无助/弱势/压抑；晕倒、受委屈、被困'),
        (('病床', '病房', '卧病', '医院', '输液', '照顾病人'),
         '齐胸高位机位，微俯平视',
         '轻微俯视不压迫；病房/室内近景'),
        # 三、空间框架/窥视
        (('敲门', '门外', '偷看', '窥视', '门缝', '开门', '推门'),
         '门外固定机位，门框框架视角（门框作前景遮挡向内拍）',
         '门外敲门/偷看屋内剧情'),
        (('窗边', '窗前', '窗外', '独处', '眺望', '看窗外', '发呆'),
         '窗边机位，窗框框架视角（窗框形成天然画框）',
         '室内安静抒情/独处镜头'),
        # 四、移动跟拍
        (('搀扶', '扶', '陪同', '同行', '并肩', '护送'),
         '侧面移动机位，跟随平视视角（相机与人物同步横向移动，轻微防抖）',
         '人物赶路/行走/搀扶同行'),
        (('进入', '踏入', '走进', '步入', '潜入', '探险', '进入陌生'),
         '后方跟拍机位，背部平视视角（跟随在人物身后拍后背）',
         '赶路/进入陌生场景，营造代入感'),
        # 五、特殊创意
        (('大场景', '全景交代', '城市全景', '战场全貌', '俯瞰', '环境交代', '航拍', '天际线'),
         '高空机位，鸟瞰俯视视角（高空大全景）',
         '大场景环境交代；少用于人物特写'),
        (('打斗', '搏斗', '战斗', '格斗', '撞击', '冲击', '摔倒', '翻滚'),
         '地面低位机位，贴地仰视视角（相机贴近地面向上拍）',
         '打斗/冲击感强的画面'),
    ]
    # 视角匹配避坑：大幅切换的机位组合（避免相邻镜头穿帮，前端不处理则仅作提示）
    VIEW_TRANSITION_RULES = ('相邻镜头视角尽量接近，不要斜侧镜头突然切鸟瞰/第一人称，大幅切换会严重穿帮')

    def _select_camera_guide(self, body, prev_camera=''):
        """按分镜文本智能选取机位+视角（用户提供的标准化词库）。
        优先：用户分镜里明确写了机位/视角 → 直接采用其描述；
        否则按场景/动作关键词从词库匹配；都不匹配回退 3/4斜侧平视（首选）。
        返回 (机位视角句, 是否匹配到)。"""
        import re as _re
        text = body or ''
        # 1. 分镜文本里已含机位/视角描述（如"固定机位""主观视角""鸟瞰"）→ 直接采用
        #    （用户自己写的比词库更准）
        explicit = ('固定机位', '移动机位', '低位机位', '高位机位', '门外固定机位',
                    '窗边机位', '高空机位', '地面低位机位', '侧面移动机位',
                    '后方跟拍机位', '主观视角', '第一人称', 'POV', '过肩', '鸟瞰',
                    '贴地', '仰视', '俯视', '平视', '微俯')
        found = [e for e in explicit if e in text]
        if found:
            # 提取包含该机位词的那一行作为句（去行首字段名如"运镜设计：/角度："）
            for line in text.split('\n'):
                if any(f in line for f in found) and ('机位' in line or '视角' in line or '镜头' in line):
                    _c = line.strip().lstrip('- ').strip()
                    _c = _re.sub(r'^(运镜设计|角度|机位|景别|构图|焦段)[：:]\s*', '', _c)
                    if _c and len(_c) <= 60:
                        return _c, True
            return '、'.join(found), True
        # 2. 关键词匹配词库
        for keys, sentence, _desc in self.CAMERA_VIEW_LIB:
            if any(k in text for k in keys):
                return sentence, True
        # 3. 回退：3/4斜侧平视（首选，五官最稳定）
        return '固定机位，3/4斜侧平视视角，中近景', False

    def _detect_viewpoint_guide(self, body):
        """检测分镜的镜头视角类型，生成明确的视角指令（2026-08-08 用户反馈：
        "旁观镜头盯着手机发呆的主角 + 第一人称拍手机屏幕"，实际生成成了"把手机屏幕对着观众"——
        根因是提示词没表达"镜头视角主体"。H3 默认按旁观视角理解，把物品怼向镜头展示）。

        主观视角关键词命中 → 第一人称 POV 指令；
        否则 → 旁观视角指令（含"物品不要朝向镜头"约束）。
        """
        import re as _re
        text = body or ''
        pov_keys = ('主观视角', '第一人称', 'POV', 'pov', '模拟.*视野', '模拟.*视角',
                    '角色视角', '眼睛所见', '所见画面', '透过.*看', '第一视角', '主角视角')
        for k in pov_keys:
            if _re.search(k, text):
                return ('镜头视角：主观视角（第一人称POV）——画面等于角色眼睛所见，观众看到的就是角色正在看的内容；'
                        '若角色低头看手机，画面呈现手机屏幕内容（屏幕界面），而不是角色本人的脸，'
                        '手机保持角色手中自然朝向，不要举向镜头展示')
        return ('镜头视角：旁观视角（第三人称）——镜头位于角色之外观察角色本人及其动作表情；'
                '角色手中的物品（如手机）保持自然持握朝向，不要将物品举向/朝向镜头展示给观众，'
                '观众看的是角色本人的状态')

    def _extract_director_guide(self, body, style_name='', ethnicity='中国'):
        """从分镜规划文本提取导演控制信息（景别/运镜/构图/画面内容/景深/光影/音效/自然渲染词/情绪微表情），
        生成补充指令拼到视频提示词末尾（H3 原生支持多语言）。

        2026-08-08 扩展（用户要求）：
        - 画面内容：全量提取（之前截 120 字）
        - 景深层次：全量提取（新增）
        - 渲染技术：不整段拼；只在写实风格下挑出自然现象词（体积光/体积雾/光线追踪等）拼入
        - 过滤污染：字幕文字、剪辑过渡句（"向下一镜过渡/黑场/全剧终/承接上镜"等）不拼入
        - 镜头视角：主观视角(POV) vs 旁观视角——视角指令最优先拼入（防"把物品怼镜头"）
        - 情绪微表情：提取分镜【情绪微表情】字段（用户需求：让模型准确识别苦笑/冷笑等）
        - 语言跟随国别：中国 → 导演控制输出中文；海外 → 输出英文（H3 提示词语言与人物地域一致）
        """
        try:
            import re as _re
            # 国别 → 语言：中国=中文指令，海外=英文指令
            _is_cn = (str(ethnicity or '').strip() != '海外')
            parts_out = []
            lines = body.split('\n')

            def _field_val(ls, k):
                """提取 'k：值' 或 '- k：值' 的值；返回 (值, 是否匹配)"""
                for pre in ('- ', ''):
                    for sep in ('：', ':'):
                        if ls.startswith(pre + k + sep):
                            return ls.split(sep, 1)[-1].strip(), True
                return '', False

            def _clean_pollution(s):
                """过滤剪辑指导/字幕污染：黑场、过渡、全剧终、承接上镜、字幕文字等。
                2026-08-08 新增：过滤微表情/心理描写（模型生成视频时无法呈现，影响效果）——
                保留肢体动作/姿态（攥拳/低头/转身），剔除面部微表情（苦笑/眼神/嘴角/眼泪/皱眉等）。
                2026-08-17 新增：剔除混入画面内容/人声字段的"台词：..."段
                （导演控制里残留台词 → H3 念出台词之外的话，分镜一实证）。"""
                # 2026-08-17：先剔除"台词：..."段（删到第一个句号/行尾，兼容引号）
                s = _re.sub(r'台词\s*[:：][^。！？\n]*[。！？]?', '', s)
                s = _re.sub(r'向下一镜过渡[^；。]*?。?', '', s)
                s = _re.sub(r'承接上镜[^；。]*?。?', '', s)
                s = _re.sub(r'画面渐暗至黑场[^；。]*?。?', '', s)
                s = _re.sub(r'(全剧终|剧终|结束镜头|片尾)', '', s)
                s = _re.sub(r'【字幕】[^。；]*', '', s)
                s = _re.sub(r'字幕[^。；，]*[，。]?', '', s)
                s = _re.sub(r'向下一镜[^；。]*', '', s)
                # 微表情/心理描写过滤（非特写镜头不呈现；删除含微表情词的短句片段）
                s = _re.sub(r'[，,；;]\s*(嘴角|眼神|眼眶|眉头|眉梢|瞳孔|泪光|泪珠|泪水|泪痕|神情|表情|脸色|面色|笑容|苦笑|冷笑|微笑|抿唇|咬唇|颤抖的唇|鼻翼)[^，,；;。]{0,12}', '', s)
                s = _re.sub(r'(嘴角|眼神|眼眶|眉头|眉梢|瞳孔|泪光|泪水|神情|表情|笑容|苦笑|冷笑|抿唇|咬唇)[^，,；;。]{0,15}[，,；;。]?', '', s)
                s = _re.sub(r'(心里|内心|心想|暗暗|默默|似乎|仿佛|好像|觉得|感到|意识到|回忆起|想起)[^，,；;。]{0,18}[，,；;。]?', '', s)
                # 2026-08-15 用户要求：禁背景人声+人物情绪描述——"人声与音效"字段里的
                # 人物人声及情绪描述（"小明人声（惊喜上扬，童声清脆）"）会诱导 H3 生成
                # 台词之外的多余人声/语气词，整段删除"XX人声..."直到环境音/动作音效关键词
                # （环境音/音效/脚步/风声/鸟鸣/碗碟/静默等）之前的内容，只保留环境音/动作音效。
                # 2026-08-15 补充：**环境人声**（"环境人声（远处窃窃私语）"）是提示词明确
                # 要求的环境人声，保留不删（用户要求：提示词写了环境人声才允许生成）。
                # 实现：先把"环境人声"替换为占位符保护 → 删除人物人声 → 恢复占位符。
                # 2026-08-17 修复（分镜一多念一句根因之二）：旧正则只删"XX人声（…）"，
                # 不含"人声"二字的人声描述（"人物说话声/嘀咕声/低声议论/起哄声/笑声"等）
                # 会残留 → 诱导 H3 生成多余语音。扩展删除所有"XX声（…）"人声类描述。
                _ENV_VOICE_PH = '\x01ENVV\x02'
                # 2026-08-17 修复（用户问"现场氛围怎么办"）：整段保护"环境人声（…）"——
                # 只保护关键词时，括号内"低声议论/窃窃私语/嘈杂"等词会被后续人声删除正则误删；
                # 若整段直接替换成固定占位符，恢复时只回"环境人声"四字、括号描述永久丢失。
                # 用回调把原文存入字典，恢复时原样还原——围观人群氛围（路径B）完整可用。
                _env_keep = {}
                def _ph_env(m):
                    _k = '\x01ENVK%d\x02' % len(_env_keep)
                    _env_keep[_k] = m.group(0)
                    return _k
                s = _re.sub(r'环境人声\s*[（(][^）)]*[）)]', _ph_env, s)
                s = s.replace('环境人声', _ENV_VOICE_PH)
                # 删除"XX人声（描述）"——含"人声"的最常见形式（*? 允许分句开头无人声前缀）
                s = _re.sub(r'[^，,；;。\s]*?人声（[^）]*）', '', s)
                # 2026-08-17 扩展：删除"XX说话声/嘀咕声/低语声/议论声/起哄声/笑声/喊声/叫声/哭声/叹气声（描述）"
                # 及不含括号的同款（说话声/嘀咕声/低语/议论/起哄/叫喊/呼喊/惊呼/哼声）
                _human_voice = ('说话声', '嘀咕声', '低语声', '议论声', '起哄声', '笑声', '喊声',
                                '叫声', '哭声', '叹气声', '惊呼声', '说话', '嘀咕', '低语',
                                '议论', '起哄', '叫喊', '呼喊', '惊呼', '嘟囔', '喃喃自语',
                                '自言自语', '对话声', '交谈声', '吆喝声', '叫卖声', '吆喝', '叫卖',
                                '嘈杂声', '喧哗声', '人声')
                _voice_alt = '|'.join(_human_voice)
                s = _re.sub(r'[^，,；;。\s]*?(?:%s)（[^）]*）' % _voice_alt, '', s)
                s = _re.sub(r'[^，,；;。\s]*?(?:%s)[^，,；;。]*' % _voice_alt, '', s)
                _m_rs = _re.search(r'[^，,；;。\s]*?(?:人声|说话声|嘀咕|低语|议论|起哄|叫喊|呼喊|惊呼|嘟囔|自言自语|对话声|交谈声)[^，,；;。]*', s)
                if _m_rs:
                    _env_keys = ('环境音', '音效', '脚步', '风声', '鸟鸣', '碗碟', '静默', '碰撞', '吱呀', '动作音')
                    _rest = s[_m_rs.end():]
                    _env_idx = min([_rest.find(k) for k in _env_keys if _rest.find(k) >= 0] or [-1])
                    if _env_idx >= 0:
                        s = _rest[_env_idx:]
                    else:
                        s = _rest.lstrip('，,；;。')
                s = s.replace(_ENV_VOICE_PH, '环境人声')
                # 还原"环境人声（描述）"整段原文（回调保存的内容）
                for _k, _v in _env_keep.items():
                    s = s.replace(_k, _v)
                # 清理过滤后留下的孤立标点残渣（如 "：，。"）
                s = _re.sub(r'[：:，,；;。]{2,}', '，', s)
                s = _re.sub(r'^[，,；;。:：\s]+', '', s)
                s = _re.sub(r'[，,；;。:：\s]+$', '', s)
                return s.strip()

            # 0. 镜头视角指令（最优先：机位+视角词库智能匹配 + 主观POV检测）
            try:
                _cam, _matched = self._select_camera_guide(body)
                # 若分镜文本含主观视角关键词 → POV 指令优先（防"物品怼镜头"）
                import re as _re2
                _pov = any(_re2.search(k, body or '') for k in
                           ('主观视角', '第一人称', 'POV', 'pov', '模拟.*视野', '模拟.*视角',
                            '角色视角', '眼睛所见', '所见画面', '透过.*看', '第一视角', '主角视角'))
                if _pov:
                    parts_out.append('镜头视角：主观视角（第一人称POV）——画面等于角色眼睛所见，观众看到的就是角色正在看的内容；若角色低头看手机，画面呈现手机屏幕内容（屏幕界面），而不是角色本人的脸，手机保持角色手中自然朝向，不要举向镜头展示'
                                     if _is_cn else
                                     'Camera view: first-person POV — the frame equals what the character sees; if the character looks down at a phone, show the phone screen content, not their face; keep the phone held naturally, do not raise it toward the camera')
                else:
                    _vb = ('镜头视角：%s。' % _cam) if _cam else ''
                    parts_out.append(_vb + '物品（如手机）保持自然持握朝向，不要将物品举向/朝向镜头展示给观众，观众看的是角色本人的状态'
                                     if _is_cn else
                                     ('Camera view: %s. Keep objects (e.g. phone) held naturally, do not raise them toward the camera; the audience watches the character, not the object.' % _cam))
            except Exception:
                pass

            # 分镜信息字段（单行：场景/角色/站位/景别/角度/焦段/构图/运镜设计）
            # 2026-08-08 用户要求：情绪微表情不进视频提示词（模型生成视频时做不到微表情，
            # 除非脸部特写）——从导演控制提取中移除"情绪微表情"；仅当分镜景别含"特写"时才额外提取
            # 2026-08-08 用户要求：加"站位"字段（解决人物左右互换/无全局观）
            # 2026-08-09 全英文改造：字段标签翻译成英文（用户要求导演控制全英文）
            _EN_KEYS = {'场景': 'Scene', '角色': 'Characters', '站位': 'Positions',
                        '道具位置': 'Prop position', '景别': 'Shot size', '角度': 'Camera angle',
                        '焦段': 'Focal length',
                        '构图': 'Composition', '运镜设计': 'Camera movement',
                        '情绪微表情': 'Emotion', '画面内容': 'Scene content',
                        '景深层次': 'Depth of field', '光影与色调': 'Lighting & color',
                        '人声与音效': 'Sound', '渲染氛围': 'Atmosphere'}
            info_keys = ('场景', '角色', '站位', '道具位置', '景别', '角度', '焦段', '构图', '运镜设计')
            _is_closeup = ('特写' in body or '大特写' in body)
            for line in lines:
                ls = line.strip()
                for k in info_keys:
                    val, ok = _field_val(ls, k)
                    if ok:
                        # 过滤"无/无人物（环境交代镜）/无角色/无场景"等占位
                        _v = val.strip()
                        if (_v and _v != '无'
                                and not _v.startswith('无人物') and not _v.startswith('无角色')
                                and not _v.startswith('无场景')):
                            _val_clean = _clean_pollution(val)
                            if _is_cn:
                                parts_out.append('%s：%s' % (k, _val_clean))
                            else:
                                # 英文：标签英文 + 值做术语映射（景别/角度/焦段/构图常见词）
                                parts_out.append('%s: %s' % (_EN_KEYS.get(k, k), self._dir_value_en(k, _val_clean)))
                        break
            # 情绪微表情：仅当本镜为脸部特写/大特写时才提取（模型视频无法呈现非特写的微表情）
            if _is_closeup:
                for line in lines:
                    ls = line.strip()
                    _val, _ok = _field_val(ls, '情绪微表情')
                    if _ok and _val.strip() and _val.strip() != '无':
                        _val_clean = _clean_pollution(_val)
                        if _is_cn:
                            parts_out.append('情绪微表情：%s' % _val_clean)
                        else:
                            parts_out.append('Emotion: %s' % self._dir_value_en('情绪微表情', _val_clean))
                        break
            # 画面与视听细节：画面内容 + 景深层次 + 光影与色调 + 人声与音效（全量提取，过滤污染）
            detail_keys = ('画面内容', '景深层次', '光影与色调', '人声与音效')
            for i, line in enumerate(lines):
                ls = line.strip()
                for k in detail_keys:
                    val, ok = _field_val(ls, k)
                    if ok:
                        # 多行值：合并后续行直到空行或下一个字段
                        j = i + 1
                        while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith(('- ', k)):
                            nxt = lines[j].strip()
                            if nxt.startswith(('【', '=====', '景深层次', '渲染技术', '画面内容', '光影与色调', '人声与音效')):
                                break
                            val += nxt
                            j += 1
                        val = _clean_pollution(val)
                        if val:
                            if _is_cn:
                                parts_out.append('%s：%s' % (k, val))
                            else:
                                parts_out.append('%s: %s' % (_EN_KEYS.get(k, k), self._dir_value_en(k, val)))
                        break
            # 渲染技术：只在写实风格下挑自然现象词（不整段拼）
            try:
                _style = VIDEO_STYLE_PRESETS.get(str(style_name or '').strip()) or {}
                _zh = _style.get('zh', '') or ''
                _is_realistic = ('写实' in _zh) or ('真实' in _zh and '卡通' not in _zh)
                if _is_realistic:
                    for line in lines:
                        ls = line.strip()
                        val, ok = _field_val(ls, '渲染技术')
                        if ok:
                            found = [w for w in self.RENDER_NATURE_WORDS if w in val]
                            if found:
                                parts_out.append('渲染氛围：%s' % '、'.join(found) if _is_cn
                                                 else 'Atmosphere: %s' % ', '.join(found))
                            break
            except Exception:
                pass
            if not parts_out:
                return ''
            if _is_cn:
                return '\n【导演控制】' + '；'.join(parts_out) + '（严格按以上景别/运镜/构图/画面/景深/光影/情绪/音效执行）'
            return '\n[Director control] ' + '; '.join(parts_out) + ' (strictly follow the above shot size/camera/composition/scene/depth/lighting/emotion/sound)'
        except Exception:
            return ''

    def _dir_value_en(self, key, val):
        """导演控制英文化：把中文术语值映射为英文。
        策略（2026-08-09 修正）：标签全英文由调用处处理；本方法只处理**整段可术语化**的字段
        （景别/角度/焦段/构图），用整词替换避免半吊子残留；叙述性字段（场景/角色/站位/画面内容/
        景深/光影/人声）保留中文原文——这些是给 H3 的导演意图描述，非语音内容不会被念出来，
        且 Qwen3VL 原生懂中文，硬翻反而失真。"""
        import re as _re
        try:
            v = str(val or '').strip()
            if not v:
                return v
            if key == '景别':
                _m = {'大特写': 'Extreme close-up', '特写': 'Close-up', '近景': 'Medium close-up',
                      '中景': 'Medium shot', '全景': 'Full shot', '远景': 'Long shot'}
                for zh, en in _m.items():
                    if v == zh or v.startswith(zh):
                        return v.replace(zh, en, 1)
            elif key == '角度':
                _m = {'平视': 'Eye level', '仰视': 'Low angle', '俯视': 'High angle',
                      '荷兰角': 'Dutch angle', '鸟瞰': 'Bird\'s-eye view', '主观视角': 'POV'}
                for zh, en in _m.items():
                    if v == zh or v.startswith(zh):
                        return v.replace(zh, en, 1)
            elif key == '焦段':
                _m = {'广角': 'Wide angle', '标准': 'Standard', '长焦': 'Telephoto',
                      '微距': 'Macro', '鱼眼': 'Fisheye'}
                for zh, en in _m.items():
                    if v == zh or v.startswith(zh):
                        v = v.replace(zh, en, 1)
                        # 中文括号转英文（Telephoto（85mm）→ Telephoto (85mm)）
                        v = v.replace('（', ' (').replace('）', ')')
                        return v
            elif key == '构图':
                _m = {'三分法': 'Rule of thirds', '三分法则': 'Rule of thirds',
                      '居中构图': 'Centered composition', '居中': 'Centered',
                      '对称构图': 'Symmetrical composition', '对称': 'Symmetrical',
                      '框架构图': 'Frame composition', '引导线构图': 'Leading lines composition',
                      '引导线': 'Leading lines'}
                for zh, en in _m.items():
                    if v == zh or v.startswith(zh):
                        return v.replace(zh, en, 1)
            # 其他字段（场景/角色/站位/运镜/画面内容等）：保留中文原文
            return v
        except Exception:
            return str(val or '')

    def _extract_dialogue(self, body):
        """从分镜文本提取"说话人+动作+台词"完整句（2026-08-09 台词内嵌改造）。

        用户要求：台词必须绑定说话人+对象+动作，格式如"路名看着王菲说：\"我喜欢你\""，
        没有对象时人物自言自语。不要孤立的纯台词段（H3 会猜错说话人导致台词乱飘）。

        处理分镜格式：
          - 台词：\n（OS）苏晴（低声）：十年感情，连当面分手的勇气都没有吗？
          - 台词：苏晴：你回来了。
          - 台词：\n路名（看着王菲）：我喜欢你。
          - 【字幕】"内容"
        返回 list[dict]，每个 dict = {'speaker','action','line','full'}：
          - speaker: 说话人（去掉 OS/动作括号后的名字；无名字时 ''）
          - action:  动作/对象（从 台词行内括号 或 画面内容字段 语义提取；无则 ''）
          - line:    纯台词原文（去引号/去动作括号/去人物名前缀）
          - full:    最终内嵌句："路名看着王菲说：\"我喜欢你\"" / "苏晴说：\"你回来了\"" / "旁白：xxx"
        """
        import re as _re
        text = body or ''
        sentences = []
        # 1. 台词：字段（多行，到下一个字段/分镜结束）——前瞻排除 ** 开头的标题行（**【画面与视听细节】**）
        # 2026-08-17 修复（分镜一多念一句根因之三）：旧前瞻 `\n景深|\n光影|\n画面内容` 不识别
        # LLM 输出的 `- 景深层次：`（带 - 前缀）→ 台词段把后续字段行全吞进台词 → H3 念出
        # "景深层次（自言自语）：前后景虚化" 这类听不懂的话。前瞻改为兼容 `- ` 前缀。
        m = _re.search(r'台词[：:]\s*\n?(.*?)(?=\n\s*\*+【|\n\s*【|\n\s*=====|\n\s*(?:-\s*)?(?:景深|光影|画面内容|人声|渲染|情绪|气氛|字幕|运镜|构图|站位|角色|场景|道具|统一视觉|电影画质|镜头光晕|画面极具|画质技术)|\Z)', text, re.S)
        if m:
            raw = m.group(1)
            for line in raw.split('\n'):
                ls = line.strip()
                if not ls or ls.startswith(('【', '=====')):
                    continue
                # 2026-08-16 OS转台词兜底：行首带（OS）/(OS) 的内心独白一律丢弃，
                # 不转为台词也不发H3（防止旧项目残留OS被念成画外音）
                if _re.match(r'^\s*[（(]\s*OS\s*[）)]', ls):
                    continue
                # 2026-08-16 OS转台词兜底：旁白：开头的行（无说话人）一律丢弃，
                # 必须在形式0（完整句）检查之前拦截，否则被当完整台词保留
                if _re.match(r'^旁白\s*[：:]', ls):
                    continue
                # 提取说话人（行首 人物名： 或 （OS）人物名（动作）：）
                speaker = ''
                action = ''
                # 形式0：行内已是完整句（路名看着王菲："我喜欢你" 或 带"说"字旧格式）→ 整行保留
                # 判断：行内含引号台词 + 冒号/说在引号前（避免把普通描述行当台词）
                if (_re.search(r'[\"“].+?[\"”]', ls) and _re.search(r'[：:]\s*[\"“]', ls)) or ('说：' in ls or '说:' in ls):
                    # 2026-08-17 修复（分镜一多念一句根因之四）：LLM 常把台词写为
                    # "台词：路名（看着苏晴）：\"我喜欢你\"。远处灯光闪烁。"——引号闭合后
                    # 还跟着画面描述尾巴，若整行保留，H3 会把"远处灯光闪烁"也念出来。
                    # 只保留「人物前缀：\"台词\"」部分，丢弃引号后的尾巴。
                    _qm0 = _re.search(r'(.*?[：:])\s*[“"]([^“”"]*)[”"]', ls)
                    if _qm0:
                        _pre0 = _qm0.group(1).strip()
                        _core0 = _qm0.group(2).strip()
                        # 去掉"台词：/对话："标记前缀（台词字段行首标记）
                        _pre0 = _re.sub(r'^(台词|对话)\s*[：:]\s*', '', _pre0)
                        # 防止双冒号：前缀已以冒号结尾（路名（看着苏晴）：）则只补左引号
                        if _pre0.endswith('：') or _pre0.endswith(':'):
                            _ls2 = _pre0 + '“' + _core0 + '”'
                        else:
                            _ls2 = _pre0 + '：“' + _core0 + '”'
                    else:
                        # 无引号完整句（旧格式 路名说：你回来了）→ 规范化引号兜底
                        _ls2 = ls.replace('"', '“').replace('"', '”')
                    # 仅当整句首尾都被引号包住（如 "路名看着王菲：\"我喜欢你\""）才去最外层；
                    # 普通台词行（林晚：\"xxx\"）首字符是名字不是引号，绝不剥尾引号
                    if len(_ls2) >= 2 and _ls2[0] in '“"' and _ls2[-1] in '”"':
                        _ls2 = _ls2[1:-1]
                    sentences.append({'speaker': '', 'action': '', 'line': _ls2, 'full': _ls2})
                    continue
                # 先抓行内动作括号（说话人后面的（动作））
                # 形式1：苏晴（低声）：xxx → speaker=苏晴 action=低声
                _m2 = _re.match(r'^(?:[（(]\s*OS\s*[）)]\s*)?([^（(：:]{1,12})\s*[（(]([^）)]{1,20})[）)]\s*[：:]\s*(.*)$', ls)
                if _m2:
                    speaker, action, rest = _m2.group(1).strip(), _m2.group(2).strip(), _m2.group(3).strip()
                else:
                    # 形式2：苏晴：xxx 或 （OS）苏晴：xxx
                    _m3 = _re.match(r'^(?:[（(]\s*OS\s*[）)]\s*)?([^：:]{1,12})[：:]\s*(.*)$', ls)
                    if _m3:
                        speaker, rest = _m3.group(1).strip(), _m3.group(2).strip()
                    else:
                        speaker, rest = '', ls
                # 台词原文（去引号——原台词可能自带 “” 或 \"\"）
                # 2026-08-17 修复：rest 可能带引号后尾巴（苏晴：\"你回来了\"。远处灯光闪烁）——
                # 只取引号内台词，丢弃引号后画面描述，避免 H3 把尾巴念出来
                _qm1 = _re.search(r'[“"]([^“”"]*)[”"]', rest)
                if _qm1:
                    line_txt = _qm1.group(1).strip()
                else:
                    line_txt = rest.replace('“', '').replace('”', '').replace('"', '').replace('"', '').strip()
                line_txt = _re.sub(r'[（(][^）)]*[）)]', '', line_txt).strip()
                # 过滤"无"/"无。"等无台词占位
                if not line_txt or len(line_txt) < 2 or line_txt in ('无', '无。', '无！', '无？', '（无）', '(无)'):
                    continue
                sentences.append({'speaker': speaker, 'action': action, 'line': line_txt, 'full': ''})
        # 2. 【字幕】字段：2026-08-16 OS转台词——字幕/旁白类一律丢弃，不转台词不发H3
        #    （原逻辑会提取为无说话人句子→生成"旁白：xxx"发给H3→画外音根源）
        if not sentences:
            return ''
        # 3. 从画面内容/动作字段提取"动作/对象"（语义融合：画面里写"路名看向王菲/望向她"）
        #    若台词行内已有动作（低声等语气词）保留；否则从画面内容抓看向/望着/看着对象
        _scene = ''
        _m_scene = _re.search(r'画面内容[：:]\s*(.*?)(?=\n\s*【|\n\s*=====|\Z)', text, re.S)
        if _m_scene:
            _scene = _m_scene.group(1)
        # 3.5 从【站位】字段提取每个说话人的画面位置（2026-08-09 对话说话人绑定）：
        #    H3 音画联合生成需知道"这句台词是谁张嘴说的"，中文名标签（林晚/她/我）无法绑定到画面，
        #    画面位置（左侧/右侧/中央/前景/背景）是最可靠的视觉锚点——
        #    组装成 "林晚（画面左侧座椅）：'台词'"，H3 即可确定画面中对应位置的人说话。
        _pos_map = {}
        _pos_txt = ''
        _m_pos = _re.search(r'站位[：:]\s*\n?(.*?)(?=\n\s*【|\n\s*=====|$)', text, re.S)
        if _m_pos:
            _pos_txt = _m_pos.group(1)
            for s in sentences:
                _sp = s['speaker']
                if not _sp:
                    continue
                # 匹配 "林晚在画面左侧座椅上" → 位置短语 "画面左侧座椅上"（去掉名字前缀，避免冗余）
                _mp = _re.search(_re.escape(_sp) + r'[^。；]{0,8}?(?:在|位于|站在|坐于|处于)?([^。；]{0,6}?画面(?:左|右|中|中央|前景|背景|角落)[^，。；]{0,12})', _pos_txt)
                if _mp:
                    _pos_map[_sp] = _mp.group(1).strip()
        for s in sentences:
            sp = s['speaker']
            act = s['action']
            # 语气动作词（低声/大喊/冷笑等）保留为动作
            if act and act not in ('低声', '轻声', '喃喃', '自言自语'):
                s['action'] = act
            # 无对象/动作时：从画面内容抓"看向/望着/盯着/面对 X"
            if not s['action'] and _scene and sp:
                _mo = _re.search(sp + r'[^。；]{0,18}?(看向|望着|盯着|看着|望向|面对|注视|凝视|转身面对|抬头看|低头看)[^。；]{1,12}?', _scene)
                if _mo:
                    s['action'] = _mo.group(0).replace(sp, '').strip()
        # 4. 组装完整句（2026-08-09 去"说"字：H3 会把"说"字念出来，改为冒号直接引出台词）
        for s in sentences:
            sp, act, line = s['speaker'], s['action'], s['line']
            if s.get('full'):
                # 形式0：已是完整句，去掉"说"字（路名看着王菲说："xxx" → 路名看着王菲："xxx"）
                s['full'] = _re.sub(r'说\s*[：:](?=\s*["“])', '：', s['full'])
                # 2026-08-09 形式0 补位置绑定：整行完整句（如 林晚："xxx"）若站位字段有
                # 该说话人的画面位置，则插为 林晚（画面左侧座椅）："xxx"——H3 音画绑定需要
                _m0 = _re.match(r'^([^：:]{1,12})[：:]', s['full'])
                if _m0:
                    _sp0 = _re.sub(r'[（(][^）)]*[）)]', '', _m0.group(1)).strip()
                    if _sp0:
                        _mp = _re.search(_re.escape(_sp0) + r'[^。；]{0,8}?(?:在|位于|站在|坐于|处于)?([^。；]{0,6}?画面(?:左|右|中|中央|前景|背景|角落)[^，。；]{0,12})', _pos_txt)
                        if _mp and _mp.group(1).strip() and _mp.group(1).strip() not in s['full']:
                            s['full'] = s['full'].replace(_sp0 + '：', _sp0 + '（%s）：' % _mp.group(1).strip(), 1)
                continue
            if sp:
                _pos = _pos_map.get(sp, '')
                if act:
                    # 动作若含"看向X"则：路名看着王菲："xxx"；否则：路名（画面左侧，低声）："xxx"
                    if any(k in act for k in ('看向', '望着', '盯着', '看着', '望向', '面对', '注视', '凝视')):
                        full = '%s%s："%s"' % (sp, act, line)
                    else:
                        # 位置 + 语气动作合并：林晚（画面左侧座椅，低声）："xxx"
                        _act_parts = []
                        if _pos:
                            _act_parts.append(_pos)
                        if act:
                            _act_parts.append(act)
                        full = '%s（%s）："%s"' % (sp, '，'.join(_act_parts), line)
                else:
                    if _pos:
                        # 无动作但有位置：林晚（画面左侧座椅）："xxx"
                        full = '%s（%s）："%s"' % (sp, _pos, line)
                    else:
                        # 无动作无位置无对象 → 自言自语
                        full = '%s（自言自语）："%s"' % (sp, line)
            else:
                # 2026-08-16 OS转台词：无说话人（字幕/OS/裸行）一律丢弃，不再生成旁白
                continue
            s['full'] = full
        # 返回：完整句列表（多句用 分号 连接，保留引号）
        return '；'.join(s['full'] for s in sentences if s['full'])

    def _dialogue_en(self, dialogue):
        """把中文台词完整句翻译为英文（2026-08-09 台词内嵌：英文版写英文台词）。

        输入是 _extract_dialogue 输出的完整句（"路名看着王菲说：\"我喜欢你\"" / "旁白：\"xxx\""），
        保持同样结构，只翻译台词原文并转英文引号：
          "Luming looks at Wangfei and says: \"I love you\"" / "Narrator: \"xxx\""
        不翻译（返回空串）：空 / 无引号 / 含中文动作词但无法拆分。失败返回 ''（调用处回退）。
        """
        import re as _re
        try:
            if not dialogue or not str(dialogue).strip():
                return ''
            out = []
            # 按分号拆多句
            for _seg in str(dialogue).split('；'):
                _seg = _seg.strip()
                if not _seg:
                    continue
                # 2026-08-16 OS转台词：旁白已在上游 _extract_dialogue 丢弃，
                # 此处不再翻译旁白（原 Narrator 分支已删除，防画外音复活）
                _m = _re.search(r'^(.+?)[：:]\s*["“](.+?)["”]\s*$', _seg)
                if _m:
                    _pre = _m.group(1).strip()  # "路名看着王菲" 或 "苏晴（低声）"
                    _line = _m.group(2)
                    # 去（低声）→ 保留语气词
                    _pre_clean = _re.sub(r'[（(]([^）)]{1,20})[）)]', r' \1 ', _pre).strip()
                    out.append('%s: "%s"' % (_pre_clean, _line))
                else:
                    # 没有引号结构（可能纯台词）——不强行翻译，跳过
                    continue
            return '；'.join(out)
        except Exception:
            return ''

    def _dialogue_quote_text(self, dialogue):
        """从台词完整句中提取引号内的纯台词原文（供时长自适应/字数统计用）。
        "路名看着王菲说：\"我喜欢你\"" → "我喜欢你"；旁白："xxx" → xxx。无引号返回原串。"""
        import re as _re
        try:
            _parts = []
            for _seg in str(dialogue or '').split('；'):
                _m = _re.search(r'["“](.+?)["”]', _seg)
                if _m:
                    _parts.append(_m.group(1))
                else:
                    _parts.append(_seg.strip())
            return ''.join(_parts)
        except Exception:
            return str(dialogue or '')

    def _auto_duration_for_dialogue(self, dialogue, user_dur):
        """台词-时长自适应：按 3.5 字/秒正常语速计算台词所需时长，
        超过用户设定时长则自动提升（上限 10 秒）——避免 H3 被迫加速/省略台词导致"跳过情节"。
        2026-08-09 台词内嵌：台词是"路名看着王菲说：\"我喜欢你\""完整句，
        只统计引号内的台词原文字数（动作/人名不占语速）。
        返回 (生效时长, 是否自动提升)。"""
        try:
            _chars = len(self._dialogue_quote_text(dialogue)) if hasattr(self, '_dialogue_quote_text') else len(str(dialogue or '').strip())
            if _chars <= 0:
                return max(5, int(user_dur or 5)), False
            _need = int(math.ceil(_chars / 3.5))
            _need = max(5, min(_need, 10))
            _base = max(5, int(user_dur or 5))
            if _need > _base:
                return _need, True
            return _base, False
        except Exception:
            return max(5, int(user_dur or 5)), False

    def _plot_summary(self, director):
        """从导演控制文本提取\"画面内容\"动作主线（首句，≤60字），
        拼到提示词最前面——H3 对提示词开头指令执行度最高，前置剧情主线可减少跳情节。"""
        try:
            if not director:
                return ''
            import re as _re
            _m = _re.search(r'画面内容[：:]\s*([^；;。]{6,60})', director)
            _plot = _m.group(1).strip() if _m else ''
            if not _plot:
                return ''
            return '【本镜剧情】%s，必须完整呈现，不得省略或跳过任何情节动作。\n' % _plot
        except Exception:
            return ''


    def _inject_h3_ref_defs(self, prompt, refs_meta, has_prev_frame):
        """2026-08-19 分镜衔接修复：把实际参考图用途写进提示词（<Picture N> 编号），
        替换写死的"无外部参考素材"——让 H3 知道 ref_image_0 是上一镜末帧起始画面锚点，
        以及各角色/场景/道具参考图的用途。无参考图时原样返回。"""
        if not prompt or '【subject_definitions 素材定义】' not in prompt:
            return prompt
        lines = []
        n = 0
        if has_prev_frame:
            n += 1
            lines.append('<Picture %d>：上一镜末帧图（本镜起始画面锚点），视频必须从该画面自然开始，'
                         '人物位置、姿态、光线、构图与上一镜结尾衔接，不得跳变。' % n)
        for _u, _name, _atype in (refs_meta or []):
            n += 1
            _nm = str(_name or ('参考图%d' % n))
            if _atype == 'character':
                lines.append('<Picture %d>：%s人物参考，锁定五官、脸型、身形、服饰造型，全程保持样貌稳定不变形。' % (n, _nm))
            elif _atype == 'scene':
                lines.append('<Picture %d>：%s场景参考，锁定环境布局、色调、道具位置，场景构图统一。' % (n, _nm))
            elif _atype == 'prop':
                lines.append('<Picture %d>：%s道具参考，锁定道具形制、材质、颜色，位置状态与参考一致。' % (n, _nm))
            else:
                lines.append('<Picture %d>：%s参考图，作为画面构成参考。' % (n, _nm))
        if not lines:
            return prompt
        ref_text = '\n'.join(lines)
        old = '无外部参考素材。请根据文字建立并锁定以下角色、场景和道具。'
        if old in prompt:
            prompt = prompt.replace(old, '参考素材（以下图片编号对应实际上传参考图）：\n' + ref_text
                                    + '\n无图部分按文字建立并锁定以下角色、场景和道具。', 1)
        else:
            # 找不到固定句：插在 subject_definitions 标题后
            prompt = prompt.replace('【subject_definitions 素材定义】',
                                    '【subject_definitions 素材定义】\n' + ref_text, 1)
        return prompt

    def _extract_h3_full_prompt(self, body):
        """V5.0 新格式：提取发给 H3 的提示词 = 仅【H3视频提示词】六段全文。
        用户 2026-08-19 指令：分镜信息不要、画面与视听细节不要，只保留六段式。
        找不到六段结构时返回 None（调用方回退旧格式提取）。"""
        if not body:
            return None
        # 提取【H3视频提示词】段（兼容 ** 粗体；终点 negative_constraint 段结束，丢弃【自检】）
        m2 = re.search(r'(【\*?H3视频提示词\*?】)\s*(.*?)(?=\n\s*【自检】|\n\s*=====|\Z)', body, re.S)
        if not m2:
            return None
        h3_seg = m2.group(1).strip() + '\n' + m2.group(2).strip()
        # 必须含【subject_definitions 素材定义】（六段结构标志）；没有则不是完整六段
        if '【subject_definitions 素材定义】' not in h3_seg:
            return None
        # 终点：negative_constraint 段结束（其后若有残留如【自检】，一并丢弃）
        end_m = re.search(r'【negative_constraint 负面约束】[\s\S]*?(?=\n\s*【|\n\s*=====|\Z)', h3_seg)
        if end_m:
            h3_seg = h3_seg[:end_m.end()]
        return h3_seg.strip()


    def _extract_h3_duration(self, body):
        """2026-08-19 用户要求：按提示词时间轴总时长生成视频。
        解析 H3 提示词中的总时长（秒）：优先 detailed_description 标题"总时长X秒"，
        否则取所有时间段终点最大值（0-2.8秒…5.8-8秒 → 8）。返回 int（clamp 5-15）；失败返回 None。"""
        if not body:
            return None
        import re as _re_d
        # 1) 标题总时长："总时长8秒" / "总时长8.5秒"
        m = _re_d.search(r'总时长\s*(\d+(?:\.\d+)?)\s*秒', body)
        if m:
            return max(5, min(int(math.ceil(float(m.group(1)))), 15))
        # 2) 时间段终点最大值："0-2.8秒…5.8-8秒" → 取最大终点 8
        ends = _re_d.findall(r'[-–—]\s*(\d+(?:\.\d+)?)\s*秒', body)
        if ends:
            _max = max(float(x) for x in ends)
            return max(5, min(int(math.ceil(_max)), 15))
        return None

    def _extract_h3_dialogue(self, body):
        """V5.0 新格式：从 detailed_description 提取台词（台词（说话人）：'…' 模式）。
        返回 str（拼接的台词原文），供时长自适应使用；无台词返回 ''。"""
        if not body:
            return ''
        lines = []
        for m in re.finditer(r"台词（([^）]+)）：[\'“\"]([^\'”\"]+)[\'”\"]", body):
            speaker = m.group(1).strip()
            line = m.group(2).strip()
            if speaker and line:
                lines.append(speaker + '：' + line)
        # 兼容 "X说：'…'" / "X道："…"" 模式（detailed_description 内常见写法）
        for m in re.finditer(r"([\u4e00-\u9fff]{2,6})(?:说|道|喊|叫|问|答)[：:]\s*[\'“\"]([^\'”\"]+)[\'”\"]", body):
            speaker = m.group(1).strip()
            line = m.group(2).strip()
            if speaker and line:
                lines.append(speaker + '：' + line)
        return '\n'.join(lines)

    def _parse_storyboard_prompts(self):
        """从分镜资产 Tab 文本中解析出所有分镜的提示词列表"""
        try:
            text = self.text_widgets.get('storyboard').get('1.0', tk.END)
        except Exception:
            return []
        if not text.strip():
            return []
        prompts = []
        # 按分镜分隔符切分：===== 分镜 N · 标题 =====
        parts = re.split(r'=====\s*分镜\s*(\d+)[^\n]*=====', text)
        # parts[0] 是开头说明，之后是 (分镜号, 内容) 交替
        for i in range(1, len(parts), 2):
            num = parts[i].strip()
            body = parts[i + 1] if i + 1 < len(parts) else ''
            # 提取【英文AI提示词】/【中文AI提示词】（兼容 markdown 星号：**【中文AI提示词】**）
            # 2026-08-09 用户要求：发给模型的提示词变英文（H3 底层 Qwen3VL 对英文理解更稳定，
            # 且避免 H3 把中文画面描述当语音内容念出来——00070 无台词分镜出现中英混杂语音的根因）。
            # 始终优先英文AI提示词，中文仅作回退。
            # 2026-08-19 用户指令：优先提取【H3视频提示词】完整七段全文（分镜所有内容全部发 H3）；
            # 找不到七段（旧格式资产）时回退【中文AI提示词】提取——已生成旧资产不受影响。
            _h3_full = self._extract_h3_full_prompt(body)
            _is_cn = (str((self.current_project or {}).get('ethnicity', '') or '中国').strip() != '海外')
            if _h3_full:
                prompt = _h3_full
                _is_h3_full = True
            else:
                _is_h3_full = False
                en = re.search(r'【英文AI提示词】\**\s*\**\s*(.*?)(?=\n\s*\**【|\n\s*=====|\Z)', body, re.S)
                cn = re.search(r'【中文AI提示词】\**\s*\**\s*(.*?)(?=\n\s*\**【英文|\n\s*=====|\Z)', body, re.S)
                # 2026-08-10 修正：中国项目画面描述**优先中文【中文AI提示词】**——H3 Qwen3VL 原生支持中文，
                # 英文画面描述会被 H3 音频生成当语音念出来（外语声音根因，00070 已实证）。海外项目才用英文。
                # 2026-08-16 锁死中文：只取中文AI提示词，缺失时不再回退英文（英文画面描述会被H3念成外语）
                prompt = (cn.group(1).strip() if cn else '') or (en.group(1).strip() if en else '')
            # 2026-08-16 修复：LLM 常把"台词：XX说…"写进画面描述 → H3 把所有台词从一个人嘴里念出。
            # 剔除画面描述中的台词段（台词只由【对话】段注入），保留其余画面内容。
            # 2026-08-17 修复（分镜一多念一句根因）：旧正则依赖「气氛/构图/说/道/讲」关键词，
            # 台词段后无这些词（如"台词：路名（看着苏晴）：\"我喜欢你\"。远处灯光闪烁。"）就删不干净
            # → 画面描述残留台词 → H3 把第二句也念出来。改为按字段边界删除整段台词，
            # 兼容 同行/换行、有无引号 全部格式。
            import re as _re_dl2
            def _strip_dialogue_seg(p):
                """从画面描述中整段剔除「台词：…」内容，删到 字段边界/分镜边界/引号闭合 为止。
                边界关键词 = LLM 分镜模板的下一字段（场面描述里残留台词段之后通常紧跟这些字段）。"""
                if not p:
                    return p
                # 1) 引号台词（含换行/多句）：台词：苏晴说："你回来了"。/ 台词：\n苏晴：\n"你回来了"
                #    删到最后一个引号闭合后的标点，保留引号后面的画面描述
                _m = _re_dl2.search(r'台词\s*[:：][^\n【]*(?:[\"“][\s\S]*?[\"”][。！？]?|.+?[。！？])', p)
                if _m:
                    p = p.replace(_m.group(0), '')
                # 2) 无引号台词（台词：苏晴：你回来了。/ 台词：\n苏晴说：你回来了）
                p = _re_dl2.sub(r'台词\s*[:：]\s*\n?[^\n【]*?(?:说|道|讲|喊|叫|念|问|答|低语|自语|心想|OS)[^。！？\n]*[。！？]?', '', p)
                # 3) 兜底：任何残留的「台词：」行（含换行形式）——删到下一个字段/分镜边界
                _parts = []
                for _ln in p.split('\n'):
                    _s = _ln.strip()
                    if _re_dl2.match(r'^台词\s*[:：]', _s):
                        continue  # 跳过台词标记行
                    if _s.startswith(('【', '=====')) or _re_dl2.match(r'^(场景|角色|站位|景别|角度|焦段|构图|运镜|画面内容|光影|渲染|人声|情绪|气氛|字幕|道具|景深|统一视觉|电影画质|镜头光晕|画面极具|画质技术)[：:]', _s):
                        _parts.append(_ln)  # 新字段边界：保留本行
                        continue
                    # 非边界行：若上一行是台词标记行，跳过（台词内容行）
                    if _parts and _re_dl2.match(r'^台词\s*[:：]', _parts[-1].strip()):
                        # 本行是台词内容（人名：台词 或 引号台词）→ 跳过；否则保留
                        if _re_dl2.match(r'^[^\n【]{0,12}?[：:]\s*[\"“]', _s) or _re_dl2.search(r'[\"“].+?[\"”]', _s):
                            continue
                    _parts.append(_ln)
                p = '\n'.join(_parts)
                # 清理空行堆积与行首残留
                p = _re_dl2.sub(r'\n{3,}', '\n\n', p)
                return p.strip()
            if not _is_h3_full:
                # 旧格式才剔除画面描述内台词段（七段模式的台词已内嵌 detailed_description，不能删）
                prompt = _strip_dialogue_seg(prompt)
                if not _is_cn:
                    prompt = (cn.group(1).strip() if cn else '') or prompt
            if prompt:
                # 分镜归属章节：优先用项目保存的 storyboard_chapter（重开项目后 combo 恢复为
                # "全部章节"，若直接用 combo 当前值会把所有分镜章节覆盖成"全部章节"→ 按章生成视频失效）
                _ch = ''
                try:
                    _ch = (self.current_project or {}).get('storyboard_chapter') or ''
                except Exception:
                    _ch = ''
                if not _ch or _ch == '全部章节':
                    _ch = self.combo_vid_chapter.get() if hasattr(self, 'combo_vid_chapter') else "全部章节"
                # 2026-08-08 用户要求恢复：导演控制提取（景别/运镜/构图/画面/光影/音效/情绪微表情）+ 台词提取
                _style = self.combo_global_style.get() if hasattr(self, 'combo_global_style') else DEFAULT_VIDEO_STYLE
                _eth = (self.current_project or {}).get('ethnicity', '') or '中国'
                # 2026-08-10 修正：导演控制按项目地域走对应语言分支（中国=中文标签，海外=英文），
                # 不再写死'海外'强制英文——英文标签文本会被 H3 念成外语。
                _director = self._extract_director_guide(body, _style, _eth)
                if _is_h3_full:
                    # 2026-08-19 七段模式：导演信息已完整内嵌 detailed_description（镜头/景别/运镜），
                    # 置空 director 防止 worker 末尾重复追加（用户要求：分镜所有内容全部发给 H3，不另加尾巴）
                    _director = ''
                _dialogue = self._extract_dialogue(body)
                if not _dialogue and _is_h3_full:
                    _dialogue = self._extract_h3_dialogue(body)
                # 2026-08-10 修正：台词内嵌仅中文（中国项目）；海外项目才用英文台词
                _dialogue_en = self._dialogue_en(_dialogue) if _dialogue else ''
                # 2026-08-10 修正：中国项目 DIALOGUE 引导用**中文**（英文引导会被 H3 念外语）
                _dl_final = _dialogue_en if (not _is_cn and _dialogue_en) else _dialogue
                if _is_h3_full:
                    # 七段模式：台词已内嵌 detailed_description（台词（X）：'…'），不再追加【对话】段
                    pass
                elif _dl_final and str(_dl_final).strip() and str(_dl_final).strip().lower() != '无':
                    # 台词内嵌：紧跟画面描述，无【台词】标记（去掉标记词，H3 更易识别为语音内容）
                    # 2026-08-09 说话人绑定：多句台词拆为每句独立一行（分号挤一段会让 H3 当成
                    # 同一人连续说话，导致两人对话全从一个人嘴里出来）；
                    # 2026-08-10 修正：引导改中文（H3 原生支持中文；英文引导文本有被念风险）
                    # 2026-08-16 锁死中文：仅中文引导（英文 DIALOGUE 分支已删除，防外语复活）
                    _dl_seg = ('\n【对话】画面中人物之间的对话。每句台词由冒号前标注的人说出，说话时只有他/她的嘴动，'
                               '其他人保持安静倾听。每句台词用中文普通话逐字说出。'
                               '默认禁止任何背景人声、环境人声——除这句台词外不得出现任何人说话声、人群声、交谈声、议论声；仅当本镜提示词明确写有「周围窃窃私语」「低声议论」等环境人声描述字样时，才允许轻微的环境人声（必须是中文普通话的说话声，严禁外语发音，音量压到极低——不超过台词音量的20%、如同远处几乎听不清的细碎耳语）。\n'
                               + str(_dl_final).strip().replace('；', '\n'))
                    if _dl_seg not in prompt:
                        prompt = prompt.rstrip() + _dl_seg
                _h3_dur = self._extract_h3_duration(prompt) if _is_h3_full else None
                prompts.append({'num': num, 'prompt': prompt, 'chapter': _ch,
                                'director': _director, 'dialogue': _dialogue,
                                'dialogue_en': _dialogue_en, 'is_cn': _is_cn,
                                'h3_duration': _h3_dur})
        return prompts

    def _rebuild_empty_sb_list(self):
        """清空分镜提示词列表 UI"""
        try:
            for w in self.sb_inner.winfo_children():
                w.destroy()
            tk.Label(self.sb_inner, text='（暂无分镜提示词，请先生成分镜资产后点击"🔄 重新同步"）',
                     font=('微软雅黑', 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(anchor='w', pady=6, padx=8)
            self.sb_canvas.configure(scrollregion=self.sb_canvas.bbox('all'))
        except Exception:
            pass

    def _set_sb_all_checked(self, checked=True):
        """2026-08-15 需求：全选/取消全选所有分镜复选框（一键勾选或取消）"""
        try:
            for var in getattr(self, 'story_prompt_vars', []) or []:
                try:
                    var.set(bool(checked))
                except Exception:
                    pass
            n = len(getattr(self, 'story_prompt_vars', []) or [])
            self._show_toast('已%s全部 %d 个分镜' % ('选中' if checked else '取消选中', n), 'info')
        except Exception as e:
            self._show_toast('操作失败: %s' % e, 'error')

    def _sync_storyboard_prompts(self, silent=False):
        """从分镜资产 Tab 重新同步分镜提示词列表到视频 Tab"""
        try:
            prompts = self._parse_storyboard_prompts()
        except Exception as e:
            if not silent:
                self._show_toast('分镜解析失败: ' + str(e), 'warning')
            return
        self.storyboard_prompts = prompts
        self.story_prompt_vars = []
        self.story_prompt_texts = []
        self._sb_ref_photo_refs = {}
        # 重建列表 UI
        try:
            for w in self.sb_inner.winfo_children():
                w.destroy()
        except Exception:
            pass
        if not prompts:
            try:
                tk.Label(self.sb_inner, text='（暂无分镜提示词，请先生成分镜资产后点击"🔄 重新同步"）',
                         font=('微软雅黑', 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(anchor='w', pady=6, padx=8)
                self.sb_canvas.configure(scrollregion=self.sb_canvas.bbox('all'))
            except Exception:
                pass
            return
        _render_ok = 0
        for _pi, p in enumerate(prompts):
            try:
                # 分镜分区：每行 = 勾选+分镜号 | 左:智能匹配参考图缩略图 | 右:分镜提示词
                row = tk.Frame(self.sb_inner, bg=COLOR_PANEL)
                row.pack(fill='x', pady=3, padx=4)
                # 勾选 + 分镜号
                head = tk.Frame(row, bg=COLOR_PANEL)
                head.pack(side='left', anchor='n', pady=2)
                var = tk.BooleanVar(value=True)
                chk = tk.Checkbutton(head, variable=var, bg=COLOR_PANEL,
                                     activebackground=COLOR_PANEL)
                chk.pack(anchor='w')
                # 2026-08-21 点击分镜名称弹出大编辑窗（完整提示词编辑，保存写回该分镜）
                _sb_idx = _pi
                _lbl_num = tk.Label(head, text='✎ 分镜 ' + str(p['num']), font=('微软雅黑', 9, 'bold'),
                                    fg=COLOR_ACCENT, bg=COLOR_PANEL, cursor='hand2')
                _lbl_num.pack(anchor='w')
                _lbl_num.bind('<Button-1>', lambda e, _n=_sb_idx: self._open_sb_prompt_editor(_n))
                # 左：该分镜智能匹配到的参考图缩略图
                ref_box = tk.Frame(row, bg=COLOR_PANEL)
                ref_box.pack(side='left', anchor='n', padx=(2, 4), pady=2)
                try:
                    self._render_sb_ref_thumbs(ref_box, str(p['num']))
                except Exception:
                    pass
                # 2026-08-15 需求2：分镜参考图编辑按钮（删除/添加匹配图片）
                try:
                    btn_edit_ref = tk.Button(ref_box, text="✎ 编辑匹配", font=("微软雅黑", 7),
                                             bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT,
                                             command=lambda n=str(p['num']): self._open_sb_ref_editor(n))
                    btn_edit_ref.pack(anchor='w', pady=(2, 0))
                    bind_hover(btn_edit_ref, COLOR_BORDER, "#D0D0D0")
                except Exception:
                    pass
                # 右：分镜提示词（2026-08-21 改紧凑 height=2；双击框体也弹出大编辑窗）
                txt = tk.Text(row, height=2, font=FONT_CODE, bg=COLOR_INPUT, fg=COLOR_TEXT,
                              relief='solid', bd=1, wrap=tk.WORD)
                txt.insert('1.0', p['prompt'])
                txt.pack(side='left', fill='x', expand=True, padx=(2, 0))
                txt.bind('<Double-Button-1>', lambda e, _n=_pi: self._open_sb_prompt_editor(_n))
                self.story_prompt_vars.append(var)
                self.story_prompt_texts.append(txt)
                _render_ok += 1
            except Exception as _re:
                try:
                    self.ctx.log('\n[系统日志] 分镜 %s 提示词行渲染失败: %s\n' % (p.get('num', '?'), _re))
                except Exception:
                    pass
        try:
            self.sb_canvas.configure(scrollregion=self.sb_canvas.bbox('all'))
        except Exception:
            pass
        if not silent:
            self._show_toast('已同步 %d 个分镜提示词' % len(prompts), 'success')
        else:
            try:
                if _render_ok < len(prompts):
                    self.ctx.log('[系统日志] 分镜提示词同步：成功渲染 %d/%d 行\n' % (_render_ok, len(prompts)))
            except Exception:
                pass

    def _open_sb_prompt_editor(self, idx):
        """2026-08-21 点击分镜名称/双击提示词框 → 弹出大编辑窗：完整展示提示词，
        编辑后点「保存」写回该分镜（更新 storyboard_prompts + 行内控件，生成视频即用新内容）"""
        try:
            if idx is None or idx < 0 or idx >= len(self.storyboard_prompts):
                self._show_toast('分镜索引无效', 'warning')
                return
            p = self.storyboard_prompts[idx]
            row_txt = self.story_prompt_texts[idx] if idx < len(self.story_prompt_texts) else None
            num = p.get('num', idx + 1)
            cur = row_txt.get('1.0', tk.END).strip() if row_txt else (p.get('prompt') or '')

            dlg = tk.Toplevel(self.root)
            dlg.title('编辑 分镜%s 提示词' % num)
            dlg.configure(bg=COLOR_PANEL)
            dlg.transient(self.root)
            dlg.geometry('820x620+%d+%d' % (self.root.winfo_x() + 50, self.root.winfo_y() + 50))
            try:
                dlg.iconbitmap(resource_path('app.ico'))
            except Exception:
                pass
            dlg.minsize(560, 400)

            tk.Label(dlg, text='分镜%s 完整提示词（编辑后点「保存」写回该分镜）' % num,
                     font=('微软雅黑', 11, 'bold'), fg=COLOR_ACCENT_DARK, bg=COLOR_PANEL
                     ).pack(anchor='w', padx=14, pady=(12, 4))

            ed_frame = tk.Frame(dlg, bg=COLOR_PANEL)
            ed_frame.pack(fill='both', expand=True, padx=14, pady=6)
            editor = tk.Text(ed_frame, font=FONT_CODE, bg=COLOR_INPUT, fg=COLOR_TEXT,
                             relief='solid', bd=1, wrap=tk.WORD, undo=True)
            vsb = tk.Scrollbar(ed_frame, orient='vertical', command=editor.yview)
            editor.configure(yscrollcommand=vsb.set)
            vsb.pack(side='right', fill='y')
            editor.pack(side='left', fill='both', expand=True)
            editor.insert('1.0', cur)
            editor.focus_set()

            btns = tk.Frame(dlg, bg=COLOR_PANEL)
            btns.pack(fill='x', padx=14, pady=(0, 12))

            def _save():
                new_prompt = editor.get('1.0', tk.END).strip()
                p['prompt'] = new_prompt
                if row_txt is not None:
                    row_txt.delete('1.0', tk.END)
                    row_txt.insert('1.0', new_prompt)
                try:
                    self._auto_save_project()
                except Exception:
                    pass
                self._show_toast('分镜%s 提示词已保存' % num, 'success')
                dlg.destroy()

            def _save_and_close():
                _save()

            btn_save = tk.Button(btns, text='✅ 保存', font=('微软雅黑', 10, 'bold'),
                                 bg=COLOR_ACCENT, fg='#FFFFFF', relief=tk.FLAT, command=_save_and_close)
            btn_save.pack(side='left', padx=(0, 10))
            bind_hover(btn_save, COLOR_ACCENT, COLOR_ACCENT_DARK)
            btn_cancel = tk.Button(btns, text='取消', font=('微软雅黑', 10),
                                   bg=COLOR_BORDER, fg=COLOR_TEXT, relief=tk.FLAT, command=dlg.destroy)
            btn_cancel.pack(side='left')
            bind_hover(btn_cancel, COLOR_BORDER, '#D0D0D0')
            # Ctrl+S 快捷保存
            editor.bind('<Control-s>', lambda e: _save())
        except Exception as e:
            self._show_toast('打开提示词编辑窗失败: %s' % e, 'error')

    def _render_sb_ref_thumbs(self, container, num):
        """在分镜分区左侧渲染该分镜智能匹配到的参考图缩略图（最多9张，48px）"""
        try:
            refs = self._refs_for_storyboard_num(num, with_meta=True)
            if not refs:
                tk.Label(container, text='无参考图', font=('微软雅黑', 7),
                         fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(anchor='w')
                return
            for url, name, atype in refs[:9]:
                found = None
                for _core, _item in (self.asset_images or {}).items():
                    if _item and _item.get('url') == url:
                        found = _item
                        break
                cell = tk.Frame(container, bg=COLOR_PANEL)
                cell.pack(side='left', padx=1, pady=1)
                img = found.get('img') if found else None
                ph = None
                if img is not None:
                    try:
                        t = img.copy()
                        t.thumbnail((40, 40), Image.LANCZOS)
                        ph = ImageTk.PhotoImage(t)
                        self._sb_ref_photo_refs[len(self._sb_ref_photo_refs)] = ph
                    except Exception:
                        ph = None
                cv = tk.Canvas(cell, width=44, height=44, bg=COLOR_PANEL,
                               highlightthickness=1, highlightbackground=COLOR_BORDER)
                cv.pack(side='top')
                if ph:
                    cv.create_image(22, 22, image=ph)
                else:
                    cv.create_text(22, 22, text=str(name or '')[:3], fill=COLOR_TEXT_DIM,
                                   font=('微软雅黑', 6))
        except Exception:
            pass

    def _collect_sb_prompts(self, selected_only):
        """收集分镜提示词：selected_only=True 仅勾选的；False 全部。
        若视频Tab章节下拉选了具体章节，只收集该章节的分镜。"""
        out = []
        vid_ch = self.combo_vid_chapter.get() if hasattr(self, 'combo_vid_chapter') else "全部章节"
        for i, p in enumerate(self.storyboard_prompts):
            if i >= len(self.story_prompt_vars):
                continue
            txt = self.story_prompt_texts[i] if i < len(self.story_prompt_texts) else None
            prompt = txt.get('1.0', tk.END).strip() if txt else (p.get('prompt') or '')
            if not prompt:
                continue
            # 2026-08-09：UI 文本框可能被用户编辑过（或旧版同步无台词内嵌）→ 若 prompt 无台词行则补内嵌
            import re as _re_dl
            _has_dl = bool(_re_dl.search(r'[：:]\s*["“]', prompt)) or '旁白' in prompt
            if not _has_dl:
                _dl = p.get('dialogue', '')
                _is_cn = p.get('is_cn', True)
                if not _is_cn:
                    _dl = p.get('dialogue_en', '') or _dl
                if _dl and str(_dl).strip() and str(_dl).strip().lower() != '无':
                    # 2026-08-10 修正：引导改中文（H3 原生支持中文；英文引导文本有被念风险）
                    # 2026-08-16 锁死中文：仅中文引导（英文 DIALOGUE 分支已删除）
                    _dl_seg = ('\n【对话】画面中人物之间的对话。每句台词由冒号前标注的人说出，说话时只有他/她的嘴动，'
                               '其他人保持安静倾听。每句台词用中文普通话逐字说出。'
                               '默认禁止任何背景人声、环境人声——除这句台词外不得出现任何人说话声、人群声、交谈声、议论声；仅当本镜提示词明确写有「周围窃窃私语」「低声议论」等环境人声描述字样时，才允许轻微的环境人声（必须是中文普通话的说话声，严禁外语发音，音量压到极低——不超过台词音量的20%、如同远处几乎听不清的细碎耳语）。\n'
                               + str(_dl).strip().replace('；', '\n'))
                    if _dl_seg not in prompt:
                        prompt = prompt.rstrip() + _dl_seg
            if selected_only and not self.story_prompt_vars[i].get():
                continue
            # 按章节过滤：分镜 chapter 为空或"全部章节"视为通用分镜放行（兼容旧项目/全部生成），
            # 只过滤明确属于其他章节的分镜
            if vid_ch and vid_ch != "全部章节":
                p_ch = p.get('chapter') or ''
                if p_ch and p_ch != '全部章节' and p_ch != vid_ch:
                    continue  # 该分镜不属于所选章节
            out.append({'num': p.get('num', i + 1), 'prompt': prompt, 'chapter': p.get('chapter', ''),
                        'director': p.get('director', ''), 'dialogue': p.get('dialogue', ''),
                        'h3_duration': p.get('h3_duration'),
                        'is_cn': p.get('is_cn', True), 'dialogue_en': p.get('dialogue_en', '')})
        return out

    def _on_gen_selected_sb_videos(self):
        prompts = self._collect_sb_prompts(selected_only=True)
        if not prompts:
            self._show_toast('请先勾选要生成的分镜提示词（至少1个）', 'warning')
            return
        self._start_sb_video_batch(prompts)

    def _on_gen_all_sb_videos(self):
        prompts = self._collect_sb_prompts(selected_only=False)
        if not prompts:
            self._show_toast('当前没有分镜提示词可生成', 'warning')
            return
        self._start_sb_video_batch(prompts)

    def _start_sb_video_batch(self, prompts):
        """批量生成视频：串行逐个生成（复用智能匹配参考图逻辑）"""
        self._sb_batch_prompts = prompts
        self._sb_batch_index = 0
        self._story_batch_done = 0
        self._sb_batch_in_progress = True
        # 预读取参数（worker 线程不能直接访问 tkinter 控件）
        self._sb_batch_dur = int(self.combo_vid_duration.get())
        self._sb_batch_ratio = self.combo_vid_ratio.get()
        self._sb_batch_res = self.combo_vid_res.get()
        self._sb_batch_style = self.combo_global_style.get()
        self._sb_batch_lang = self.combo_vid_lang.get()
        self.btn_gen_vid.config(state=tk.DISABLED)
        self.btn_gen_sb_all.config(state=tk.DISABLED)
        # 2026-08-21 需求2：记录锁定时间戳（3 分钟超时自动恢复）
        self._btn_lock_times['gen_vid'] = time.time()
        self.label_vid_status.config(text='分镜视频批量生成中 0/%d ...' % len(prompts))
        self.ctx.log('\n[系统日志] 开始批量生成分镜视频，共 %d 个分镜...\n' % len(prompts))
        # 2026-08-21 启动即显示"正在生成"跑马灯行
        try:
            self._update_video_history_ui()
        except Exception:
            pass
        threading.Thread(target=self._sb_video_batch_worker, daemon=True).start()

    def _sb_video_batch_worker(self):
        prompts = list(getattr(self, '_sb_batch_prompts', []))
        total = len(prompts)
        dur = getattr(self, '_sb_batch_dur', 5)
        ratio = getattr(self, '_sb_batch_ratio', '16:9')
        res = getattr(self, '_sb_batch_res', '1080p')
        # 分镜衔接初始值：单独生成第 N+1 镜（N>1）时用最近生成的视频衔接；
        # 从第 1 镜开始（全部分镜）则不衔接（第 1 镜没有上一镜）
        prev_video_url = None
        try:
            _first_num = str(prompts[0].get('num', '1')) if prompts else '1'
            if _first_num != '1' and self.video_history:
                prev_video_url = self.video_history[-1]
        except Exception:
            pass
        for idx, item in enumerate(prompts, 1):
            if getattr(self.ctx, 'stop_flag', False):
                self.ctx.log('\n[系统日志] 用户已停止批量生成视频。\n')
                break
            self._sb_batch_index = idx
            # 2026-08-21 每镜开始 → 刷新视频历史（顶部显示"正在生成 分镜 X/Y"跑马灯）
            try:
                self.root.after(0, self._update_video_history_ui)
            except Exception:
                pass
            # 2026-08-09 提示词结构重构（用户要求）：
            #  ①【执行要求+语言要求】前置（H3 对开头指令执行度最高——约束/语言先锁定，杜绝自由发挥/语言漂移）
            #  ②画面描述（英文）+ 台词（内嵌，中文原文）
            #  ③导演控制（全英文标签）
            prompt = item['prompt']
            dur_eff = dur
            num = item.get('num', idx)
            self.ctx.log('\n[系统日志] [%d/%d] 正在生成分镜 %s 视频...\n' % (idx, total, num))
            # 2026-08-19 用户要求：按提示词时间轴总时长生成——提示词写 8 秒就生成 8 秒，
            # 绝不被界面默认时长截断（时间轴未走完不得提前结束）。
            _h3_dur = item.get('h3_duration')
            # 台词-时长自适应：仅当提示词未提供时间轴总时长时兜底（台词已内嵌进画面描述）
            _dialogue = ''
            try:
                _dialogue = item.get('dialogue', '')
                if _h3_dur:
                    dur_eff = int(_h3_dur)
                    self.ctx.log('[系统日志] 分镜 %s 按提示词时间轴 %d 秒生成（详细画面动态时序总时长）\n'
                                 % (num, dur_eff))
                else:
                    dur_eff, _auto = self._auto_duration_for_dialogue(_dialogue, dur)
                    if _auto:
                        self.ctx.log('[系统日志] 分镜 %s 台词较长（%d 字），时长自动调整为 %d 秒\n'
                                     % (num, len(str(_dialogue).strip()), dur_eff))
            except Exception:
                pass
            # ③导演控制（机位运镜视角，全英文标签，用户要求必须传）
            try:
                _director = item.get('director', '')
                if _director and _director not in prompt:
                    prompt = prompt.rstrip() + '\n' + _director
            except Exception:
                pass
            # 智能匹配参考图（纯 url 列表传给 video_skill，图是旁路节点）
            matched = self._refs_for_storyboard_num(num, with_meta=True)
            if not matched:
                matched = []
                for it in reversed(self.image_history):
                    if it.get('url'):
                        matched.append((it['url'], it.get('name', ''), it.get('type', '')))
                    if len(matched) >= 6:
                        break
            self.pending_video_ref_urls = [u for u, _, _ in matched]
            self.video_matched_ready = True
            # 2026-08-19 分镜衔接修复：提示词注入参考素材说明（含上一镜末帧锚点），
            # 替换"无外部参考素材"——H3 才能正确使用 ref_image_0 起始画面
            try:
                prompt = self._inject_h3_ref_defs(prompt, matched, bool(prev_video_url))
            except Exception:
                pass
            try:
                # 分镜衔接：把上一镜视频 URL 注入 api_config（VideoSkill 据此接 ref_videos+ref_video_audios）
                cfg = self._get_api_config()
                if prev_video_url:
                    cfg['prev_video_url'] = prev_video_url
                # 2026-08-21 本地尾帧优先
                try:
                    _prev_num = self._story_batch_done
                    _tail_cand = os.path.join(self._tail_frames_dir(), "分镜%d.png" % _prev_num)
                    if _prev_num >= 1 and os.path.exists(_tail_cand):
                        cfg['prev_tail_frame'] = _tail_cand
                except Exception:
                    pass
                # 人物音色：该分镜涉及的人物资产上传的音色（本地路径列表，最多3个）
                _voices = self._voices_for_storyboard_num(num)
                if _voices:
                    cfg['ref_audio_paths'] = _voices
                self.agent.generate_video(prompt, cfg,
                                          dur_eff, ratio, res,
                                          list(self.pending_video_ref_urls),
                                          local_refs=self._local_paths_for_refs(matched))
                # generate_video 是异步线程，等待其完成信号（video_done/video_failed 事件递增计数）
                deadline = time.time() + 2400
                base = self._story_batch_done
                base_fail = getattr(self, '_story_batch_fail_count', 0)
                while time.time() < deadline and self._story_batch_done == base:
                    if getattr(self.ctx, 'stop_flag', False):
                        break
                    time.sleep(1)
                # 统计成功/失败（失败计数递增 = 本镜失败；否则成功）
                if getattr(self, '_story_batch_fail_count', 0) > base_fail:
                    self._sb_batch_fail = getattr(self, '_sb_batch_fail', 0) + 1
                else:
                    self._sb_batch_ok = getattr(self, '_sb_batch_ok', 0) + 1
                # 更新上一镜 URL（_handle_video_done 已写入 current_video_url；仅成功时更新）
                if self.current_video_url:
                    prev_video_url = self.current_video_url
                self.root.after(0, lambda i=idx, n=total: self.label_vid_status.config(
                    text='分镜视频批量生成中 %d/%d ...' % (i, n)))
            except Exception as e:
                self.ctx.log('\n[系统日志] 分镜 %s 视频生成异常: %s\n' % (num, e))
                self._sb_batch_fail = getattr(self, '_sb_batch_fail', 0) + 1
        # 收尾（真实统计：成功 X 失败 Y，不再无条件弹"完成"）
        _ok = getattr(self, '_sb_batch_ok', 0)
        _fail = getattr(self, '_sb_batch_fail', 0)
        self.ctx.log('\n[系统日志] 批量生成视频完成：成功 %d 个，失败 %d 个。\n' % (_ok, _fail))
        self.root.after(0, lambda: self._finish_sb_video_batch(_ok, _fail))

    def _finish_sb_video_batch(self, ok=0, fail=0):
        # 按钮恢复放最前 + try/finally 保证异常中断也能恢复（修复：批量异常时按钮永远灰色）
        try:
            self._sb_batch_in_progress = False
            self.btn_gen_vid.config(state=tk.NORMAL)
            self.btn_gen_sb_all.config(state=tk.NORMAL)
        except Exception:
            pass
        # 真实统计收尾（修复：原来无条件弹"完成"，全部失败也弹成功）
        if fail and not ok:
            self.label_vid_status.config(text='批量生成失败（%d 个）' % fail)
            self._show_toast('批量生成失败：%d 个分镜视频生成失败，请查看日志' % fail, 'error')
        elif fail:
            self.label_vid_status.config(text='批量生成完成（成功 %d / 失败 %d）' % (ok, fail))
            self._show_toast('批量生成完成：成功 %d 个，失败 %d 个（详见日志）' % (ok, fail), 'warning')
        else:
            self.label_vid_status.config(text='批量生成完成（成功 %d 个）' % ok)
            self._show_toast('全部分镜视频生成完成（%d 个）！' % ok, 'success')
        # 重置统计（下次批量重新计数）
        self._sb_batch_ok = 0
        self._sb_batch_fail = 0
        self._story_batch_fail_count = 0
        # 2026-08-21 移除"正在生成"跑马灯行
        try:
            self._stop_video_progress_marquee()
        except Exception:
            pass

    # ============ 本地控制接口（OpenClaw/QQ 遥控，2026-08-20 新增） ============
    def _ctrl_submit(self, fn, timeout=15):
        """在主线程执行 fn（root.after 调度），返回是否已执行。"""
        ev = threading.Event()
        def _run():
            try:
                fn()
            except Exception:
                pass
            finally:
                ev.set()
        try:
            self.root.after(0, _run)
            return ev.wait(timeout=timeout)
        except Exception:
            return False

    def _gen_in_progress(self):
        """全链路生成是否进行中（生成按钮禁用 = 在生成）"""
        try:
            return str(self.btn_generate.cget('state')) == 'disabled'
        except Exception:
            return False

    def ctrl_status(self):
        try:
            return {
                'ok': True,
                'busy': bool(getattr(self, '_sb_batch_in_progress', False)) or self._gen_in_progress(),
                'storyboard_count': len(getattr(self, 'storyboard_prompts', []) or []),
                'video_count': len(getattr(self, 'video_history', []) or []),
                'last_video': (getattr(self, 'video_history', []) or [None])[-1],
                'project': (self.current_project or {}).get('name', ''),
                'port': getattr(self, '_ctrl_port', 8712),
            }
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def ctrl_export(self):
        try:
            vids = list(getattr(self, 'video_history', []) or [])
            return {'ok': True, 'count': len(vids), 'videos': vids}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def ctrl_stop(self):
        try:
            self.ctx.stop_flag = True
            return {'ok': True, 'stopped': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def ctrl_list_projects(self):
        """列出全部项目（名称/备注/更新时间）"""
        try:
            items = self._list_projects()
            return {'ok': True, 'count': len(items),
                    'projects': [{'name': p.get('name', ''), 'remark': (p.get('remark') or '')[:50],
                                  'updated': p.get('updated', '')} for p in items]}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def ctrl_new_project(self, name, remark=''):
        """新建项目（主线程执行 _create_project）"""
        name = (name or '').strip()
        if not name:
            return {'ok': False, 'error': '项目名为空'}
        # 重名检查（与对话框逻辑一致）
        if os.path.exists(self._project_path(name)):
            return {'ok': False, 'error': '同名项目已存在：%s' % name}
        ev = threading.Event()
        result = {}
        def _run():
            try:
                self._create_project(name, (remark or '').strip(), '中国')
                result['ok'] = True
            except Exception as e:
                result['error'] = str(e)
            finally:
                ev.set()
        try:
            self.root.after(0, _run)
            if not ev.wait(timeout=15):
                return {'ok': False, 'error': 'UI 主线程无响应'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        if result.get('error'):
            return {'ok': False, 'error': result['error']}
        return {'ok': True, 'project': name}

    def ctrl_open_project(self, name):
        """打开项目（按名字从项目列表匹配）"""
        name = (name or '').strip()
        if not name:
            return {'ok': False, 'error': '项目名为空'}
        try:
            items = self._list_projects()
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        target = None
        for p in items:
            if p.get('name') == name:
                target = p
                break
        if target is None:
            # 模糊匹配：包含
            for p in items:
                if name in (p.get('name') or ''):
                    target = p
                    break
        if target is None:
            return {'ok': False, 'error': '未找到项目：%s（现有：%s）' % (name, '、'.join(p.get('name','') for p in items[:10]) or '无')}
        ev = threading.Event()
        result = {}
        def _run():
            try:
                self._load_project(target)
                result['ok'] = True
            except Exception as e:
                result['error'] = str(e)
            finally:
                ev.set()
        try:
            self.root.after(0, _run)
            if not ev.wait(timeout=15):
                return {'ok': False, 'error': 'UI 主线程无响应'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
        if result.get('error'):
            return {'ok': False, 'error': result['error']}
        return {'ok': True, 'project': target.get('name', name)}

    def ctrl_shutdown(self):
        """关闭 wave漫流 软件（延时让 HTTP 先回响应）"""
        try:
            def _quit():
                try:
                    self.root.quit()
                    self.root.destroy()
                except Exception:
                    pass
            self.root.after(500, _quit)
            return {'ok': True, 'shutdown': True}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def ctrl_generate(self, novel, command=''):
        """全链路生成：小说 → 剧本/资产/分镜。阻塞到完成（最长 90 分钟）。"""
        if not novel or not str(novel).strip():
            return {'ok': False, 'error': 'novel 文本为空'}
        if self._gen_in_progress():
            return {'ok': False, 'error': '已有生成任务进行中'}
        def _submit():
            try:
                self.text_input_novel.config(state=tk.NORMAL)
                self.text_input_novel.delete('1.0', tk.END)
                self.text_input_novel.insert('1.0', novel)
            except Exception:
                pass
            try:
                self.text_input_command.config(state=tk.NORMAL)
                self.text_input_command.delete('1.0', tk.END)
                self.text_input_command.insert('1.0', command or '')
            except Exception:
                pass
            self._on_generate_click()
        if not self._ctrl_submit(_submit):
            return {'ok': False, 'error': '提交失败（UI 主线程无响应）'}
        time.sleep(1)  # 等 _on_generate_click 重置 _story_gen_done
        deadline = time.time() + 5400
        while time.time() < deadline:
            if self._story_gen_done:
                break
            if getattr(self.ctx, 'stop_flag', False):
                return {'ok': False, 'stopped': True, 'error': '用户已停止'}
            time.sleep(1)
        return {
            'ok': bool(self._story_gen_done),
            'storyboard_count': len(self.storyboard_prompts),
            'video_count': len(self.video_history),
        }

    def ctrl_video(self, nums=None):
        """生成分镜视频：nums=None 全部；[1,2,3] 指定分镜。阻塞到完成（最长 90 分钟）。"""
        if getattr(self, '_sb_batch_in_progress', False):
            return {'ok': False, 'error': '已有视频生成任务进行中'}
        self._ctrl_video_error = ''
        def _submit():
            try:
                if nums is None:
                    self._on_gen_all_sb_videos()
                else:
                    all_p = self._collect_sb_prompts(selected_only=False)
                    ns = set()
                    for x in nums:
                        try:
                            ns.add(int(x))
                        except Exception:
                            pass
                    targets = [p for p in all_p if int(p.get('num', -1)) in ns]
                    if not targets:
                        self._ctrl_video_error = '没有找到指定分镜: %s（当前共 %d 个分镜）' % (sorted(ns), len(all_p))
                        return
                    self._start_sb_video_batch(targets)
            except Exception as e:
                self._ctrl_video_error = str(e)
        if not self._ctrl_submit(_submit):
            return {'ok': False, 'error': '提交失败（UI 主线程无响应）'}
        if getattr(self, '_ctrl_video_error', ''):
            return {'ok': False, 'error': self._ctrl_video_error}
        base_done = self._story_batch_done
        base_fail = getattr(self, '_story_batch_fail_count', 0)
        deadline = time.time() + 5400
        while time.time() < deadline:
            if not getattr(self, '_sb_batch_in_progress', False):
                break
            if getattr(self.ctx, 'stop_flag', False):
                return {'ok': False, 'stopped': True, 'error': '用户已停止'}
            time.sleep(1)
        fail_delta = getattr(self, '_story_batch_fail_count', 0) - base_fail
        done_delta = self._story_batch_done - base_done
        success = max(0, done_delta - fail_delta)
        return {'ok': True, 'success': success, 'fail': fail_delta,
                'total': len(self.storyboard_prompts)}

    # ============ 资产图匹配（分镜→资产图）============
    def _build_asset_match_area(self, parent):
        """构建资产图匹配区域 UI（参考图设置下方、历史图片列表上方）"""
        tk.Label(parent, text="▼ 资产图匹配 (按分镜规划显示涉及资产图，勾选可重新生成/删除)",
                 font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_INPUT).pack(anchor="w", pady=(6, 2))
        asset_frame = tk.Frame(parent, bg=COLOR_INPUT)
        asset_frame.pack(fill="x", pady=2)
        self.asset_canvas = tk.Canvas(asset_frame, bg=COLOR_PANEL, highlightthickness=0, height=190)
        asset_vs = ttk.Scrollbar(asset_frame, orient="vertical", command=self.asset_canvas.yview)
        self.asset_canvas.configure(yscrollcommand=asset_vs.set)
        self.asset_canvas.pack(side="left", fill="both", expand=True)
        asset_vs.pack(side="right", fill="y")
        self.asset_inner = tk.Frame(self.asset_canvas, bg=COLOR_PANEL)
        self._win_asset = self.asset_canvas.create_window((0, 0), window=self.asset_inner, anchor="nw")
        self.asset_inner.bind("<Configure>",
                              lambda e: self.asset_canvas.configure(scrollregion=self.asset_canvas.bbox("all")))
        self.asset_canvas.bind("<Configure>",
                               lambda e: self.asset_canvas.itemconfig(self._win_asset, width=e.width))
        self.asset_canvas.bind("<MouseWheel>", self._on_asset_wheel)
        # 初始占位提示
        self._asset_placeholder_ui()

    def _on_asset_wheel(self, event):
        try:
            self.asset_canvas.yview_scroll(int(-event.delta / 120), "units")
        except Exception:
            pass

    def _asset_placeholder_ui(self):
        """无分镜/无资产时的占位提示"""
        try:
            if not hasattr(self, 'asset_inner'):
                return  # 生成器版已移除资产图匹配区域 UI，仅保留数据逻辑
            for w in self.asset_inner.winfo_children():
                w.destroy()
            tk.Label(self.asset_inner,
                     text='（暂无资产图。\n请先生成分镜与资产图片，然后点击"🔄 重新同步"）',
                     font=("微软雅黑", 9), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL,
                     justify="left").pack(anchor="w", pady=8, padx=10)
            self.asset_canvas.configure(scrollregion=self.asset_canvas.bbox("all"))
        except Exception:
            pass

    def _asset_core_name(self, name):
        """提取资产核心名（去掉 角色/场景/道具/资产 前缀与分隔符 + markdown 残留）"""
        import re as _re
        s = str(name or '').strip()
        s = self._clean_asset_name(s)
        s = _re.sub(r'^(角色|人物|场景|道具|资产|物品)[·\-_:：\s]+', '', s)
        s = _re.sub(r'[·\-_:：\s]+', '', s)
        return s

    def _clean_asset_name(self, s):
        """清洗资产名/字段值：去掉 markdown 残留（**、*、反引号）、行首 -、首尾空白"""
        import re as _re
        s = str(s or '').strip()
        s = s.replace('**', '').replace('`', '').replace('*', '')
        s = _re.sub(r'^\s*[-—–]\s*', '', s)
        return s.strip()

    def _asset_match_aliases(self, name, atype=''):
        """生成资产名的多个匹配别名（供智能匹配使用）：
        1. 原名（保留分隔符）  2. 去类型前缀  3. 去前缀+去分隔符（原核心名）
        4. 按分隔符切的第一段（如'主角-少年期'→'主角'）
        5. 去括号注释（'敌方狙击手（第一晚）'→'敌方狙击手'）
        6. prop 类型：提取最后 2-3 字简称（'战术耳机'→'耳机'，'PFM-1地雷'→'地雷'）"""
        import re as _re
        s = str(name or '').strip()
        aliases = set()
        if s:
            aliases.add(s)
        s2 = _re.sub(r'^(角色|人物|场景|道具|资产|物品)[·\-_:：\s]+', '', s)
        if s2 and s2 != s:
            aliases.add(s2)
        s3 = _re.sub(r'[·\-_:：\s]+', '', s2)
        if s3 and s3 != s2:
            aliases.add(s3)
        # 首段：按分隔符切分取第一段
        first = _re.split(r'[·\-_:：\s]+', s2, 1)[0] if s2 else ''
        if first and len(first) >= 2 and first != s2 and first != s3:
            aliases.add(first)
        # 去括号注释（'敌方狙击手（第一晚）' → '敌方狙击手'）
        no_paren = _re.sub(r'[（(].*?[）)]', '', s2).strip()
        if no_paren and len(no_paren) >= 2 and no_paren not in aliases:
            aliases.add(no_paren)
        # prop 类型：提取尾部 2-3 字简称（'战术耳机'→'耳机'，'狙击步枪'→'步枪'）
        if atype == 'prop':
            base = no_paren or s2
            tail2 = base[-2:] if len(base) >= 3 else ''
            tail3 = base[-3:] if len(base) >= 4 else ''
            for t in (tail3, tail2):
                if t and len(t) >= 2 and t not in aliases and not t.isdigit():
                    aliases.add(t)
        return aliases

    def _alias_in_body(self, al, body, known_names=None):
        """检查别名 al 是否出现在 body 中，且不是其他中文词的子串。
        跳过条件（命中位置左侧紧邻汉字时）：
        a) 左侧汉字+别名 构成已知资产名（如资产'女主角'存在时，'主角'在'女主角'内→跳过）
        b) 左侧是强修饰字（女/男/配/反/小/大/老/主/辅/正/副）→ 视为复合词内部（如'女主角'）"""
        import re as _re
        known_names = known_names or set()
        strong_mod = set('女男配反小大老主辅正副')
        start = 0
        while True:
            idx = body.find(al, start)
            if idx < 0:
                return False
            before = body[idx - 1] if idx > 0 else ''
            if before and _re.match(r'[\u4e00-\u9fff]', before):
                if (before + al) in known_names:
                    start = idx + 1
                    continue
                if before in strong_mod:
                    start = idx + 1
                    continue
            return True

    def _parse_storyboard_fields(self, body):
        """解析分镜正文中的结构化字段行（- 场景：X / - 角色：X / - 道具：X）。
        返回 {'scene': [...], 'character': [...], 'prop': [...]}，值为候选名列表（顿号/逗号分割）。
        角色值含"无人物/无/无角色"等 → 该角色项忽略。支持带 - 前缀或不带前缀。"""
        out = {'scene': [], 'character': [], 'prop': []}
        key_map = {'场景': 'scene', '角色': 'character', '人物': 'character', '道具': 'prop', '物品': 'prop'}
        for line in body.split('\n'):
            ls = line.strip()
            for k, v in key_map.items():
                # 匹配 "- 场景：xxx" / "场景：xxx"（带或不带连字符前缀）
                for sep in ('：', ':'):
                    marker = '- ' + k + sep
                    if ls.startswith(marker):
                        val = self._clean_asset_name(ls[len(marker):])
                        break
                    if ls.startswith(k + sep):
                        val = self._clean_asset_name(ls[len(k) + 1:])
                        break
                else:
                    continue
                if not val:
                    continue
                # 忽略"无人物/无/无角色/环境交代"等占位
                if v == 'character' and re.match(r'^(无|无人物|无角色|暂无|—|-|－|$)', val):
                    continue
                if v == 'scene' and re.match(r'^(无|无场景|—|-|－|$)', val):
                    continue
                # 顿号/逗号/斜杠/中文逗号 分割候选
                for cand in re.split(r'[、，,/\s]+', val):
                    cand = cand.strip()
                    if cand and len(cand) >= 2 and cand not in out[v]:
                        out[v].append(cand)
        return out

    def _common_prefix_len(self, a, b):
        n = 0
        for x, y in zip(a, b):
            if x != y:
                break
            n += 1
        return n

    def _field_asset_match(self, field_val, asset_name, aliases):
        """字段候选值 vs 资产名 是否匹配：
        1. 完全相等（清洗后） 2. 一方包含另一方（≥2字） 3. 公共前缀≥3且前缀后是括号/结尾"""
        fv = self._clean_asset_name(field_val)
        an = self._clean_asset_name(asset_name)
        if not fv or not an:
            return False
        # 1. 相等（或 fv 是别名之一）
        if fv == an:
            return True
        for al in aliases:
            if al and fv == al:
                return True
        # 2. 包含（≥2 字，避免单字误配）
        if len(fv) >= 2 and (fv in an or an in fv):
            return True
        # 3. 公共前缀 ≥3：前缀末尾是括号（双方都是"名称（注释）"形式，在注释处分叉），
        #    或一方是另一方的真前缀（"敌方狙击手" vs "敌方狙击手（第一晚）"）
        cp = self._common_prefix_len(fv, an)
        if cp >= 3:
            if fv[cp - 1:cp] in '（(' and an[cp - 1:cp] in '（(':
                return True
            if cp == len(fv) or cp == len(an):
                return True
        return False

    # 道具触发词表：资产名含左侧任一关键词 + 分镜正文含右侧任一描述词 → 语义关联。
    # 解决"狙击步枪"这类资产名在分镜正文中不出现（只出现"枪管/瞄准镜"）的匹配缺口。
    PROP_TRIGGER_WORDS = [
        (('枪', '步枪', '手枪', '狙击', '机枪', '枪械', '武器', '炮'),
         ('枪管', '枪口', '扣扳机', '瞄准镜', '瞄准', '射击', '开火', '子弹', '弹道', '击发',
          '枪托', '扳机', '消音', '枪声', '开枪', '拔枪', '换弹', '上膛', '弹匣', '枪械')),
        (('剑', '刀', '匕首', '利刃'),
         ('剑', '拔剑', '拔刀', '刀光', '剑刃', '剑鞘', '刀刃', '出鞘', '挥剑', '刀锋')),
        (('耳机', '耳麦', '对讲机'),
         ('耳机', '耳麦', '通讯', '报话', '听筒', '电流声', '对讲')),
        (('地雷', '炸弹', '炸药', '雷'),
         ('雷场', '地雷', '爆炸', '引爆', '爆破', '爆弹')),
        (('车', '坦克', '装甲'),
         ('驾驶', '引擎', '方向盘', '发动', '油门', '履带', '刹车', '汽车')),
        (('手机', '电话'),
         ('电话', '手机', '铃声', '拨号', '来电', '接听')),
        (('钥匙',), ('钥匙', '开锁', '锁孔')),
        (('灯', '手电'), ('灯', '手电', '照明', '光亮', '灯光')),
        (('酒', '酒杯', '酒瓶'), ('酒杯', '酒瓶', '喝酒', '饮酒', '斟酒', '干杯')),
        (('烟', '烟斗'), ('抽烟', '烟斗', '烟圈', '烟雾', '吐烟')),
        (('表', '手表'), ('手表', '表盘', '指针', '秒针', '看表')),
        (('相机', '摄像机'), ('相机', '快门', '拍照', '摄影', '镜头')),
        (('伞',), ('撑伞', '雨伞', '伞面', '打伞')),
        (('包', '背包'), ('背包', '挎包', '行囊', '包裹', '背囊')),
        (('眼镜',), ('眼镜', '镜片', '镜框', '墨镜')),
        (('书', '文件', '档案', '卷宗'), ('翻阅', '翻开', '文件', '档案', '书页', '卷宗', '书本')),
        (('药', '药品'), ('吃药', '服药', '药瓶', '药片', '药物')),
        (('信', '信件'), ('信件', '书信', '拆信', '信封', '信纸')),
        (('钱', '金币', '钞票'), ('金钱', '钞票', '金币', '掏钱', '付钱')),
        (('地图', '罗盘'), ('地图', '罗盘', '指南针')),
    ]

    # 兜底实体道具词表：LLM 生成道具资产卡可能漏项（如高跟鞋），生图前扫描正文，
    # 出现次数 >= MIN 的实体道具词自动补进资产列表（type=prop）。
    # 词表覆盖常见服装/鞋履/饰品/随身物品/器物，名称需足够具体以免误补。
    PROP_FALLBACK_WORDS = (
        # 鞋履
        '高跟鞋', '皮鞋', '运动鞋', '长靴', '短靴', '靴子', '拖鞋', '凉鞋', '布鞋', '球鞋',
        # 服装
        '婚纱', '礼服', '西装', '旗袍', '风衣', '大衣', '夹克', '衬衫', '卫衣', '毛衣', '连衣裙',
        '裙子', '裤子', '牛仔裤', '围巾', '领带', '领结', '手套', '帽子', '鸭舌帽', '丝巾',
        # 饰品
        '耳环', '耳钉', '项链', '戒指', '手链', '手镯', '发卡', '胸针', '手表', '墨镜', '眼镜',
        # 随身物品
        '手机', '钱包', '钥匙', '雨伞', '背包', '挎包', '手提包', '行李箱', '公文包', '口红',
        '香水', '镜子', '梳子', '扇子', '打火机',
        # 器物/饮品
        '酒杯', '酒瓶', '茶杯', '茶壶', '咖啡杯', '碗', '筷子', '蜡烛', '台灯', '花瓶', '相框',
        '日记本', '信封', '请柬', '红包', '项链盒', '戒指盒', '捧花', '花束',
    )
    PROP_FALLBACK_MIN = 2  # 正文中出现至少 N 次才自动补（≥2 显著，避免误补）

    # 兜底道具提示词的题材风格映射（跟随小说旁的题材下拉，避免所有项目都是"modern urban"）
    PROP_FALLBACK_STYLE = {
        '军事': 'military tactical style', '热血动作': 'action combat style',
        '历史史诗': 'ancient historical style', '古风仙侠': 'ancient chinese xianxia style',
        '仙侠奇幻': 'ancient chinese xianxia style', '科幻末日': 'sci-fi post-apocalyptic style',
        '恐怖灵异': 'horror dark style', '悬疑惊悚': 'suspense noir style',
        '心理剧': 'psychological drama style', '甜宠言情': 'modern romance style',
        '都市职场': 'modern urban style', '家庭温情': 'modern warm family style',
        '成长励志': 'modern youth style', '喜剧幽默': 'modern comedic style',
    }
    PROP_FALLBACK_STYLE_DEFAULT = 'modern realistic style'

    def _extract_assets_full(self, text):
        """健壮版资产生成解析（2026-08-09 全资产生成要求）。

        按行识别资产卡标题（===== 角色 N · 名 ===== / ===== 道具资产卡 · 名 ===== / 【场景 N】名），
        从卡内提取【英文AI提示词】（缺英文时退回【中文AI提示词】），按 (类型, 名) 去重。

        修复：旧 llm_skill.extract_assets 用正则跨行匹配（(.*?) =====），当卡名含中文括号
        （如“贴身宫女（贪嘴丫鬟）=====” 的 ===== 前无空格）时正则跨行吞内容，导致：
        ① 小宫女卡名变成超长垃圾；② 后续所有道具卡匹配失败全部丢失；③ 续写重复段被重复解析。
        本方法按行解析 + 按 (类型, 名) 去重，保证资产卡里提到的资产全部解析出来，不过滤、不发挥。

        返回 list[{'type','name','prompt_en'}]（与 llm_skill.extract_assets 同结构）。
        """
        import re as _re
        assets = []
        seen = set()  # (type, name)
        try:
            lines = str(text or '').split('\n')
            i, n = 0, len(lines)
            _re_char = _re.compile(r'^=+\s*角色\s*\d+\s*·\s*(.+?)\s*=+\s*$')
            _re_prop = _re.compile(r'^=+\s*道具资产卡\s*·\s*(.+?)\s*=+\s*$')
            _re_scene = _re.compile(r'^【场景\s*\d+】\s*(.+?)\s*$')
            # 卡内容边界：其他卡标题 / 大段标题(A~G) / 分隔线（=数量容错 4/5/6）
            _boundary = _re.compile(r'^=+\s*[^=]|^【场景\s*\d+】|^-----|^[A-G]\.\s|^=+\s*$')
            while i < n:
                line = lines[i].strip()
                atype = None
                m = _re_char.match(line)
                if m:
                    atype, name = 'character', m.group(1).strip()
                else:
                    m = _re_prop.match(line)
                    if m:
                        atype, name = 'prop', m.group(1).strip()
                    else:
                        m = _re_scene.match(line)
                        if m:
                            atype, name = 'scene', m.group(1).strip()
                if atype and name:
                    # 收集本卡内容到下一个边界
                    seg = []
                    j = i + 1
                    while j < n:
                        _l = lines[j].strip()
                        if _boundary.match(_l):
                            break
                        seg.append(lines[j])
                        j += 1
                    body = '\n'.join(seg)
                    prompt_en = ''
                    _em = _re.search(r'【英文AI提示词】\s*\*?\*?\s*(.*?)(?=\n【|\n=+|\n-----|\n[A-G]\. |\Z)', body, _re.S)
                    if _em:
                        prompt_en = _em.group(1).strip()
                    if not prompt_en:
                        _cm = _re.search(r'【中文AI提示词】\s*\*?\*?\s*(.*?)(?=\n【|\n=+|\n-----|\n[A-G]\. |\Z)', body, _re.S)
                        if _cm:
                            prompt_en = _cm.group(1).strip()
                    prompt_en = prompt_en.replace('\n', ' ')
                    if prompt_en:
                        # 去首尾 markdown 粗体标记（**），保证同名不同格式也能去重
                        name = _re.sub(r'^\*+|\*+$', '', name).strip()
                        key = (atype, name)
                        if key not in seen:
                            seen.add(key)
                            assets.append({'type': atype, 'name': name, 'prompt_en': prompt_en})
                    i = j
                    continue
                i += 1
        except Exception:
            pass
        return assets

    def _supplement_missing_props(self, full_text, assets):
        """资产兜底补全：扫描正文中出现 ≥N 次的实体道具词，
        若资产列表（含 name）没有覆盖，则自动补一条 prop 资产。
        解决 LLM 生成道具资产卡漏项（如高跟鞋出现12次但没建卡）。"""
        try:
            if not full_text or not assets:
                return 0
            have = set()
            for a in assets:
                if isinstance(a, dict) and a.get('name'):
                    have.add(str(a['name']))
            # 兜底提示词风格：跟随题材下拉（军事→tactical 等）
            style = self.PROP_FALLBACK_STYLE_DEFAULT
            try:
                _g = getattr(self, '_genre_var', None)
                if _g is not None:
                    style = self.PROP_FALLBACK_STYLE.get(_g.get(), self.PROP_FALLBACK_STYLE_DEFAULT)
            except Exception:
                pass
            added = 0
            for w in self.PROP_FALLBACK_WORDS:
                if full_text.count(w) < self.PROP_FALLBACK_MIN:
                    continue
                # 已有同名资产（或资产名包含该词，如"白色高跟鞋"）→ 跳过
                if any(w in h or h in w for h in have):
                    continue
                assets.append({'type': 'prop', 'name': w,
                               'prompt_en': self._fallback_prop_prompt(w, style)})
                have.add(w)
                added += 1
            return added
        except Exception:
            return 0

    def _rebuild_cn_prompt_map(self, full_text, assets=None):
        """重建 资产名→中文提示词 映射（双击图片预览显示用，用户要求显示中文）。
        按类型段提取【中文AI提示词】——角色卡/道具卡/场景卡各自段内提取，
        不依赖资产卡名的精确匹配（解决带括号/特殊字符名提取失败的问题）。"""
        try:
            self._asset_prompt_cn_map = {}
            if not full_text:
                return
            # 按类型段切分：角色卡段 / 道具卡段 / 场景卡段
            # 角色段：===== 角色 N · 名字 ===== ... 【中文AI提示词】...【英文...】（=数量容错）
            for _m in re.finditer(r'=+\s*角色\s*\d+\s*·\s*([^\n=]+?)\s*=+(.*?)(?=\n=+|\Z)', full_text, re.S):
                _name = _m.group(1).strip()
                _seg = _m.group(2)
                _cm = re.search(r'【中文AI提示词】\**\s*(.*?)(?=\n\s*【英文|\n\s*=+|\Z)', _seg, re.S)
                if _cm and _cm.group(1).strip():
                    self._asset_prompt_cn_map[_name] = _cm.group(1).strip().replace('\n', ' ')
            # 道具段：===== 道具资产卡 · 名字 =====
            for _m in re.finditer(r'=+\s*道具资产卡\s*·\s*([^\n=]+?)\s*=+(.*?)(?=\n=+|\Z)', full_text, re.S):
                _name = _m.group(1).strip()
                _seg = _m.group(2)
                _cm = re.search(r'【中文AI提示词】\**\s*(.*?)(?=\n\s*【英文|\n\s*=+|\Z)', _seg, re.S)
                if _cm and _cm.group(1).strip():
                    self._asset_prompt_cn_map[_name] = _cm.group(1).strip().replace('\n', ' ')
            # 场景段：【场景 N】名字
            for _m in re.finditer(r'【场景\s*\d+】\s*([^\n]+?)\n(.*?)(?=\n【场景|\n=+|\Z)', full_text, re.S):
                _name = _m.group(1).strip()
                _seg = _m.group(2)
                _cm = re.search(r'【中文AI提示词】\**\s*(.*?)(?=\n\s*【英文|\n\s*=+|\Z)', _seg, re.S)
                if _cm and _cm.group(1).strip():
                    self._asset_prompt_cn_map[_name] = _cm.group(1).strip().replace('\n', ' ')
        except Exception:
            self._asset_prompt_cn_map = {}

    def _fallback_prop_prompt(self, name, style=None):
        """兜底补全道具的标准英文提示词（四视图静物摄影模板，禁止人物出现；穿戴类加强）"""
        if not style:
            style = self.PROP_FALLBACK_STYLE_DEFAULT
        _wear = any(_w in str(name or '') for _w in ('鞋', '耳环', '耳钉', '戒指', '项链', '手链',
                                                     '手镯', '眼镜', '墨镜', '手表', '发卡', '胸针',
                                                     '领带', '帽子', '手套'))
        _no_human = ('NO person, NO human, NO hands, NO body, no people in frame'
                     if not _wear else
                     'NO person, NO human, NO hands, NO feet, NO body, NO mannequin, '
                     'NO model wearing it, no people in frame, floating product only')
        return ('%s,%s,four views composition front back side detail close-up,'
                'white light gray background,soft top lighting,clear touchable material texture,'
                '8K ultra-detailed,cinematic still life photography,%s' % (style, name, _no_human))

    def _prop_trigger_match(self, asset_name, body):
        """道具资产 vs 分镜正文 的语义触发匹配（武器/装备等）。
        资产名含触发词左列关键词，且正文含右列任一描述词 → True"""
        an = self._clean_asset_name(asset_name)
        if not an:
            return False
        for keys, descs in self.PROP_TRIGGER_WORDS:
            if not any(k in an for k in keys):
                continue
            for d in descs:
                if d in body:
                    return True
        return False

    def _match_assets_to_storyboard(self):
        """解析分镜资产文本 → 每个分镜涉及的资产图列表（智能匹配，不串类型）"""
        try:
            text = self.text_widgets.get('storyboard').get('1.0', tk.END)
        except Exception:
            return
        if not text.strip():
            return
        # 1. 从图片历史收集资产（按核心名去重，取最新），带类型标记。
        #    注意：只要求有 url/name 即可参与匹配（img 缺失时项目重开后的场景也能匹配，
        #    缩略图由后台线程补拉显示）。
        asset_pool = {}   # 核心名 -> 完整条目
        for it in self.image_history:
            nm = it.get('name') or ''
            if not nm or not it.get('url'):
                continue
            core = self._asset_core_name(nm)
            if not core:
                continue
            _typ = it.get('type', '')
            # 类型纠正：资产名含明显道具特征词（PROP_FALLBACK_WORDS）但 type 异常（character/空/中文）
            # → 纠正为 prop。修复：LLM 可能把含人形描述的道具误生成进角色卡/type 丢失，
            # 导致道具出现音色按钮、参考图排序错乱
            if _typ != 'prop':
                try:
                    if any(_w in core for _w in ('手机', '耳环', '雨伞', '高跟鞋', '戒指', '项链', '手链',
                                                  '手表', '眼镜', '背包', '钱包', '钥匙', '捧花', '花束',
                                                  '酒杯', '茶杯', '咖啡', '相机', '镜子', '口红', '香水',
                                                  '文件', '信封', '红包', '礼物', '道具', '鞋', '包',
                                                  '伞', '瓶', '杯', '戒')):
                        _typ = 'prop'
                except Exception:
                    pass
            # 2026-08-09 全资产生成要求：不再过滤随身小物（宫格合并已停用），
            # 资产卡里生成的所有道具都参与分镜参考图匹配。
            asset_pool[core] = {
                'name': nm, 'url': it.get('url', ''),
                'img': it.get('img'), 'prompt': it.get('prompt', ''),
                'type': _typ,
            }
        # 2.5 构建已知名称集合（供词边界判断：'女主角'是资产时，'主角'子串不算独立命中）
        known_names = set()
        for core, item in asset_pool.items():
            known_names.add(core)
            known_names.update(self._asset_match_aliases(item.get('name') or core, item.get('type', '')))
        # 2. 分割分镜（兼容多种分隔符格式）
        parts = re.split(r'=====\s*分镜\s*(\d+)[^\n]*=====', text)
        links = []
        for i in range(1, len(parts), 2):
            num = parts[i].strip()
            body = parts[i + 1] if i + 1 < len(parts) else ''
            # 2a. 字段优先匹配：解析 - 场景/角色/道具 行，与资产名做模糊匹配
            fields = self._parse_storyboard_fields(body)
            field_hit = []
            for ftype, names in fields.items():
                for fv in names:
                    for core, item in asset_pool.items():
                        if core in field_hit:
                            continue
                        an = item.get('name') or core
                        if self._field_asset_match(fv, an, self._asset_match_aliases(an, item.get('type', ''))):
                            field_hit.append(core)
                            break
            # 2b. 道具触发词匹配：prop 类型资产，正文含武器/装备描述词（语义匹配，如"狙击步枪"←"枪管/瞄准镜"）
            trigger_hit = []
            for core, item in asset_pool.items():
                if core in field_hit or core in trigger_hit:
                    continue
                if item.get('type') == 'prop' and self._prop_trigger_match(item.get('name') or core, body):
                    trigger_hit.append(core)
            # 2c. 正文兜底匹配：未被上面匹配的资产，按正文包含别名（≥2 字 + 词边界）
            body_hit = []
            for core, item in asset_pool.items():
                if core in field_hit or core in trigger_hit:
                    continue
                aliases = self._asset_match_aliases(item.get('name') or core, item.get('type', ''))
                for al in sorted(aliases, key=len, reverse=True):
                    if al and len(al) >= 2 and self._alias_in_body(al, body, known_names):
                        body_hit.append(core)
                        break
            # 合并：字段命中在前（类型强关联），触发词次之，正文兜底最后
            hit = field_hit + [c for c in trigger_hit if c not in field_hit] + \
                  [c for c in body_hit if c not in field_hit and c not in trigger_hit]
            links.append({'num': num, 'assets': hit})
        # 2026-08-15 需求2：用户手动编辑过的分镜（_sb_ref_edited 标记）保留用户设置，不被重新匹配覆盖
        edited_map = getattr(self, '_sb_ref_edited', {}) or {}
        if edited_map:
            old_links = {str(ln.get('num')): list(ln.get('assets', [])) for ln in getattr(self, 'story_asset_links', [])}
            for ln in links:
                if str(ln.get('num')) in edited_map and str(ln.get('num')) in old_links:
                    ln['assets'] = old_links[str(ln.get('num'))]
        self.story_asset_links = links
        # 3. 资产图映射（只保留被分镜引用的）
        used = set()
        for ln in links:
            used.update(ln['assets'])
        new_asset_images = {}
        for core in used:
            item = asset_pool.get(core)
            if item:
                new_asset_images[core] = item
        self.asset_images = new_asset_images

    def _open_sb_ref_editor(self, num):
        """2026-08-15 需求2：编辑指定分镜的参考图匹配（可添加/删除图片）。
        对话框列出全部资产图（角色/场景/道具）+ 上传图片，勾选=该分镜使用；保存后写入 story_asset_links 并刷新缩略图。"""
        try:
            # 当前分镜已匹配的资产名
            cur = []
            for ln in getattr(self, 'story_asset_links', []):
                if str(ln.get('num')) == str(num):
                    cur = list(ln.get('assets', []))
                    break
            # 全部可选图片：asset_images（资产图）+ image_history 里 type 为空的上传图
            pool = []  # (key, name, type, img)
            seen_urls = set()
            for core, item in (self.asset_images or {}).items():
                if item and item.get('img') is not None:
                    pool.append((core, item.get('name') or core, item.get('type') or '', item.get('img')))
                    if item.get('url'):
                        seen_urls.add(item.get('url'))
            for it in getattr(self, 'image_history', []):
                u = it.get('url') or ''
                if u and u not in seen_urls and it.get('img') is not None:
                    seen_urls.add(u)
                    pool.append(('hist:' + u, it.get('name') or '上传图', it.get('type') or '上传', it.get('img')))
            if not pool:
                self._show_toast('暂无可编辑的图片（请先生成/上传资产图）', 'warning')
                return

            win = tk.Toplevel(self.root)
            win.title('分镜 %s 参考图编辑' % num)
            win.configure(bg=COLOR_PANEL)
            win.geometry('560x520')
            win.transient(self.root)
            win.grab_set()
            tk.Label(win, text='分镜 %s · 勾选要作为该分镜参考图的图片（可多选）' % num,
                     font=('微软雅黑', 10, 'bold'), fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(anchor='w', padx=12, pady=(10, 4))
            tk.Label(win, text='提示：角色/场景/道具图来自资产；"上传"图来自图片历史。取消勾选=从该分镜移除。',
                     font=('微软雅黑', 8), fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(anchor='w', padx=12)

            # 滚动区：每个图片 = 缩略图 + 勾选框 + 名称
            canvas = tk.Canvas(win, bg=COLOR_PANEL, highlightthickness=0)
            vs = ttk.Scrollbar(win, orient='vertical', command=canvas.yview)
            canvas.configure(yscrollcommand=vs.set)
            canvas.pack(side='left', fill='both', expand=True, padx=(12, 0), pady=8)
            vs.pack(side='right', fill='y', pady=8)
            inner = tk.Frame(canvas, bg=COLOR_PANEL)
            wid = canvas.create_window((0, 0), window=inner, anchor='nw')
            inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
            canvas.bind('<Configure>', lambda e: canvas.itemconfig(wid, width=e.width))
            canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(int(-e.delta / 120), 'units'))

            # 是否已有手动静默编辑标记（用户编辑后重新同步不覆盖）
            edited_key = '_sb_ref_edited'
            if not hasattr(self, edited_key):
                setattr(self, edited_key, {})

            vars_map = {}
            cur_set = set(cur)
            # 已匹配的资产优先排序
            pool.sort(key=lambda x: (0 if x[0] in cur_set else (1 if x[2] != '上传' else 2), x[1]))
            for key, name, atype, img in pool:
                rowf = tk.Frame(inner, bg=COLOR_PANEL)
                rowf.pack(fill='x', padx=6, pady=3)
                var = tk.BooleanVar(value=key in cur_set)
                vars_map[key] = var
                chk = tk.Checkbutton(rowf, variable=var, bg=COLOR_PANEL, activebackground=COLOR_PANEL)
                chk.pack(side='left')
                try:
                    t = img.copy()
                    t.thumbnail((52, 52), Image.LANCZOS)
                    ph = ImageTk.PhotoImage(t)
                    lb = tk.Label(rowf, image=ph, bg=COLOR_PANEL)
                    lb.image = ph
                    lb.pack(side='left', padx=4)
                except Exception:
                    pass
                _tag = {'character': '角色', 'scene': '场景', 'prop': '道具', '上传': '上传'}.get(atype, atype or '图')
                tk.Label(rowf, text='[%s] %s' % (_tag, str(name)[:24]), font=('微软雅黑', 9),
                         fg=COLOR_TEXT, bg=COLOR_PANEL).pack(side='left')

            def _save():
                new_assets = [k for k, v in vars_map.items() if v.get()]
                # 更新 story_asset_links
                found = False
                for ln in getattr(self, 'story_asset_links', []):
                    if str(ln.get('num')) == str(num):
                        ln['assets'] = new_assets
                        found = True
                        break
                if not found:
                    self.story_asset_links.append({'num': num, 'assets': new_assets})
                # 记录手动静默编辑（防止重新同步覆盖）
                setattr(self, edited_key, dict(getattr(self, edited_key, {})))
                getattr(self, edited_key)[str(num)] = True
                win.destroy()
                # 刷新该分镜缩略图：重建分镜列表 UI
                try:
                    self._sync_storyboard_prompts(silent=True)
                except Exception:
                    pass
                self._show_toast('分镜 %s 参考图已更新（%d 张）' % (num, len(new_assets)), 'success')

            btns = tk.Frame(win, bg=COLOR_PANEL)
            btns.pack(fill='x', padx=12, pady=(0, 10))
            tk.Button(btns, text='保存', font=FONT_MAIN, bg=COLOR_ACCENT, fg='white', relief='flat',
                      command=_save).pack(side='left', ipadx=18, ipady=2)
            tk.Button(btns, text='取消', font=FONT_MAIN, bg=COLOR_BORDER, fg=COLOR_TEXT, relief='flat',
                      command=win.destroy).pack(side='left', padx=8, ipadx=18, ipady=2)
            # 全不选=清空该分镜参考图
            tk.Button(btns, text='清空全部', font=FONT_MAIN, bg=COLOR_DANGER, fg='white', relief='flat',
                      command=lambda: [v.set(False) for v in vars_map.values()]).pack(side='left', padx=8, ipadx=10, ipady=2)
        except Exception as e:
            try:
                self._show_toast('参考图编辑打开失败: %s' % e, 'error')
            except Exception:
                pass

    def _refs_for_storyboard_num(self, num, with_meta=False):
        """取指定分镜在资产图匹配区匹配到的参考图 url 列表（角色优先，最多9张，不串类型）。
        with_meta=True 时返回 [(url, 资产名, 类型), ...]（供【参考图定义】段生成）。
        2026-08-15 支持 hist: 前缀 key（用户手动添加的上传图，从 image_history 取 url）。"""
        try:
            for ln in getattr(self, 'story_asset_links', []):
                if str(ln.get('num')) == str(num):
                    items = []
                    for core in ln.get('assets', []):
                        if isinstance(core, str) and core.startswith('hist:'):
                            # 用户手动添加的上传图：按 url 从 image_history 找
                            _u = core[5:]
                            for _it in getattr(self, 'image_history', []):
                                if _it.get('url') == _u and _it.get('url'):
                                    items.append({'url': _it.get('url'), 'name': _it.get('name', '上传图'),
                                                  'type': _it.get('type', '上传')})
                                    break
                        else:
                            item = (self.asset_images or {}).get(core)
                            if item and item.get('url'):
                                items.append(item)
                    if not items:
                        return []
                    # 参考图优先级：角色图最优先（人物一致性）→ 场景图（环境锚定）→ 道具图。
                    # H3 多图参考上限 9 张，按此排序保证关键参考（角色+场景）不被道具挤掉
                    items.sort(key=lambda it: 0 if it.get('type') == 'character'
                               else (1 if it.get('type') == 'scene' else 2))
                    urls = []
                    seen = set()
                    for it in items:
                        u = it.get('url')
                        if u and u not in seen:
                            seen.add(u)
                            if with_meta:
                                urls.append((u, it.get('name', ''), it.get('type', '')))
                            else:
                                urls.append(u)
                        if len(urls) >= self.MAX_VIDEO_REFS:
                            break
                    return urls
        except Exception:
            pass
        return []

    def _ref_defs_section(self, num, refs_meta, has_prev_frame):
        """生成【参考图定义】段：让 H3 明确每张参考图的作用（角色/场景/道具/起始画面）。
        角色图 → 锁定五官脸型身形服饰；场景图 → 锁定环境布局色调；
        道具图 → 锁定道具形制；上一镜末帧图 → 作为本镜起始画面锚点（衔接）。"""
        try:
            lines = []
            n = 0
            for url, name, atype in refs_meta:
                n += 1
                nm = str(name or '参考图%d' % n)
                if atype == 'character':
                    lines.append('图片%d：%s角色人设参考，锁定五官、脸型、身形、服饰造型，全程保持样貌稳定不变形' % (n, nm))
                elif atype == 'scene':
                    lines.append('图片%d：%s场景参考图，锁定环境布局、色调、道具位置，场景构图统一' % (n, nm))
                elif atype == 'prop':
                    lines.append('图片%d：%s道具参考图，锁定道具形制、材质、颜色，位置状态与参考一致' % (n, nm))
                else:
                    lines.append('图片%d：%s参考图，作为画面构成参考' % (n, nm))
            if has_prev_frame:
                n += 1
                lines.append('图片%d：本镜头起始画面参考，作为视频初始画面构图与内容锚点，开头画面须与此图衔接' % n)
            if not lines:
                return ''
            return '【参考图定义】\n' + '\n'.join(lines) + '\n'
        except Exception:
            return ''

    def _voices_for_storyboard_num(self, num):
        """取指定分镜涉及人物资产的音色本地路径列表（人物有上传音色才返回，最多 3 个，H3 ref_audios 上限）"""
        try:
            for ln in getattr(self, 'story_asset_links', []):
                if str(ln.get('num')) == str(num):
                    voices = []
                    seen = set()
                    for core in ln.get('assets', []):
                        item = (self.asset_images or {}).get(core)
                        if item and item.get('type') == 'character':
                            vp = (self.asset_voices or {}).get(core, '')
                            if vp and os.path.exists(vp) and vp not in seen:
                                seen.add(vp)
                                voices.append(vp)
                            if len(voices) >= 3:
                                break
                    return voices
        except Exception:
            pass
        return []

    def _save_asset_image_local(self, pil_img, name, chapter=''):
        """2026-08-21 资产图本地落盘：保存到 项目目录/assets/，返回本地路径（失败返回 ''）。"""
        try:
            if pil_img is None:
                return ''
            d = self._assets_dir()
            safe = re.sub(r'[\\/:*?"<>|]', "_", str(name or "asset")).strip() or "asset"
            if chapter and chapter != "全部章节":
                safe = "%s_%s" % (safe, re.sub(r'[\\/:*?"<>|]', "_", str(chapter)).strip()[:20])
            path = os.path.join(d, safe + ".png")
            buf = io.BytesIO()
            pil_img.convert('RGB').save(buf, format='PNG')
            with open(path, 'wb') as f:
                f.write(buf.getvalue())
            return path
        except Exception:
            return ''

    def _local_paths_for_refs(self, matched):
        """2026-08-21 从匹配的参考图（url,name,type 或 dict）中收集本地路径列表。"""
        out = []
        try:
            for m in matched:
                _lp = ''
                if isinstance(m, dict):
                    _lp = m.get('local_path') or ''
                    _nm = m.get('name') or ''
                else:
                    _url, _nm = m[0], m[1]
                    for _it in self.image_history:
                        if _it.get('name') == _nm and _it.get('local_path'):
                            _lp = _it.get('local_path')
                            break
                if _lp and os.path.exists(_lp):
                    out.append(_lp)
                    continue
                if _nm:
                    _cand = os.path.join(self._assets_dir(), re.sub(r'[\\/:*?"<>|]', "_", str(_nm)) + ".png")
                    if os.path.exists(_cand):
                        out.append(_cand)
                        continue
                out.append('')
        except Exception:
            pass
        return out

    def _rebuild_asset_match_area(self):
        """重建资产图匹配区域 UI"""
        if not hasattr(self, 'asset_inner'):
            return
        for w in self.asset_inner.winfo_children():
            w.destroy()
        self._asset_photo_refs = {}
        if not self.story_asset_links or not self.asset_images:
            self._asset_placeholder_ui()
            return
        for ln in self.story_asset_links:
            num = ln.get('num', '?')
            assets = [a for a in ln.get('assets', []) if a]
            row_title = tk.Frame(self.asset_inner, bg=COLOR_PANEL)
            row_title.pack(fill="x", padx=6, pady=(4, 0))
            tk.Label(row_title, text="分镜 %s：" % num, font=("微软雅黑", 9, "bold"),
                     fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(side="left")
            tk.Label(row_title, text="%d 个资产" % len(assets), font=("微软雅黑", 8),
                     fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(side="left", padx=6)
            if not assets:
                tk.Label(row_title, text="（分镜中未匹配到已生成的资产图）", font=("微软雅黑", 8),
                         fg=COLOR_TEXT_DIM, bg=COLOR_PANEL).pack(side="left", padx=6)
                continue
            row = tk.Frame(self.asset_inner, bg=COLOR_PANEL)
            row.pack(fill="x", padx=6, pady=(0, 2))
            for ci, core in enumerate(assets):
                cell = tk.Frame(row, bg=COLOR_PANEL)
                cell.grid(row=0, column=ci, padx=4, pady=2)
                item = self.asset_images.get(core)
                if item is not None:
                    self._render_asset_cell(cell, core, item)
                else:
                    self._render_asset_placeholder(cell, core)
        self.asset_canvas.configure(scrollregion=self.asset_canvas.bbox("all"))

    def _render_asset_cell(self, cell, core, item):
        """渲染一张资产图：缩略图 + 左上角选择框 + (勾选后)重新生成/删除按钮"""
        try:
            thumb = item['img'].copy()
            thumb.thumbnail((78, 78), Image.LANCZOS)
            ph = ImageTk.PhotoImage(thumb)
            self._asset_photo_refs[core + str(id(cell))] = ph
        except Exception:
            ph = None
        cv = tk.Canvas(cell, width=84, height=84, bg=COLOR_PANEL,
                       highlightthickness=1, highlightbackground=COLOR_BORDER)
        cv.pack(side="top")
        if ph:
            cv.create_image(42, 42, image=ph)
        else:
            cv.create_text(42, 42, text="无图", fill=COLOR_TEXT_DIM, font=("微软雅黑", 8))
        _type_label = {'character': '人物', 'prop': '道具', 'scene': '场景'}.get(item.get('type', ''), '')
        _show_core = (_type_label + '·' + core) if _type_label else core
        cv.create_text(42, 80, text=_show_core, fill=COLOR_TEXT_DIM, font=("微软雅黑", 7), anchor="s")
        # 左上角选择框
        var = tk.BooleanVar(value=False)
        self._asset_checked[core] = var
        chk = tk.Checkbutton(cell, variable=var, bg=COLOR_PANEL, activebackground=COLOR_PANEL,
                             command=lambda c=core: self._toggle_asset_checked(c))
        chk.place(x=0, y=0)
        # 操作按钮行（默认隐藏）
        btns = tk.Frame(cell, bg=COLOR_PANEL)
        btn_re = tk.Button(btns, text="🔄", font=("微软雅黑", 8), bg="#F0A500", fg="white",
                           relief="flat", padx=4, command=lambda c=core: self._regenerate_asset_image(c))
        btn_re.pack(side="left", padx=1)
        btn_del = tk.Button(btns, text="🗑", font=("微软雅黑", 8), bg="#D63027", fg="white",
                            relief="flat", padx=4, command=lambda c=core: self._delete_asset_image(c))
        btn_del.pack(side="left", padx=1)
        btns.pack(side="top", pady=(1, 0))
        # 人物资产：音色上传按钮（生成视频时该人物自动用此音色）
        # 双保险：仅当 type 明确为 character 且资产名不含道具特征词时才显示——
        # 修复：extract_assets 可能把含人形描述的道具（如"手机人形"）误判为 character，
        # 导致道具资产出现音色按钮
        _is_char = item.get('type') == 'character'
        if _is_char:
            try:
                _n = str(core or '')
                # 资产名含道具特征词（PROP_FALLBACK_WORDS 或明显物品词）→ 按道具处理，不显示音色
                if any(_w in _n for _w in ('手机', '耳环', '雨伞', '高跟鞋', '戒指', '项链', '手链',
                                            '手表', '眼镜', '背包', '钱包', '钥匙', '捧花', '花束',
                                            '酒杯', '茶', '咖啡', '相机', '镜子', '口红', '香水',
                                            '文件', '书', '信封', '红包', '礼物', '道具')):
                    _is_char = False
            except Exception:
                pass
        if _is_char:
            vrow = tk.Frame(cell, bg=COLOR_PANEL)
            vrow.pack(side="top", pady=(2, 0))
            _vpath = (self.asset_voices or {}).get(core, '')
            if _vpath and os.path.exists(_vpath):
                _vname = os.path.basename(_vpath)
                tk.Label(vrow, text='🎵 ' + _vname[:8], font=("微软雅黑", 7),
                         fg=COLOR_SUCCESS, bg=COLOR_PANEL).pack(side="left")
                tk.Button(vrow, text="✕", font=("微软雅黑", 7), bg=COLOR_PANEL,
                          fg=COLOR_DANGER, relief="flat", padx=2,
                          command=lambda c=core: self._clear_asset_voice(c)).pack(side="left")
            else:
                tk.Button(vrow, text="🎵 音色", font=("微软雅黑", 7), bg=COLOR_PANEL,
                          fg=COLOR_ACCENT, relief="solid", bd=1, highlightbackground=COLOR_BORDER,
                          padx=4, command=lambda c=core: self._upload_asset_voice(c)).pack(side="left")
        # 记录以便控制显隐
        cell._asset_btns = btns
        cell._asset_var = var
        cell._asset_core = core

    def _render_asset_placeholder(self, cell, core):
        """渲染占位框：图片被删除后的空位，点击可上传新图"""
        cv = tk.Canvas(cell, width=84, height=84, bg=COLOR_INPUT,
                       highlightthickness=1, highlightbackground=COLOR_BORDER,
                       highlightcolor=COLOR_ACCENT)
        cv.pack(side="top")
        cv.create_rectangle(6, 6, 78, 78, outline="#AAAAAA", dash=(3, 3))
        cv.create_text(42, 36, text="点击上传", fill=COLOR_TEXT_DIM, font=("微软雅黑", 8))
        cv.create_text(42, 52, text=core, fill=COLOR_TEXT_DIM, font=("微软雅黑", 7))
        cv.bind("<Button-1>", lambda e, c=core: self._upload_asset_image(c))
        cv.configure(cursor="hand2")

    def _toggle_asset_checked(self, core):
        """勾选资产图 → 显示/隐藏 重新生成/删除 按钮"""
        self._refresh_asset_buttons()

    def _refresh_asset_buttons(self):
        """根据勾选状态刷新所有资产图的操作按钮显隐"""
        for row_frame in self.asset_inner.winfo_children():
            for child in row_frame.winfo_children():
                if hasattr(child, '_asset_btns') and hasattr(child, '_asset_var'):
                    if child._asset_var.get():
                        child._asset_btns.pack(side="top", pady=(1, 0))
                    else:
                        try:
                            child._asset_btns.pack_forget()
                        except Exception:
                            pass

    # ── 随身小物宫格合并（2026-08-09 用户要求：人物随身佩戴的小东西不单独生成，
    #    直接在人物图中用宫格展示，减少资产图数量、避免参考图太多导致视频生成出问题）──
    # 大件保留词表：命中的 prop 仍有独立剧情/画面价值，保留单独生成；
    # 其余 prop（穿戴类/包类/手机钥匙等随身物）一律合并进对应人物图的宫格。
    BIG_PROP_KEEP = (
        # 箱包大件
        '行李箱', '箱子', '旅行箱', '拉杆箱', '手提箱', '皮箱',
        # 信物/文件（剧情关键道具）
        '信封', '信件', '信纸', '遗书', '合同', '文件', '公文包', '档案', '判决书', '地契',
        '账本', '名单', '图纸', '地图', '密信', '圣旨', '诏书', '书信',
        # 武器（军事/武侠题材核心）
        '枪', '剑', '刀', '匕首', '弓', '弩', '箭', '炮', '炸弹', '地雷', '手雷', '盾',
        '矛', '戟', '棍', '锤', '斧', '鞭', '暗器', '飞镖',
        # 大型/家具/交通工具/设备
        '显示屏', '屏幕', '电视', '电脑', '冰箱', '洗衣机', '空调', '柜子', '衣柜', '书柜',
        '桌子', '椅子', '床', '沙发', '茶几', '梳妆台', '书桌', '钢琴', '古琴', '马车',
        '汽车', '轿车', '摩托', '自行车', '电动车', '船', '飞机', '火车',
        # 场景性大件
        '烛台', '香炉', '屏风', '花瓶', '灯笼', '牌匾', '石碑', '佛像', '神像', '雕像',
        '浴桶', '木桶', '水缸', '推车', '担架',
        # 乐器/特殊道具（有独立价值）
        '古筝', '琵琶', '二胡', '唢呐', '笛子', '萧', '鼓',
    )

    def _is_wear_carry_item(self, name):
        """判断 prop 是否算\"随身小物\"（穿戴类/包类/手机钥匙等）→ 合并进人物图宫格。
        大件保留词表命中的返回 False（单独生成）。"""
        try:
            _n = str(name or '')
            if any(k in _n for k in self.BIG_PROP_KEEP):
                return False
            return True
        except Exception:
            return False

    def _match_prop_to_character(self, prop_name, char_names, context_text=''):
        """把随身小物归属到最可能的人物：优先括号注释（手机（林晚）→ 林晚），
        其次按名字包含关系匹配；再按正文上下文（道具出现位置前后 80 字内的人物）；
        匹配不到返回 None（合并进全局宫格/所有人物图）。"""
        try:
            import re as _re
            _p = str(prop_name or '')
            if not _p:
                return None
            # 1. 括号注释：xxx（林晚）/xxx(苏晴)
            m = _re.search(r'[（(]([^（()）]{1,8})[）)]', _p)
            if m:
                _inside = m.group(1).strip()
                for c in char_names:
                    if _inside == c or _inside in c or c in _inside:
                        return c
            # 2. 名字包含：道具名含人物名（苏晴的手机）
            for c in char_names:
                if c and c in _p:
                    return c
            # 3. 人物名含道具名（罕见）
            for c in char_names:
                if c and _p and _p in c:
                    return c
            # 4. 正文上下文：道具出现位置前后 80 字内出现的人物 → 归属该人物（取最近/首次）
            if context_text:
                _hits = []
                for m in _re.finditer(_re.escape(_p), context_text):
                    _ctx = context_text[max(0, m.start() - 80):m.end() + 80]
                    for c in char_names:
                        if c and c in _ctx and c not in [h[0] for h in _hits]:
                            _hits.append((c, m.start()))
                if _hits:
                    # 取首次出现时最近的人物
                    _hits.sort(key=lambda h: h[1])
                    return _hits[0][0]
            return None
        except Exception:
            return None

    def _merge_props_into_characters(self, to_gen):
        """批量生图前合并：把随身小物 prop 从 to_gen 移除，按归属并入对应人物图的宫格提示词。
        返回 (新 to_gen 列表, 合并说明列表)。人物图提示词追加宫格布局指令。"""
        import re as _re
        try:
            # 拆出人物与道具（scene 等其他类型原样保留，绝不丢弃）
            chars = []
            props = []
            others = []  # scene 等非 character/prop 类型，原样保留
            for a in to_gen:
                if not isinstance(a, dict):
                    continue
                if str(a.get('type') or '') in ('character', '人物', '角色'):
                    chars.append(a)
                elif str(a.get('type') or '') in ('prop', '道具'):
                    props.append(a)
                else:
                    others.append(a)
            if not chars:
                return to_gen, []
            char_names = [str(c.get('name') or '') for c in chars if c.get('name')]
            merged = []      # 合并说明
            keep_props = []  # 大件保留
            small_items = []  # 随身小物（待合并）
            for p in props:
                _nm = str(p.get('name') or '')
                if self._is_wear_carry_item(_nm):
                    small_items.append(p)
                else:
                    keep_props.append(p)
            if not small_items:
                return to_gen, []
            # 每个随身小物 → 归属人物（或 None=归入所有人物的公共宫格）
            # 上下文：优先用全部文本（self.text_widgets['all']），失败则空
            try:
                _ctx_text = self.text_widgets.get('all').get('1.0', tk.END) if hasattr(self, 'text_widgets') else ''
            except Exception:
                _ctx_text = ''
            for p in small_items:
                _owner = self._match_prop_to_character(str(p.get('name') or ''), char_names, _ctx_text)
                _detail = str(p.get('prompt_en') or p.get('prompt') or '')
                # 提炼细节：去掉风格尾缀（8K/cinematic/white background 等）保留形制描述
                # ⚠️ 保留 NO person/no people 等禁人约束（否则宫格小物格会画出人脸/人手——2026-08-09 用户报"部分资产图带人脸"）
                _detail = _re.sub(r'(white light gray background|soft top light|8K ultra fine|'
                                  r'cinematic still life photography|clear texture|photorealistic style|'
                                  r'floating product only[^,]*|isolated product photography[^,]*|'
                                  r'product still life[^,]*|,?\s*$)',
                                  '', _detail, flags=_re.I)
                _detail = _detail.strip(' ,，。')
                if not _detail:
                    _detail = str(p.get('name') or '')
                merged.append((_owner, str(p.get('name') or ''), _detail))
            # 按归属分组：owner -> [(name, detail)]
            by_owner = {}
            for owner, nm, dt in merged:
                by_owner.setdefault(owner, []).append((nm, dt))
            # 构造宫格指令并拼进人物图提示词
            grid_notes = []
            for a in chars:
                _cn = str(a.get('name') or '')
                _items = []
                # 显式归属该人物的
                _items.extend(by_owner.get(_cn, []))
                # 归属 None 的公共小物也并入每个人物图（若无显式归属）
                _items.extend(by_owner.get(None, []))
                if not _items:
                    continue
                # 去重
                _seen = set()
                _uniq = []
                for nm, dt in _items:
                    if nm not in _seen:
                        _seen.add(nm)
                        _uniq.append((nm, dt))
                if not _uniq:
                    continue
                _grid = self._build_accessory_grid_cn(_uniq)
                if _grid:
                    a['prompt_en'] = (a.get('prompt_en') or '') + _grid
                    grid_notes.append('%s: %s' % (_cn, '、'.join(n for n, _ in _uniq)))
            # 返回：人物图（含宫格）+ 大件保留道具 + 场景等其他类型（原样保留）
            new_list = chars + keep_props + others
            return new_list, grid_notes
        except Exception:
            return to_gen, []

    def _build_accessory_grid_cn(self, items):
        """构造人物图宫格指令（中英双语）：主图人物 + 随身物细节宫格。"""
        try:
            if not items:
                return ''
            # 宫格规模：1-2个=2格，3-4个=4格(2x2)，5-9个=6格(2x3)，>9取前9
            _n = len(items)
            _grid_spec = 'two' if _n <= 2 else ('2x2 grid' if _n <= 4 else '2x3 grid')
            _cells = []
            for i, (nm, dt) in enumerate(items[:9], 1):
                _cells.append('cell %d: %s (%s)' % (i, nm, dt[:120]))
            _cell_txt = '; '.join(_cells)
            return ('\nGRID LAYOUT: character portrait as main image, plus %s accessory detail cells '
                    'showing the character\'s personal items: %s. '
                    'Each accessory cell is a clean close-up on white background, showing the ITEM ONLY. '
                    'The accessory cells must contain NO human face, NO hands, NO body, NO person. '
                    'The main portrait keeps the character\'s full look (face, hair, outfit) as described above.' % (_grid_spec, _cell_txt))
        except Exception:
            return ''

    def _no_human_suffix(self, name, atype):
        """道具类资产禁止人体约束后缀（穿戴类加强）。统一供批量/单图/重新生成使用。
        返回 '' 表示非道具无需附加。"""
        try:
            if str(atype or '') not in ('prop', '道具'):
                return ''
            _n = str(name or '')
            _wear = any(_w in _n for _w in ('鞋', '耳环', '耳钉', '戒指', '项链', '手链',
                                            '手镯', '眼镜', '墨镜', '手表', '发卡',
                                            '胸针', '领带', '帽子', '手套'))
            return (', isolated product photography on white background, NO person, NO human, '
                    'NO hands, NO feet, NO body, NO mannequin, NO model wearing it, '
                    'no people in frame, floating product only' if _wear else
                    ', product still life, NO person, NO human, NO hands, NO body, NO mannequin, '
                    'no people in frame')
        except Exception:
            return ''

    def _regenerate_asset_image(self, core):
        """重新生成资产图：自动提取该资产保存的提示词生成"""
        item = self.asset_images.get(core)
        if not item:
            self._show_toast('资产不存在', 'warning')
            return
        prompt = item.get('prompt') or self._asset_prompt_map.get(core, '')
        if not prompt:
            self._show_toast('该资产没有保存的提示词\n请先在图片生成Tab手动生成', 'warning')
            return
        # 道具类重新生成也强制禁止人体（修复：原路径无 PROP_NO_HUMAN，道具图含人体）
        _nh = self._no_human_suffix(core, item.get('type', ''))
        if _nh and 'NO person' not in prompt:
            prompt = prompt.rstrip() + _nh
        self._regenerating_asset = core
        self.ctx.log('[系统日志] 正在重新生成资产图 [%s]...\n' % core)
        try:
            self.agent.image_skill.generate_single_image(prompt, self._get_api_config(),
                                                         self.combo_img_ratio.get(),
                                                         self.combo_img_res.get())
            self._show_toast('正在重新生成 [%s] 资产图...' % core, 'info')
        except Exception as e:
            self._regenerating_asset = None
            self._show_toast('生成失败: ' + str(e), 'warning')

    def _delete_asset_image(self, core):
        """删除资产图：从所有分镜中移除该图，保留占位框供上传"""
        if not messagebox.askyesno(APP_NAME, '确定删除资产图 [%s]？\n'
                                            '将从所有分镜中删除该图片，保留位置供重新上传。' % core):
            return
        self.asset_images.pop(core, None)
        self._asset_checked.pop(core, None)
        self._show_toast('已删除资产图 [%s]，可点击占位框上传新图' % core, 'success')
        self._rebuild_asset_match_area()

    def _upload_asset_voice(self, core):
        """人物音色选择：从音色文件夹/任意位置选择本地音频（用户自己管理音色文件）"""
        # 默认打开 exe 同目录的 voices/ 文件夹（用户可把音色文件放这里，也可选任意位置）
        voices_dir = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "voices")
        if not os.path.isdir(voices_dir):
            try:
                os.makedirs(voices_dir)
            except Exception:
                voices_dir = os.path.expanduser("~")
        path = filedialog.askopenfilename(
            initialdir=voices_dir,
            title='为人物 [%s] 选择音色音频（可先点「打开音色文件夹」放入音色文件）' % core,
            filetypes=[('音频文件', '*.wav *.mp3 *.flac *.m4a *.aac *.ogg'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            vdir = os.path.join(os.environ.get('TEMP', os.getcwd()), 'CineMaster_Voices')
            os.makedirs(vdir, exist_ok=True)
            ext = os.path.splitext(path)[1].lower() or '.wav'
            dst = os.path.join(vdir, 'voice_%s_%s%s' % (core, int(time.time()), ext))
            import shutil as _sh
            _sh.copyfile(path, dst)
            self.asset_voices[core] = dst
            self._show_toast('已为人物 [%s] 设置音色：%s' % (core, os.path.basename(path)), 'success')
            self._rebuild_voice_area()
        except Exception as e:
            messagebox.showerror(APP_NAME, '音色设置失败：%s' % e)

    def _clear_asset_voice(self, core):
        """清除人物音色"""
        try:
            self.asset_voices.pop(core, None)
            self._show_toast('已清除人物 [%s] 的音色' % core, 'info')
            self._rebuild_voice_area()
        except Exception:
            pass

    def _upload_asset_image(self, core):
        """占位框上传新图 → 上传到 ComfyUI 拿 url（供视频参考图使用）→ 所有分镜中同名资产图全部替换"""
        path = filedialog.askopenfilename(title='为资产 [%s] 选择新图片' % core, filetypes=[
            ('图片文件', '*.png *.jpg *.jpeg *.webp'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            img = Image.open(path)
            img.load()
            old = self.asset_images.get(core, {})
            # 若当前媒体供应商是 ComfyUI，把本地图上传到 ComfyUI /upload/image，
            # 生成可被视频参考图链路（_refs_for_storyboard_num → video_skill 下载）访问的 url。
            # 否则 url 为空 → 视频生成时该资产图会被过滤（原 bug：上传的资产图永远用不上）。
            url = ''
            try:
                cfg = self._get_api_config()
                base = (cfg.get('media_base_url') or '').strip().rstrip('/')
                vtype = str(cfg.get('media_vendor_type') or '').strip().lower()
                vmodel = (cfg.get('vid_model') or '').strip().lower()
                if base and (vtype == 'comfyui' or vmodel.startswith('comfyui')
                             or any(k in base.lower() for k in ('8188', '15794', '8800', 'comfy'))):
                    buf = io.BytesIO()
                    img.convert('RGB').save(buf, format='PNG')
                    buf.seek(0)
                    files = {'image': ('asset_%s.png' % core, buf, 'image/png')}
                    r = requests.post(base + '/upload/image', files=files,
                                      data={'overwrite': 'true'}, timeout=60, verify=False)
                    if r.status_code == 200:
                        name = (r.json() or {}).get('name') or ''
                        if name:
                            url = base + '/view?filename=' + name.replace(' ', '%20') + '&type=input'
            except Exception:
                url = ''
            self.asset_images[core] = {'url': url, 'img': img, 'name': core,
                                       'prompt': old.get('prompt', '') or self._asset_prompt_map.get(core, ''),
                                       'type': old.get('type', '') or 'character'}
            # 关键修复：上传的图必须同步进 image_history —— _match_assets_to_storyboard
            # 完全从 image_history 重建资产池，若只更新 asset_images，下次"重新同步"
            # 会把上传的图冲掉，参考图匹配永远拿不到（原 bug：上传图从未生效）
            try:
                _replaced = False
                for _it in self.image_history:
                    if _it.get('name') and self._asset_core_name(_it.get('name')) == core:
                        _it.update({'url': url, 'img': img,
                                    'prompt': old.get('prompt', '') or self._asset_prompt_map.get(core, ''),
                                    'type': old.get('type', '') or 'character'})
                        _replaced = True
                        break
                if not _replaced:
                    self.image_history.append({'url': url, 'img': img, 'name': core,
                                               'prompt': old.get('prompt', '') or self._asset_prompt_map.get(core, ''),
                                               'type': old.get('type', '') or 'character'})
                    if len(self.image_history) > 500:
                        self.image_history.pop(0)
                # 立即重新匹配资产到分镜（上传后即刻生效，无需手动"重新同步"）
                self._match_assets_to_storyboard()
            except Exception:
                pass
            if url:
                self._show_toast('已上传新图（已同步到 ComfyUI），所有分镜中的 [%s] 已全部替换' % core, 'success')
            else:
                self._show_toast('已上传新图，但未能同步到 ComfyUI（视频参考图可能无效）', 'warning')
            self._rebuild_asset_match_area()
        except Exception as e:
            self._show_toast('加载失败: ' + str(e), 'warning')

    def _sync_asset_match(self):
        """同步资产图匹配（分镜解析 + 重建 UI），供自动/手动调用"""
        try:
            self._match_assets_to_storyboard()
            self._rebuild_asset_match_area()
            # 生成器版：同步刷新音色匹配区（生成完资产图后自动列出人物+音色按钮）
            try:
                self._rebuild_voice_area()
            except Exception:
                pass
            # 生成器版：同步刷新分镜分区的参考图缩略图
            try:
                self._sync_storyboard_prompts(silent=True)
            except Exception:
                pass
        except Exception as e:
            self.ctx.log('\n[系统日志] 资产图匹配同步异常: %s\n' % e)

    def _schedule_rematch(self):
        """防抖调度资产匹配：300ms 内多次触发合并为一次（并发生图时避免反复全量重建 UI）"""
        try:
            self.root.after_cancel(getattr(self, '_rematch_after_id', None))
        except Exception:
            pass
        try:
            self._rematch_after_id = self.root.after(300, self._sync_asset_match)
        except Exception:
            pass



    # ============ 事件泵 ============
    def _process_ui_queue(self):
        processed_count = 0
        max_process_per_loop = 20
        try:
            while processed_count < max_process_per_loop:
                event_type, edata = self.ctx.ui_queue.get_nowait()
                if event_type == 'log':
                    self._append_text('all', edata.get('text', ''))
                elif event_type == 'stream':
                    self._handle_stream(edata.get('text', ''))
                elif event_type == 'image_done':
                    self._handle_image_done(edata.get('url', ''), edata.get('name', ''),
                                            edata.get('type', ''))
                elif event_type == 'video_done':
                    self._handle_video_done(edata.get('url', ''))
                elif event_type == 'video_failed':
                    # 单个视频生成失败：递增批量计数，让批量 worker 继续下一个
                    self._story_batch_done += 1
                    self._story_batch_fail_count = getattr(self, '_story_batch_fail_count', 0) + 1
                    self._show_toast('视频生成失败: ' + str(edata.get('error', '')), 'error')
                elif event_type == 'status':
                    if 'btn_generate' in edata:
                        self.btn_generate.config(state=edata['btn_generate'])
                        # 修复：LLM 生成完毕（btn_generate 恢复 normal + text=生成完毕）但可能没输出 [ALL_DONE]
                        # （截断/中断/自动续写结束）→ 视频Tab分镜提示词列表永远不刷新。
                        # 检测"生成完毕"信号自动同步分镜提示词，不依赖 [ALL_DONE] 流标记。
                        if edata['btn_generate'] == 'normal' and edata.get('text', '') == '生成完毕':
                            self._story_gen_done = True
                            self.root.after(800, self._safe_sync_storyboard)
                    if 'btn_stop' in edata:
                        self.btn_stop.config(state=edata['btn_stop'])
                    if 'btn_gen_img' in edata:
                        self.btn_gen_img.config(state=edata['btn_gen_img'])
                        self.btn_gen_images_batch.config(state=edata['btn_gen_img'])
                        # 2026-08-21 需求2：禁用时记录时间戳，3分钟超时自动恢复（防 ComfyUI 卡死导致按钮永远灰）
                        if edata['btn_gen_img'] == 'disabled':
                            self._btn_lock_times['gen_img'] = time.time()
                        else:
                            self._btn_lock_times.pop('gen_img', None)
                    if 'btn_gen_vid' in edata:
                        self.btn_gen_vid.config(state=edata['btn_gen_vid'])
                        # 同步恢复"生成全部分镜视频"按钮（修复：原只恢复 btn_gen_vid，
                        # 批量开始禁用后若异常中断，btn_gen_sb_all 永远灰色）
                        self.btn_gen_sb_all.config(state=edata['btn_gen_vid'])
                        # 2026-08-21 需求2：记录时间戳
                        if edata['btn_gen_vid'] == 'disabled':
                            self._btn_lock_times['gen_vid'] = time.time()
                        else:
                            self._btn_lock_times.pop('gen_vid', None)
                    if edata.get('progress') == False:
                        self.progress_bar.stop()
                    if 'img_status_text' in edata:
                        self.ctx.log('\n[系统日志] ' + str(edata['img_status_text']) + '\n')
                processed_count += 1
        except queue.Empty:
            pass
        if processed_count > 0:
            self.root.update_idletasks()
        self.root.after(50, self._process_ui_queue)

    def _handle_stream(self, text):
        # 2026-08-21 标记跨 chunk 拆分修复：LLM 流式输出时 [STAGE1_DONE] 等标记可能
        # 被拆成多个 chunk（如 "[STAGE" + "1_DONE]"），单 chunk 检测会漏。
        # 累积最近文本到 _stream_marker_buf，用累积内容检测标记。
        try:
            _buf = getattr(self, '_stream_marker_buf', '') + text
            if len(_buf) > 200:
                _buf = _buf[-200:]
            self._stream_marker_buf = _buf
        except Exception:
            _buf = text
        # 2026-08-21 修复：LLM 可能混用 [ALL_DONE] 代替阶段标记（[STAGE1_DONE]/[STAGE2_DONE]）。
        # 收到 [ALL_DONE] 时，若当前处于分段评级模式（_gen_stage=1/2），把它转成当前阶段标记触发评级；
        # 仅当 _gen_stage=3（剪辑段）或非分段模式时，才当作"全部完成"。
        _gen_stage_now = getattr(self, '_gen_stage', 0) or 0
        _detect_text = _buf
        if '[ALL_DONE]' in _detect_text:
            if _gen_stage_now == 1:
                # 2026-08-21 只有剧本段（stage=1）才把 [ALL_DONE] 转 [STAGE1_DONE] 触发评级；
                # 资产段/分镜段用独立标记（ASSETS_DONE/STAGE2_DONE），残留 ALL_DONE 不触发
                _conv = '[STAGE1_DONE]'
                # 转成阶段标记：触发评级（延迟等缓冲刷新；防重复：已评级过的阶段不再触发）
                if _conv not in getattr(self, '_stage_review_done', set()):
                    self._pending_stage_after = self.root.after(
                        1500, lambda m=_conv: self._on_stage_complete(m))
                text = text.replace('[ALL_DONE]', _conv)
                self._stream_marker_buf = ''
            else:
                # 全部生成完成：延迟等缓冲刷新后自动同步分镜提示词
                self.root.after(800, self._safe_sync_storyboard)
                # 2026-08-21 续写功能：仅第三段（剪辑 [ALL_DONE]）真正完成时推进集数记录
                if _gen_stage_now == 3:
                    self.root.after(1500, self._advance_episode)
                self._stream_marker_buf = ''
        text = text.replace('[ALL_DONE]', '')
        # 2026-08-21 评级功能：检测阶段结束标记 → 触发评级（用累积 buffer 检测，防跨 chunk 拆分）
        _stage_marker = ''
        if '[ASSETS_DONE]' in _detect_text:
            _stage_marker = '[ASSETS_DONE]'
        elif '[STAGE1_DONE]' in _detect_text:
            _stage_marker = '[STAGE1_DONE]'
        elif '[STAGE2_DONE]' in _detect_text:
            _stage_marker = '[STAGE2_DONE]'
        if _stage_marker:
            # 延迟等缓冲刷新（行缓冲可能还有未刷的行），再触发评级
            if _stage_marker == '[ASSETS_DONE]':
                if _stage_marker not in getattr(self, '_stage_review_done', set()):
                    self._pending_stage_after = self.root.after(1500, lambda: self._on_assets_complete())
            else:
                # 防重复：同一阶段标记只评级一次（避免残留 chunk/回调导致二次评级）
                if _stage_marker not in getattr(self, '_stage_review_done', set()):
                    self._pending_stage_after = self.root.after(
                        1500, lambda m=_stage_marker: self._on_stage_complete(m))
            text = text.replace(_stage_marker, '')
            self._stream_marker_buf = ''
        self._append_text('all', text)
        self.line_buffer += text
        # 兜底：分镜段已完整出现（有"===== 分镜 N"且含【自检】/【画面与视听细节】）但 [ALL_DONE] 未到
        # （截断/中断）→ 也触发同步，保证视频Tab提示词列表能显示
        try:
            if not getattr(self, '_story_gen_done', False):
                _all = self.text_widgets.get('all').get('1.0', tk.END)
                if ('===== 分镜' in _all and '【自检】' in _all) or ('===== 分镜' in _all and '[ALL_DONE]' in _all):
                    self._story_gen_done = True
                    self.root.after(600, self._safe_sync_storyboard)
        except Exception:
            pass

    def _safe_sync_storyboard(self):
        try:
            if hasattr(self, 'sb_inner'):
                self._sync_storyboard_prompts(silent=True)
                self._sync_asset_match()
        except Exception as e:
            try:
                self.ctx.log('\n[系统日志] 自动同步分镜提示词异常: %s\n' % e)
            except Exception:
                pass

    def _sync_storyboard_all(self):
        """手动"重新同步"：分镜提示词列表 + 资产图匹配 一起刷新"""
        try:
            self._sync_storyboard_prompts(silent=False)
            self._sync_asset_match()
            _n = len(getattr(self, 'storyboard_prompts', []) or [])
            self._show_toast('分镜提示词与资产图匹配已同步（%d 个分镜）' % _n, 'success')
        except Exception as e:
            self._show_toast('同步失败: %s' % e, 'error')
            try:
                self.ctx.log('\n[系统日志] 手动同步分镜提示词异常: %s\n' % e)
            except Exception:
                pass

    def _append_text(self, widget_key, text):
        if widget_key not in self.text_widgets:
            return
        w = self.text_widgets[widget_key]
        w.config(state=tk.NORMAL)
        # 限制文本控件最大行数，防止长时间运行后 insert 越来越慢导致界面卡死
        try:
            if int(w.index('end-1c').split('.')[0]) > 8000:
                w.delete('1.0', '2000.0')  # 裁剪最前面的 2000 行
        except Exception:
            pass
        yview = w.yview()[1]
        w.insert(tk.END, text)
        if yview >= 0.95:
            w.see(tk.END)
        w.config(state=tk.DISABLED)

    def _flush_ui_buffer(self):
        if self.line_buffer:
            lines = self.line_buffer.split('\n')
            self.line_buffer = lines.pop()
            for line in lines:
                if '===== 角色' in line:
                    self.current_section = 'character'
                elif 'B. 剧本正文' in line:
                    self.current_section = 'script'
                elif '【场景' in line and '】' in line:
                    self.current_section = 'scene'
                elif '===== 道具资产卡' in line:
                    self.current_section = 'prop'
                # 阶段一：分镜脚本（全局规划）——LLM 输出的全局分镜规划段，单独放"全局分镜规划"选项卡
                # （修复：此前无此分支，全局规划内容被误塞进上一个 section（道具资产），污染道具资产选项卡）
                elif ('阶段一' in line and '分镜脚本' in line) or ('全局规划' in line and '分镜' in line):
                    self.current_section = 'global_plan'
                elif '===== 分镜' in line or 'F. 分镜资产' in line or '阶段二' in line:
                    self.current_section = 'storyboard'
                elif '剪映专业剪辑指导方案' in line:
                    self.current_section = 'editing'
                self._append_text(self.current_section, line + '\n')
        self.root.after(100, self._flush_ui_buffer)

    def _handle_image_done(self, url, name, atype=''):
        """图片生成完成回调（主线程调用）。下载图片移到后台线程，避免 UI 卡死。"""
        self.current_image_url = url
        # 后台线程下载图片，完成后回主线程更新 UI
        def _worker():
            try:
                headers = {'User-Agent': 'Mozilla/5.0', 'Referer': self.entry_media_base_url.get().strip()}
                img_response = requests.get(url, headers=headers, timeout=60, verify=False)
                pil_img = Image.open(io.BytesIO(img_response.content))
                pil_img.info.pop('icc_profile', None)
                self.root.after(0, lambda: self._finish_image_done(url, name, atype, pil_img))
            except Exception as e:
                self.root.after(0, lambda: self.ctx.log('\n[系统日志] 图片加载到界面失败: %s\n' % e))
        threading.Thread(target=_worker, daemon=True).start()

    def _finish_image_done(self, url, name, atype, pil_img):
        """主线程：图片下载完成后更新历史/资产匹配区（只在主线程操作 tkinter）"""
        try:
            prompt = self._asset_prompt_map.get(name, '')
            # 章节标记：批量生图时记录视频Tab章节下拉当前值；单图生成同
            chapter = getattr(self, '_gen_image_chapter', None) or (
                self.combo_vid_chapter.get() if hasattr(self, 'combo_vid_chapter') else "全部章节")
            # 双击预览后"重新生成"：替换原历史记录而不是追加新条目
            # 守卫：仅当本次完成事件来自重生成（单图占位名，或名称与目标资产一致）时才替换，
            # 避免重生成期间用户又触发其他图片生成导致错误替换
            # 中文提示词（双击预览显示用）：重生成时保留旧的中文提示词，否则取资产卡中文映射
            _prompt_cn = ''
            try:
                _prompt_cn = getattr(self, '_asset_prompt_cn_map', {}).get(name, '')
            except Exception:
                _prompt_cn = ''
            regen_idx = getattr(self, '_regen_hist_idx', None)
            regen_name = getattr(self, '_regen_asset_name', '')
            if regen_idx is not None and 0 <= regen_idx < len(self.image_history) and (
                    name == '单图' or name == regen_name):
                old = self.image_history[regen_idx]
                # 编辑重生成时保留用户编辑的提示词（_regen_prompt 优先，否则取资产卡原提示词）
                regen_prompt = getattr(self, '_regen_prompt', '') or prompt
                regen_prompt_cn = getattr(self, '_regen_prompt_cn', '') or old.get('prompt_cn', '') or _prompt_cn
                self._regen_prompt = ''
                self._regen_prompt_cn = ''
                _local = self._save_asset_image_local(pil_img, old.get('name', name), old.get('chapter', chapter))
                self.image_history[regen_idx] = {'url': url, 'img': pil_img, 'name': old.get('name', name),
                                                 'prompt': regen_prompt, 'type': old.get('type', atype),
                                                 'chapter': old.get('chapter', chapter),
                                                 'prompt_cn': regen_prompt_cn, 'local_path': _local}
                self._regen_hist_idx = None
            else:
                _local = self._save_asset_image_local(pil_img, name, chapter)
                self.image_history.append({'url': url, 'img': pil_img, 'name': name,
                                           'prompt': prompt, 'type': atype, 'chapter': chapter,
                                           'prompt_cn': _prompt_cn, 'local_path': _local})
                if len(self.image_history) > 500:
                    self.image_history.pop(0)
                    # 溢出删除首项后，选中索引整体左移
                    self._selected_hist_idx = {i - 1 for i in self._selected_hist_idx if i > 0}
            # 重新生成资产图：完成后回填到资产图匹配区域
            regen = getattr(self, '_regenerating_asset', None)
            if regen:
                self._regenerating_asset = None
                old = self.asset_images.get(regen, {})
                self.asset_images[regen] = {'url': url, 'img': pil_img,
                                            'prompt': old.get('prompt', '') or prompt,
                                            'type': old.get('type', '') or atype}
                try:
                    self._rebuild_asset_match_area()
                except Exception:
                    pass
            self._update_history_ui()
            # 新图片生成后自动重新智能匹配（保证刚生成的图立即能被分镜引用，无需手动同步）
            # 防抖：并发多图完成时合并为一次匹配+重建，避免每张图都全量重建 UI 卡顿
            self._schedule_rematch()
            self._show_toast('图片 [' + str(name) + '] 生成成功', 'success')
        except Exception as e:
            self.ctx.log('\n[系统日志] 图片更新界面失败: %s\n' % e)

    def _handle_video_done(self, url):
        self.current_video_url = url
        self.video_history.append(url)
        if len(self.video_history) > 500:
            self.video_history.pop(0)
        # 2026-08-21 需求：生成完自动下载保存到本地（videos/ 目录）
        try:
            if not hasattr(self, '_video_local_paths') or self._video_local_paths is None:
                self._video_local_paths = {}
        except Exception:
            self._video_local_paths = {}
        self._update_video_history_ui()
        self._story_batch_done += 1  # 批量生成计数（供批量 worker 等待）
        _sb_num = self._story_batch_done
        # 2026-08-21 后台下载视频到本地正式目录（videos/分镜N_时间戳.mp4）
        try:
            threading.Thread(target=self._save_video_local, args=(url, _sb_num), daemon=True).start()
        except Exception:
            pass
        # 2026-08-21 尾帧本地落盘：视频生成完成 → 后台抽最后一帧存 tail_frames/
        try:
            threading.Thread(target=self._save_video_tail_frame, args=(url, _sb_num), daemon=True).start()
        except Exception:
            pass
        # 批量生成中不逐个弹 toast（全部完成时统一提示）
        if not getattr(self, '_sb_batch_in_progress', False):
            self._show_toast('视频生成成功！已自动保存到本地，可在下方历史记录中播放或下载。', 'success')

    def _save_video_local(self, url, sb_num):
        """2026-08-21 自动下载视频到 项目目录/videos/，记录本地路径供预览/删除使用。"""
        try:
            if not url:
                return
            d = self._videos_dir()
            ts = time.strftime('%Y%m%d_%H%M%S')
            out = os.path.join(d, "分镜%d_%s.mp4" % (sb_num, ts))
            # 已存在同名分镜的最新文件则跳过重复下载（同一 URL 只存一份）
            if os.path.exists(out) and os.path.getsize(out) > 0:
                self._video_local_paths[url] = out
                return
            _resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=180, verify=False)
            _resp.raise_for_status()
            with open(out, 'wb') as _f:
                _f.write(_resp.content)
            if os.path.exists(out) and os.path.getsize(out) > 0:
                self._video_local_paths[url] = out
                # 下载完成 → 刷新列表（行内可显示本地状态）
                try:
                    self.root.after(0, self._update_video_history_ui)
                except Exception:
                    pass
                # 2026-08-21 hover 预览帧：后台 ffmpeg 抽帧（存 项目/assets/video_previews/分镜N/）
                try:
                    threading.Thread(target=self._extract_preview_frames,
                                     args=(url, out, sb_num), daemon=True).start()
                except Exception:
                    pass
            self.ctx.log('\n[系统日志] 视频已自动保存到本地: %s\n' % out)
        except Exception as e:
            self.ctx.log('\n[系统日志] 视频本地保存失败: %s\n' % e)

    def _extract_preview_frames(self, url, local_path, sb_num):
        """2026-08-21 用 ffmpeg 抽前 6 秒预览帧（固定 360x202，pad 黑边），存 PNG 供 hover 秒开预览。
        替代 opencv：无解码延迟、无临时缓存冗余。"""
        try:
            if not url or not local_path or not os.path.exists(local_path):
                return
            import imageio_ffmpeg
            import subprocess as _sp
            import glob
            _ff = imageio_ffmpeg.get_ffmpeg_exe()
            _previews = os.path.join(self._preview_frames_dir(), "分镜%d" % sb_num)
            os.makedirs(_previews, exist_ok=True)
            # 清掉旧帧（重新生成时覆盖）
            for _old in glob.glob(os.path.join(_previews, 'f_*.png')):
                try:
                    os.remove(_old)
                except Exception:
                    pass
            # 前 6 秒 @ 4fps = 24 帧，固定 360x202（16:9，pad 黑边）→ 窗口不跳动
            _vf = 'fps=4,scale=360:202:force_original_aspect_ratio=decrease,pad=360:202:(ow-iw)/2:(oh-ih)/2:black'
            _r = _sp.run([_ff, '-y', '-i', local_path, '-t', '6', '-vf', _vf,
                          os.path.join(_previews, 'f_%03d.png')],
                         capture_output=True, timeout=90)
            _files = sorted(glob.glob(os.path.join(_previews, 'f_*.png')))
            if _files:
                self._video_preview_frames[url] = _previews
                # 若鼠标仍悬停 → 立即播放（帧已就绪）
                if getattr(self, '_preview_hover_active', False):
                    self.root.after(0, lambda: self._play_preview_frames(_previews))
                self.ctx.log('\n[系统日志] 视频预览帧已生成: %s (%d 帧)\n' % (_previews, len(_files)))
        except Exception as e:
            self.ctx.log('\n[系统日志] 视频预览帧生成失败: %s\n' % e)

    def _save_video_tail_frame(self, url, sb_num):
        """2026-08-21 下载视频并提取最后一帧，保存到 项目目录/assets/tail_frames/分镜N.png。"""
        try:
            if not url:
                return
            import subprocess as _sp
            # 2026-08-21 优先用已自动保存的本地视频（避免重复下载）
            _local_vid = ''
            try:
                # 等待本地保存线程完成（最多 15 秒），避免两个线程重复下载同一 URL
                for _w in range(15):
                    _local_vid = (getattr(self, '_video_local_paths', {}) or {}).get(url, '')
                    if _local_vid and os.path.exists(_local_vid):
                        break
                    if _w < 14:
                        time.sleep(1)
                if _local_vid and not os.path.exists(_local_vid):
                    _local_vid = ''
            except Exception:
                _local_vid = ''
            if _local_vid:
                _tmp = _local_vid
            else:
                _tmp = os.path.join(os.environ.get('TEMP', '.'), 'wave_tail_%d.mp4' % int(time.time()))
                _resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120, verify=False)
                _resp.raise_for_status()
                with open(_tmp, 'wb') as _f:
                    _f.write(_resp.content)
            _out = os.path.join(self._tail_frames_dir(), "分镜%d.png" % sb_num)
            _done = False
            for _ff in ('ffmpeg', r'C:\ffmpeg\bin\ffmpeg.exe', r'D:\ffmpeg\bin\ffmpeg.exe'):
                try:
                    _r = _sp.run([_ff, '-y', '-i', _tmp, '-vf', 'select=eq(n\\,N)', '-vframes', '1', _out],
                                 capture_output=True, timeout=120)
                    if _r.returncode == 0 and os.path.exists(_out) and os.path.getsize(_out) > 1000:
                        _done = True
                        break
                except Exception:
                    continue
            if not _done:
                try:
                    from PIL import ImageSequence
                    _im = Image.open(_tmp)
                    _last = None
                    for _fr in ImageSequence.Iterator(_im):
                        _last = _fr.copy()
                    if _last is not None:
                        _last.convert('RGB').save(_out, 'PNG')
                        _done = True
                except Exception:
                    pass
            if _done:
                self.ctx.log("[系统日志] 分镜%d 尾帧已保存到本地: %s\n" % (sb_num, _out))
            # 仅清理临时下载（本地正式文件不删）
            try:
                if not _local_vid and os.path.exists(_tmp):
                    os.remove(_tmp)
            except Exception:
                pass
        except Exception:
            pass

    # ============ 开始/停止 ============
    def _on_generate_click(self):
        # 按章节生成：章节下拉选了具体章节 → 用该章正文；"全部章节"→ 全文
        novel = self._current_chapter_text()
        if not novel:
            self._show_toast('请输入小说文本', 'warning')
            return
        # ============ 2026-08-21 续写下一集模式 ============
        # 勾选「续写下一集」→ 检测第 N 集资产已生成 → 自动开始第 N+1 集生成。
        # 必须在本函数清空 text_widgets 之前检测（要用上一集剧本结尾作续写上下文）。
        _continue_mode = bool(getattr(self, '_continue_var', None) and self._continue_var.get())
        self._continue_episode_target = 0  # 非续写=0；续写时=目标集数
        self._continue_prev_tail = ''      # 上一集剧本结尾（续写上下文）
        if _continue_mode:
            _secs = (self.current_project or {}).get('sections', {}) or {}
            _prev_script = ''
            try:
                _w = self.text_widgets.get('script')
                if _w is not None:
                    _prev_script = _w.get('1.0', tk.END).strip()
                if not _prev_script:
                    _prev_script = str(_secs.get('script') or '').strip()
            except Exception:
                _prev_script = str(_secs.get('script') or '').strip()
            # 检测上一集资产是否已生成（角色/场景/道具任一非空即视为已生成）
            _assets_done = any(
                ((_secs.get(k) or '').strip() or
                 (self.text_widgets.get(k).get('1.0', tk.END).strip() if self.text_widgets.get(k) else ''))
                for k in ('character', 'scene', 'prop'))
            if not _assets_done:
                self._show_toast('⚠️ 未检测到已生成的资产（角色/场景/道具），无法续写。\n'
                                 '请先完成第 1 集的全链路生成，再勾选「续写下一集」。', 'warning')
                return
            _ep = int((self.current_project or {}).get('episode', 0) or 0)
            _episode_target = (_ep if _ep >= 1 else 1) + 1  # 资产存在 → 至少完成过第1集
            self._continue_episode_target = _episode_target
            # 提取上一集剧本正文结尾（800字）作为续写锚点
            if _prev_script:
                try:
                    _m = re.search(r'----- B\. 剧本正文 -----(.*)', _prev_script, re.S)
                    _body = _m.group(1).strip() if _m else _prev_script
                    self._continue_prev_tail = _body[-800:]
                except Exception:
                    self._continue_prev_tail = _prev_script[-800:]
            self.ctx.log('[系统日志] ⏭ 续写模式：检测到第 %d 集资产已生成，本次自动生成第 %d 集（从上一集结尾继续）\n'
                         % (_episode_target - 1, _episode_target))
        self.ctx.stop_flag = False
        self.line_buffer = ''
        self.current_section = 'script'
        self._story_gen_done = False  # 重置转化完成标记（新一轮生成重新检测）
        # 开始新转化时清空分镜提示词列表（生成完成后自动同步）
        self.storyboard_prompts = []
        self.story_prompt_vars = []
        self.story_prompt_texts = []
        try:
            self._rebuild_empty_sb_list()
        except Exception:
            pass
        for w in self.text_widgets.values():
            w.config(state=tk.NORMAL)
            w.delete('1.0', tk.END)
            w.config(state=tk.DISABLED)
        self.btn_generate.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.progress_bar.start()
        self.notebook_out.select(0)
        self.label_gen_time.config(text='本次生成耗时：计时中...')
        # 附加指令：优先使用已上传的指令（点过「▲ 上传指令」的），否则用输入框当前内容
        command_text = getattr(self, 'uploaded_command', None)
        if command_text is None:
            command_text = self.text_input_command.get('1.0', tk.END).strip()
        # Toonflow 导演技法注入：视觉连续性铁律 + 选中的题材导演手法
        genre = getattr(self, '_genre_var', None)
        genre_name = genre.get() if genre else '通用'
        system_prompt = SYSTEM_PROMPT
        if GENRE_DIRECTOR_SKILLS:
            extra = '\n# Toonflow 导演技法（集成增强）\n' + DIRECTOR_CONTINUITY_RULES + '\n'
            if genre_name in GENRE_DIRECTOR_SKILLS:
                extra += ('\n## 当前题材【%s】导演手法（必须遵守）\n%s\n'
                          % (genre_name, GENRE_DIRECTOR_SKILLS[genre_name]))
            else:
                extra += '\n## 题材自适配：请依据小说内容自动判断题材，并套用该题材成熟的导演分镜手法（景别递进、运镜节奏、时长把控、镜头合并、人物互动设计、台词留白、转场设计）。\n'
            system_prompt = system_prompt.rstrip() + '\n' + extra
        # 全局风格注入：用户选择风格后，所有提示词（剧本/资产/分镜）统一遵循该风格
        try:
            _style_name = self.combo_global_style.get() if hasattr(self, 'combo_global_style') else DEFAULT_VIDEO_STYLE
            _style_zh = (VIDEO_STYLE_PRESETS.get(_style_name) or {}).get('zh', '')
            if _style_zh:
                _style_inst = ('\n# 全局视觉风格（必须遵守，贯穿所有提示词）\n'
                               '本项目的统一视觉风格为：%s。\n'
                               '所有角色/场景/道具/分镜的【中文AI提示词】与【英文AI提示词】必须严格遵循此风格。\n'
                               '若风格为写实类：角色形象必须为真实人类写真（真实皮肤质感、真实五官比例、自然发丝、真实光照），严禁卡通化/动漫化/插画化/美漫化；场景与道具为真实照片质感。\n'
                               '若风格为动漫/卡通类：角色形象统一为动漫插画风，严禁写实照片风。\n'
                               '风格描述必须体现在每个提示词的开头与画质尾缀中。' % _style_zh)
                system_prompt = system_prompt.rstrip() + _style_inst
            # 同步视频Tab的风格只读标签
            try:
                if hasattr(self, 'label_vid_style'):
                    self.label_vid_style.config(text=_style_name)
            except Exception:
                pass
        except Exception:
            pass
        # 人物地域注入：项目选择的中国/海外 → 所有角色/分镜提示词统一人种特征
        try:
            _eth = ethnicity_guide((self.current_project or {}).get('ethnicity', '') or '中国')
            if _eth:
                _eth_inst = ('\n# 人物地域特征（必须遵守，贯穿所有角色与分镜提示词）\n'
                             '本项目所有【角色资产】与【分镜】的人物形象必须符合：%s。\n'
                             '角色描述（面容/发型/肤色/服装风格）必须与该地域特征一致，严禁混入其他地域人种特征。' % _eth)
                system_prompt = system_prompt.rstrip() + _eth_inst
        except Exception:
            pass
        # 2026-08-13 按需求创作模式：注入创作指令——LLM 根据用户需求自创剧本正文，
        # 再继续人物/场景/道具/分镜全链路（不依赖用户提供小说原文）
        create_mode = bool(getattr(self, '_create_mode_var', None) and self._create_mode_var.get())
        if create_mode:
            create_inst = (
                '\n# 创作模式（当前用户未提供小说，按需求创作）\n'
                '【最重要】用户输入的内容是【创作需求】而非小说原文！你必须：\n'
                '1. 深度理解用户的创作需求（题材/风格/人物/情节/氛围等所有要求），红果短剧风格即竖屏短剧：强冲突、快节奏、'
                '每集结尾留钩子、台词口语化短促、情节密度高。\n'
                '2. 先自行创作符合需求的完整小说原文（作为本集的底本，约1.5-2倍剧本字数，包含人物、场景、冲突、对话），'
                '创作时严格遵守用户需求中的所有限定，不得偏离。\n'
                '3. 然后按原有全链路流程继续：基于你创作的小说原文，输出【剧本信息】【A. 剧本基础角色资产】【B. 剧本正文】'
                '（第1集，按时长截取）、【C. 角色资产】【D. 场景资产】【E. 道具资产】、分镜【F】、剪辑方案【G】。\n'
                '4. 资产硬清单校验铁律照常执行（以你创作的剧本正文为硬清单）。\n'
                '5. 遵守三段式分段输出：本段（剧本）只输出【剧本信息】【A. 剧本基础角色资产】【B. 剧本正文】'
                '（含你创作的底本内容），末尾输出 [STAGE1_DONE]；后续资产/分镜/剪辑按软件指令分段输出。\n')
            system_prompt = system_prompt.rstrip() + create_inst
        # 2026-08-21 续写下一集：注入集数替换 + 续写指令（在导演/风格/地域/创作模式注入之后统一处理）
        if _continue_mode:
            _ep_t = self._continue_episode_target or 2
            # 1) SP 中写死的集数动态化
            system_prompt = system_prompt.replace('第1集', '第%d集' % _ep_t)
            system_prompt = system_prompt.replace('是否继续生成第2集？', '是否继续生成第%d集？' % (_ep_t + 1))
            system_prompt = system_prompt.replace(
                '从小说开头推进剧情',
                '从上一集（第%d集）剧情结束处继续推进剧情，严禁从头开始、严禁重复或改写上一集已生成内容'
                % (_ep_t - 1))
            # 2) 注入续写模式规则（最高优先级，位于 SP 末尾）
            _cont_inst = (
                '\n# 续写模式（本次为第%d集自动续写）\n'
                '本次生成是【第%d集】的续写，上一集（第%d集）的剧本/资产/分镜已生成完毕。必须遵守：\n'
                '1. 【B. 剧本正文】必须从上一集剧情结束处（见用户消息【续写上下文】）自然衔接继续推进，'
                '严禁从头开始、严禁重复或改写上一集已生成内容；全局理解仍通读整本小说，'
                '但本集只截取上一集之后的新剧情（同样遵守单集时长上限）。\n'
                '2. 资产生成（C/D/E）唯一来源=本集【B. 剧本正文】；与上一集相同的人物/场景/道具'
                '（如主角、常驻场景）仍须生成本集对应的完整资产卡（保证本集资产可独立使用），'
                '严禁从小说全文提取本集未涉及的新增资产。\n'
                '3. 分镜与剪辑照常按本集内容生成，分镜衔接以上一集结尾状态为起点。\n'
                '4. 所有阶段标记（[STAGE1_DONE]/[ASSETS_DONE]/[STAGE2_DONE]/[ALL_DONE]）照常输出。'
                % (_ep_t, _ep_t, _ep_t - 1))
            system_prompt = system_prompt.rstrip() + _cont_inst
            # 3) 上一集剧本结尾注入附加指令（贯穿所有阶段：_gen_command_text 被各阶段复用）
            _prev_tail = getattr(self, '_continue_prev_tail', '') or ''
            if _prev_tail:
                _ctx = ('\n\n【续写上下文】上一集（第%d集）剧本结尾（本集必须从这里继续，严禁从头开始）：\n%s'
                        % (_ep_t - 1, _prev_tail))
                command_text = (command_text or '') + _ctx
        # 2026-08-21 评级功能：初始化为阶段①（剧本），stop_marker=[STAGE1_DONE]
        self._gen_stage = 1
        self._gen_novel_text = novel
        self._gen_command_text = command_text
        self._gen_system_prompt = system_prompt
        self._gen_review_text = ''  # 上一轮评级意见（重新生成时携带）
        # 2026-08-21 防重复评级：新生成重置阶段标记记录与挂起回调
        try:
            self._stage_review_done = set()
            if getattr(self, '_pending_stage_after', None) is not None:
                try:
                    self.root.after_cancel(self._pending_stage_after)
                except Exception:
                    pass
                self._pending_stage_after = None
        except Exception:
            pass
        self.agent.generate_storyboard(novel,
                                       command_text,
                                       self._get_api_config(), system_prompt,
                                       stop_marker='[STAGE1_DONE]',
                                       extra_context='')


    # ============ 2026-08-21 分段评级（Toonflow 机制：生成→评级→用户确认→下一步）============
    def _on_stage_complete(self, marker):
        """阶段生成完成标记触发：STAGE1=剧本评级；STAGE2=分镜评级"""
        try:
            # 2026-08-21 防重复：清空挂起回调，标记该阶段已评级
            try:
                if getattr(self, '_pending_stage_after', None) is not None:
                    self.root.after_cancel(self._pending_stage_after)
                    self._pending_stage_after = None
            except Exception:
                pass
            try:
                self._stage_review_done.add(marker)
            except Exception:
                pass
            # 生成线程已结束，先确保按钮状态正确（btn_generate 保持可用）
            self.progress_bar.stop()
            self.btn_stop.config(state=tk.DISABLED)
            if marker == '[STAGE1_DONE]':
                self._gen_stage = 1
                self._trigger_review('script')
            elif marker == '[STAGE2_DONE]':
                self._gen_stage = 2
                self._trigger_review('storyboard')
        except Exception as e:
            self.ctx.log('\n[系统日志] 阶段完成处理异常: %s\n' % e)
            # 2026-08-21 兜底：即使评级链路异常，也要弹出评级窗口（带错误信息），
            # 保证用户一定能看到"需要确认"的界面，绝不静默卡住
            try:
                _rt = 'script' if marker == '[STAGE1_DONE]' else 'storyboard'
                self._show_review_dialog(_rt, None)
            except Exception:
                pass

    def _trigger_review(self, review_type):
        """触发监督层评级：先弹"评级中"窗口（立即反馈），后台线程调用 LLM 评级完成后填充结果"""
        self.label_gen_time.config(text='正在评级 ' + ('剧本' if review_type == 'script' else '分镜') + ' ...')
        self.ctx.log('\n[系统日志] 正在评级%s...\n' % ('剧本' if review_type == 'script' else '分镜'))
        # 2026-08-21 先弹出"评级中"窗口，避免用户以为卡死无反馈
        _win = self._show_review_loading(review_type)

        def _worker():
            try:
                api_config = self._get_api_config()
                # 收集当前阶段产出文本
                if review_type == 'script':
                    _content = ''
                    try:
                        _content += (self.text_widgets.get('script').get('1.0', tk.END) or '')
                    except Exception:
                        pass
                    _dims = REVIEW_SCRIPT_DIMENSIONS
                else:
                    # 2026-08-21 修复：原逻辑按 character→scene→prop→global_plan→storyboard 顺序拼接后
                    # 整体 [:8000]——C/D/E 资产卡把 8000 字额度占满，分镜内容全被截掉 → 评级报告误报
                    # "分镜完全缺失"。改为分段组织：分镜（global_plan+storyboard）完整优先传入，
                    # C/D/E 资产卡截断放后面作辅助分析（帮助评级校验"资产调用一致"维度）。
                    _sb_content = ''
                    for _k in ('global_plan', 'storyboard'):
                        try:
                            _sb_content += (self.text_widgets.get(_k).get('1.0', tk.END) or '') + '\n'
                        except Exception:
                            pass
                    _assets_content = ''
                    for _k in ('character', 'scene', 'prop'):
                        try:
                            _assets_content += (self.text_widgets.get(_k).get('1.0', tk.END) or '') + '\n'
                        except Exception:
                            pass
                    # 分镜内容优先且保证完整（最多 12000 字），资产卡截断（最多 6000 字）作辅助
                    _content = ('【分镜全局规划 + F 段分镜资产】\n' + (_sb_content[:12000] if _sb_content.strip() else '（无分镜内容！）') +
                                '\n\n【C/D/E 资产卡（辅助分析用，供校验分镜资产调用一致性）】\n' +
                                (_assets_content[:6000] if _assets_content.strip() else '（无资产内容）'))
                    _dims = REVIEW_STORYBOARD_DIMENSIONS
                _prompt = (_dims + '\n\n【产出物】\n' +
                           _content +
                           '\n\n请按上述审核维度输出审核报告，评分 A/B/C/D，列出问题清单。')
                _report = self.agent.review_output(api_config, _prompt, REVIEW_SYSTEM_PROMPT)
                self.root.after(0, lambda: self._fill_review_dialog(_win, review_type, _report))
            except Exception as e:
                self.ctx.log('\n[系统日志] 评级异常: %s\n' % e)
                self.root.after(0, lambda: self._fill_review_dialog(_win, review_type, None))
        threading.Thread(target=_worker, daemon=True).start()

    def _show_review_loading(self, review_type):
        """先弹"评级中"窗口（loading 态），评级完成后由 _fill_review_dialog 填充"""
        _name = '剧本' if review_type == 'script' else '分镜（全局规划+分镜资产）'
        win = tk.Toplevel(self.root)
        win.title('评级：%s' % _name)
        win.configure(bg='#FFFFFF')
        win.geometry('720x560')
        win.transient(self.root)
        win.grab_set()
        head = tk.Frame(win, bg='#FFFFFF')
        head.pack(fill='x', padx=16, pady=(14, 4))
        tk.Label(head, text='评级报告 · %s' % _name, font=('微软雅黑', 13, 'bold'),
                 bg='#FFFFFF', fg='#2C3E50').pack(anchor='w')
        # loading 提示
        _load = tk.Frame(win, bg='#FFFFFF')
        _load.pack(fill='both', expand=True, padx=16, pady=10)
        tk.Label(_load, text='⏳ 正在评级中，请稍候...（正在调用 AI 评审专家审核本阶段产出物）',
                 font=('微软雅黑', 12), bg='#FFFFFF', fg='#7F8C8D').pack(pady=30)
        # 报告文本（先空，评级完成后填充）
        txt = scrolledtext.ScrolledText(win, font=('微软雅黑', 10), wrap='word',
                                        bg='#FBFCFC', fg='#2C3E50', relief='solid', bd=1)
        txt.pack(fill='both', expand=True, padx=16, pady=10)
        txt.config(state=tk.DISABLED)
        win._review_txt = txt
        win.update_idletasks()
        try:
            _x = self.root.winfo_x() + max(0, (self.root.winfo_width() - 720) // 2)
            _y = self.root.winfo_y() + max(0, (self.root.winfo_height() - 560) // 2)
            win.geometry('+%d+%d' % (_x, _y))
        except Exception:
            pass
        return win

    def _fill_review_dialog(self, win, review_type, report):
        """评级完成后填充结果到已弹出的窗口"""
        try:
            if win is None or not win.winfo_exists():
                # 窗口已关闭（用户可能取消了）→ 用原逻辑重建
                self._show_review_dialog(review_type, report)
                return
            self.label_gen_time.config(text='评级完成')
            self.btn_generate.config(state=tk.NORMAL)
            _name = '剧本' if review_type == 'script' else '分镜（全局规划+分镜资产）'
            _grade = ''
            if report:
                import re as _re3
                _m = _re3.search(r'[（(]?\s*[**]?\s*评分\s*[：:]\s*[\[（(]?\s*([ABCD])\s*[\]）)]?', report)
                if not _m:
                    _m = _re3.search(r'\*\*评分\*\*\s*[：:]\s*([ABCD])', report)
                if _m:
                    _grade = _m.group(1)
            _grade_txt = _grade if _grade else '?'
            _color = {'A': '#27AE60', 'B': '#2E86C1', 'C': '#E67E22', 'D': '#E74C3C'}.get(_grade, '#7F8C8D')
            # 更新标题
            win.title('评级：%s' % _name)
            # 填充报告文本
            _txt = getattr(win, '_review_txt', None)
            if _txt is not None:
                _txt.config(state=tk.NORMAL)
                _txt.delete('1.0', tk.END)
                _txt.insert(tk.END, report if report else '（评级失败：无法获取评级报告，请检查 API 配置或网络）')
                _txt.config(state=tk.DISABLED)
            # 评分显示（重新构建顶部区：先清 loading，再加评分+按钮）
            for _w in win.winfo_children():
                try:
                    _w.destroy()
                except Exception:
                    pass
            head = tk.Frame(win, bg='#FFFFFF')
            head.pack(fill='x', padx=16, pady=(14, 4))
            tk.Label(head, text='评级报告 · %s' % _name, font=('微软雅黑', 13, 'bold'),
                     bg='#FFFFFF', fg='#2C3E50').pack(anchor='w')
            grade_row = tk.Frame(win, bg='#FFFFFF')
            grade_row.pack(fill='x', padx=16, pady=4)
            tk.Label(grade_row, text='综合评分：', font=('微软雅黑', 11), bg='#FFFFFF',
                     fg='#34495E').pack(side='left')
            tk.Label(grade_row, text=_grade_txt, font=('微软雅黑', 24, 'bold'),
                     bg='#FFFFFF', fg=_color).pack(side='left', padx=(8, 0))
            _grade_desc = {'A': '可直接使用', 'B': '小修后可用', 'C': '需较大修改', 'D': '建议重做'}.get(_grade, '')
            if _grade_desc:
                tk.Label(grade_row, text=_grade_desc, font=('微软雅黑', 11),
                         bg='#FFFFFF', fg=_color).pack(side='left', padx=(10, 0))
            txt = scrolledtext.ScrolledText(win, font=('微软雅黑', 10), wrap='word',
                                            bg='#FBFCFC', fg='#2C3E50', relief='solid', bd=1)
            txt.pack(fill='both', expand=True, padx=16, pady=(10, 4))
            txt.insert(tk.END, report if report else '（评级失败：无法获取评级报告，请检查 API 配置或网络）')
            txt.config(state=tk.DISABLED)
            # ===== 2026-08-21 用户指令输入区（输入修改诉求 → 上传给程序）=====
            _inp_frame = tk.Frame(win, bg='#FFFFFF')
            _inp_frame.pack(fill='x', padx=16, pady=(2, 6))
            tk.Label(_inp_frame, text='📝 你的指令/修改诉求：', font=('微软雅黑', 10, 'bold'),
                     bg='#FFFFFF', fg='#2C3E50').pack(anchor='w')
            _inp_hint = tk.Label(_inp_frame, text='（例：台词太书面，改成口语；节奏太慢加快；直接通过）',
                                 font=('微软雅黑', 8), bg='#FFFFFF', fg='#95A5A6')
            _inp_hint.pack(anchor='w')
            _entry = tk.Text(_inp_frame, font=('微软雅黑', 10), height=2, wrap='word',
                             bg='#FEFEFE', fg='#2C3E50', relief='solid', bd=1)
            _entry.pack(fill='x', pady=(4, 6))
            win._review_entry = _entry
            btns = tk.Frame(win, bg='#FFFFFF')
            btns.pack(fill='x', padx=16, pady=(0, 14))
            _regen_txt = ('🔄 重新生成' + ('（当前评级建议重做）' if _grade == 'D' else ''))
            b_regen = tk.Button(btns, text=_regen_txt, font=('微软雅黑', 11),
                                bg='#E74C3C', fg='white', relief='flat', padx=18, pady=6,
                                command=lambda: self._on_review_regen(review_type, report, win))
            b_regen.pack(side='right', padx=(10, 0))
            # 2026-08-21 上传指令按钮：把用户输入框内容作为修改指令 → 重新生成
            b_send = tk.Button(btns, text='📤 上传指令', font=('微软雅黑', 11),
                               bg='#F39C12', fg='white', relief='flat', padx=18, pady=6,
                               command=lambda: self._on_review_send(review_type, report, win))
            b_send.pack(side='right', padx=(10, 0))
            b_pass = tk.Button(btns, text='✅ 确认通过，继续下一步', font=('微软雅黑', 11),
                               bg='#27AE60', fg='white', relief='flat', padx=18, pady=6,
                               command=lambda: self._on_review_pass(review_type, win))
            b_pass.pack(side='right')
            # 窗口加高，确保按钮和输入框可见
            try:
                win.geometry('720x680')
                _x = self.root.winfo_x() + max(0, (self.root.winfo_width() - 720) // 2)
                _y = self.root.winfo_y() + max(0, (self.root.winfo_height() - 680) // 2)
                win.geometry('+%d+%d' % (_x, _y))
            except Exception:
                pass
            win.update_idletasks()
        except Exception as e:
            self.ctx.log('\n[系统日志] 评级结果填充异常: %s\n' % e)
            try:
                self._show_review_dialog(review_type, report)
            except Exception:
                pass

    def _show_review_dialog(self, review_type, report):
        """评级结果弹窗：评分 + 问题清单 + 通过/重新生成"""
        self.label_gen_time.config(text='评级完成')
        self.btn_generate.config(state=tk.NORMAL)
        _name = '剧本' if review_type == 'script' else '分镜（全局规划+分镜资产）'
        _grade = ''
        if report:
            import re as _re3
            # 宽松匹配：评分：A / **评分**：B / 评分: C / 评分 [D] / （评分：A） 等
            _m = _re3.search(r'[（(]?\s*[**]?\s*评分\s*[：:]\s*[\[（(]?\s*([ABCD])\s*[\]）)]?', report)
            if not _m:
                _m = _re3.search(r'\*\*评分\*\*\s*[：:]\s*([ABCD])', report)
            if _m:
                _grade = _m.group(1)
        _grade_txt = _grade if _grade else '?'
        _color = {'A': '#27AE60', 'B': '#2E86C1', 'C': '#E67E22', 'D': '#E74C3C'}.get(_grade, '#7F8C8D')

        win = tk.Toplevel(self.root)
        win.title('评级：%s' % _name)
        win.configure(bg='#FFFFFF')
        win.geometry('720x560')
        win.transient(self.root)
        win.grab_set()
        # 顶部：评分大字
        head = tk.Frame(win, bg='#FFFFFF')
        head.pack(fill='x', padx=16, pady=(14, 4))
        tk.Label(head, text='评级报告 · %s' % _name, font=('微软雅黑', 13, 'bold'),
                 bg='#FFFFFF', fg='#2C3E50').pack(anchor='w')
        grade_row = tk.Frame(win, bg='#FFFFFF')
        grade_row.pack(fill='x', padx=16, pady=4)
        tk.Label(grade_row, text='综合评分：', font=('微软雅黑', 11), bg='#FFFFFF',
                 fg='#34495E').pack(side='left')
        tk.Label(grade_row, text=_grade_txt, font=('微软雅黑', 24, 'bold'),
                 bg='#FFFFFF', fg=_color).pack(side='left', padx=(8, 0))
        _grade_desc = {'A': '可直接使用', 'B': '小修后可用', 'C': '需较大修改', 'D': '建议重做'}.get(_grade, '')
        if _grade_desc:
            tk.Label(grade_row, text=_grade_desc, font=('微软雅黑', 11),
                     bg='#FFFFFF', fg=_color).pack(side='left', padx=(10, 0))
        # 报告文本
        txt = scrolledtext.ScrolledText(win, font=('微软雅黑', 10), wrap='word',
                                        bg='#FBFCFC', fg='#2C3E50', relief='solid', bd=1)
        txt.pack(fill='both', expand=True, padx=16, pady=(10, 4))
        txt.insert(tk.END, report if report else '（评级失败：无法获取评级报告，请检查 API 配置或网络）')
        txt.config(state=tk.DISABLED)
        # ===== 2026-08-21 用户指令输入区（输入修改诉求 → 上传给程序）=====
        _inp_frame = tk.Frame(win, bg='#FFFFFF')
        _inp_frame.pack(fill='x', padx=16, pady=(2, 6))
        tk.Label(_inp_frame, text='📝 你的指令/修改诉求：', font=('微软雅黑', 10, 'bold'),
                 bg='#FFFFFF', fg='#2C3E50').pack(anchor='w')
        _inp_hint = tk.Label(_inp_frame, text='（例：台词太书面，改成口语；节奏太慢加快；直接通过）',
                             font=('微软雅黑', 8), bg='#FFFFFF', fg='#95A5A6')
        _inp_hint.pack(anchor='w')
        _entry = tk.Text(_inp_frame, font=('微软雅黑', 10), height=2, wrap='word',
                         bg='#FEFEFE', fg='#2C3E50', relief='solid', bd=1)
        _entry.pack(fill='x', pady=(4, 6))
        # 2026-08-21 预填主界面"附加指令"输入框的内容（用户在主界面写的诉求自动带过来）
        try:
            _main_cmd = self.text_input_command.get('1.0', tk.END).strip()
            if _main_cmd:
                _entry.insert('1.0', _main_cmd)
        except Exception:
            pass
        win._review_entry = _entry
        # 按钮
        btns = tk.Frame(win, bg='#FFFFFF')
        btns.pack(fill='x', padx=16, pady=(0, 14))
        _regen_txt = ('🔄 重新生成' + ('（当前评级建议重做）' if _grade == 'D' else ''))
        b_regen = tk.Button(btns, text=_regen_txt, font=('微软雅黑', 11),
                            bg='#E74C3C', fg='white', relief='flat', padx=18, pady=6,
                            command=lambda: self._on_review_regen(review_type, report, win))
        b_regen.pack(side='right', padx=(10, 0))
        # 2026-08-21 上传指令按钮：把用户输入框内容作为修改指令 → 重新生成
        b_send = tk.Button(btns, text='📤 上传指令', font=('微软雅黑', 11),
                           bg='#F39C12', fg='white', relief='flat', padx=18, pady=6,
                           command=lambda: self._on_review_send(review_type, report, win))
        b_send.pack(side='right', padx=(10, 0))
        b_pass = tk.Button(btns, text='✅ 确认通过，继续下一步', font=('微软雅黑', 11),
                           bg='#27AE60', fg='white', relief='flat', padx=18, pady=6,
                           command=lambda: self._on_review_pass(review_type, win))
        b_pass.pack(side='right')
        win.update_idletasks()
        # 窗口加高 + 居中（确保按钮和输入框可见）
        try:
            win.geometry('720x680')
            _x = self.root.winfo_x() + max(0, (self.root.winfo_width() - 720) // 2)
            _y = self.root.winfo_y() + max(0, (self.root.winfo_height() - 680) // 2)
            win.geometry('+%d+%d' % (_x, _y))
        except Exception:
            pass

    def _on_review_pass(self, review_type, win):
        """用户确认通过 → 进入下一阶段"""
        try:
            win.destroy()
        except Exception:
            pass
        # 2026-08-21 防重复：取消所有挂起的阶段回调，标记当前阶段已确认
        try:
            if getattr(self, '_pending_stage_after', None) is not None:
                self.root.after_cancel(self._pending_stage_after)
                self._pending_stage_after = None
        except Exception:
            pass
        if review_type == 'script':
            # 阶段①通过 → 阶段②（资产清单）
            self._stage_review_done.add('[STAGE1_DONE]')
            self._gen_review_text = ''
            self._run_stage2()
        elif review_type == 'storyboard':
            # 阶段②通过 → 阶段③（剪辑方案）
            self._stage_review_done.add('[STAGE2_DONE]')
            self._gen_review_text = ''
            self._run_stage3()

    def _on_review_regen(self, review_type, report, win):
        """用户选择重新生成 → 携带评级意见重跑当前阶段"""
        try:
            win.destroy()
        except Exception:
            pass
        # 携带评级报告作为重生成指令
        self._gen_review_text = report or ''
        if review_type == 'script':
            self._run_stage1(regen=True)
        elif review_type == 'storyboard':
            # 2026-08-21 分镜评级不通过 → 重跑分镜段（②B），资产保留不重跑
            self._run_stage2b(regen=True)

    def _on_review_send(self, review_type, report, win):
        """2026-08-21 上传指令：读取评级窗输入框内容作为用户修改诉求 → 连同评级意见一起重新生成"""
        _user_cmd = ''
        try:
            _entry = getattr(win, '_review_entry', None)
            if _entry is not None:
                _user_cmd = _entry.get('1.0', tk.END).strip()
        except Exception:
            _user_cmd = ''
        if not _user_cmd:
            self._show_toast('请先在输入框填写你的修改指令（如：台词再口语化 / 节奏加快 / 直接通过）', 'warning')
            return
        try:
            win.destroy()
        except Exception:
            pass
        # 用户指令 + 评级意见 一起作为重生成指令
        _combined = ''
        if report:
            _combined = ('【你的修改要求】\n' + _user_cmd +
                         '\n\n【AI 评级意见（供参考）】\n' + report[:3000])
        else:
            _combined = '【你的修改要求】\n' + _user_cmd
        self._gen_review_text = _combined
        self.ctx.log('\n[系统日志] 已收到你的指令：%s\n' % _user_cmd[:100])
        if review_type == 'script':
            self._run_stage1(regen=True)
        elif review_type == 'storyboard':
            # 2026-08-21 分镜指令重生成 → 重跑分镜段（②B），资产保留
            self._run_stage2b(regen=True)

    def _run_stage1(self, regen=False):
        """阶段①：剧本生成（A基础角色+B剧本正文）→ [STAGE1_DONE]"""
        try:
            self.ctx.stop_flag = False
            self.btn_generate.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.progress_bar.start()
            self._gen_stage = 1
            # 2026-08-21 重新生成时清空对应阶段 tab（避免内容追加到旧文本后）
            if regen:
                # 允许重新评级
                try:
                    self._stage_review_done.discard('[STAGE1_DONE]')
                except Exception:
                    pass
                for _k in ('all', 'script'):
                    try:
                        _w = self.text_widgets.get(_k)
                        if _w is not None:
                            _w.config(state=tk.NORMAL)
                            _w.delete('1.0', tk.END)
                            _w.config(state=tk.DISABLED)
                    except Exception:
                        pass
            _extra = ''
            if regen and self._gen_review_text:
                _extra = ('上一版剧本评级未通过，请根据以下评级意见针对性修改后重新输出完整剧本：\n'
                          + self._gen_review_text[:4000] +
                          '\n\n注意：只输出【剧本信息】【A. 剧本基础角色资产】【B. 剧本正文】，'
                          '输出完毕后输出 [STAGE1_DONE]')
            self.agent.generate_storyboard(self._gen_novel_text,
                                           self._gen_command_text,
                                           self._get_api_config(), self._gen_system_prompt,
                                           stop_marker='[STAGE1_DONE]',
                                           extra_context=_extra)
        except Exception as e:
            self.ctx.log('\n[系统日志] 阶段①生成启动异常: %s\n' % e)

    def _run_stage2(self, regen=False):
        """阶段②A：全资产(C/D/E) 生成 → [ASSETS_DONE]，等用户确认资产清单后再出分镜"""
        try:
            self.ctx.stop_flag = False
            self.btn_generate.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.progress_bar.start()
            self._gen_stage = 2
            # 2026-08-21 重新生成时清空对应阶段 tab（资产；保留剧本 script/all 不清）
            if regen:
                # 允许重新确认资产
                try:
                    self._stage_review_done.discard('[ASSETS_DONE]')
                except Exception:
                    pass
                for _k in ('character', 'scene', 'prop'):
                    try:
                        _w = self.text_widgets.get(_k)
                        if _w is not None:
                            _w.config(state=tk.NORMAL)
                            _w.delete('1.0', tk.END)
                            _w.config(state=tk.DISABLED)
                    except Exception:
                        pass
            # 2026-08-21 资产提取唯一来源：显式注入本集剧本正文（LLM 上下文只有小说全文时
            # 会从全文提取资产 → 资产比剧本用到的多。剧本正文必须作为唯一提取依据发给 LLM）
            _script_text = ''
            try:
                _w = self.text_widgets.get('script')
                if _w is not None:
                    _script_text = _w.get('1.0', tk.END).strip()
                if not _script_text:
                    _script_text = str((self.current_project or {}).get('sections', {}).get('script') or '').strip()
            except Exception:
                _script_text = ''
            _extra = ('剧本已通过评级确认。现在开始第二阶段A（资产清单）：'
                      '输出【C. 角色资产】【D. 场景资产】【E. 道具资产】（完整资产卡，'
                      '每张卡含中文+英文AI提示词）。'
                      '输出完毕后输出 [ASSETS_DONE] 并立即停止，等软件确认资产清单。')
            if _script_text:
                _extra += ('\n\n【本集剧本正文 · 资产提取唯一依据】\n'
                           '以下是本集【B. 剧本正文】全文。C/D/E 资产（角色/场景/道具）'
                           '只能从这份剧本正文中逐字提取：正文中出现的角色、场景、道具才生成资产卡，'
                           '正文未出现的严禁生成。用户消息中的小说全文仅供理解世界观背景，'
                           '严禁从小说全文或后续章节中提取任何资产。\n'
                           '----------\n' + _script_text + '\n----------')
            if regen and self._gen_review_text:
                _extra += ('\n\n上一版资产清单需调整，请根据以下要求修改后重新输出完整资产卡：\n'
                           + self._gen_review_text[:4000])
            self.agent.generate_storyboard(self._gen_novel_text,
                                           self._gen_command_text,
                                           self._get_api_config(), self._gen_system_prompt,
                                           stop_marker='[ASSETS_DONE]',
                                           extra_context=_extra)
        except Exception as e:
            self.ctx.log('\n[系统日志] 阶段②A 资产生成启动异常: %s\n' % e)

    def _run_stage2b(self, regen=False):
        """阶段②B：分镜全局规划 + F段分镜资产 → [STAGE2_DONE]，之后评级"""
        try:
            self.ctx.stop_flag = False
            self.btn_generate.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.progress_bar.start()
            self._gen_stage = 2
            # 2026-08-21 重新生成时清空分镜 tab（资产保留）
            if regen:
                # 允许重新评级分镜
                try:
                    self._stage_review_done.discard('[STAGE2_DONE]')
                except Exception:
                    pass
                for _k in ('global_plan', 'storyboard'):
                    try:
                        _w = self.text_widgets.get(_k)
                        if _w is not None:
                            _w.config(state=tk.NORMAL)
                            _w.delete('1.0', tk.END)
                            _w.config(state=tk.DISABLED)
                    except Exception:
                        pass
            # 2026-08-21 分镜阶段同样显式注入本集剧本正文（分镜必须基于本集剧本，防 LLM 依赖全文）
            _script_text = ''
            try:
                _w = self.text_widgets.get('script')
                if _w is not None:
                    _script_text = _w.get('1.0', tk.END).strip()
                if not _script_text:
                    _script_text = str((self.current_project or {}).get('sections', {}).get('script') or '').strip()
            except Exception:
                _script_text = ''
            _extra = ('资产清单已通过用户确认。现在开始第二阶段B（分镜）：'
                      '先输出【阶段一：分镜脚本（全局规划）】，再输出【F. 分镜资产】（按时长切分）。'
                      '输出完毕后输出 [STAGE2_DONE]')
            if _script_text:
                _extra += ('\n\n【本集剧本正文 · 分镜依据】\n'
                           '以下是本集【B. 剧本正文】全文。分镜全局规划与 F 段分镜资产'
                           '必须严格基于这份剧本正文：只规划本集正文包含的剧情、角色、场景、道具与台词，'
                           '严禁从小说全文或后续章节取景、取角色、取剧情。\n'
                           '----------\n' + _script_text + '\n----------')
            if regen and self._gen_review_text:
                _extra += ('\n\n上一版分镜评级未通过，请根据以下评级意见针对性修改后重新输出完整内容：\n'
                           + self._gen_review_text[:4000])
            self.agent.generate_storyboard(self._gen_novel_text,
                                           self._gen_command_text,
                                           self._get_api_config(), self._gen_system_prompt,
                                           stop_marker='[STAGE2_DONE]',
                                           extra_context=_extra)
        except Exception as e:
            self.ctx.log('\n[系统日志] 阶段②B 分镜生成启动异常: %s\n' % e)

    def _on_assets_complete(self):
        """2026-08-21 资产段完成：对比 剧本涉及资产 vs 实际生成资产，弹确认框"""
        try:
            # 2026-08-21 防重复：清空挂起回调，标记资产段已处理
            try:
                if getattr(self, '_pending_stage_after', None) is not None:
                    self.root.after_cancel(self._pending_stage_after)
                    self._pending_stage_after = None
            except Exception:
                pass
            try:
                self._stage_review_done.add('[ASSETS_DONE]')
            except Exception:
                pass
            self.progress_bar.stop()
            self.btn_stop.config(state=tk.DISABLED)
            self.label_gen_time.config(text='资产清单已生成，等待确认')
            self.ctx.log('\n[系统日志] 资产清单已生成，等待用户确认...\n')
            self._show_assets_confirm_dialog()
        except Exception as e:
            self.ctx.log('\n[系统日志] 资产确认处理异常: %s\n' % e)
            try:
                self._show_assets_confirm_dialog()
            except Exception:
                pass

    def _collect_script_assets(self):
        """从剧本正文（script tab）提取涉及的资产名：角色（△ 台词说话人）/场景（○ 标记）/道具（正文实体词）"""
        import re as _re
        _script = ''
        try:
            _script = self.text_widgets.get('script').get('1.0', tk.END) or ''
        except Exception:
            pass
        chars, scenes, props = [], [], []
        try:
            for line in _script.split('\n'):
                _l = line.strip()
                # 场景：○ 内景/外景 - 场景名 - 日/夜
                _m = _re.match(r'^[○O]\s*(内景|外景|内|外)\s*[-－]\s*(.+?)\s*[-－]', _l)
                if _m:
                    _sn = _m.group(2).strip()
                    if _sn and _sn not in scenes:
                        scenes.append(_sn)
                    continue
                # 角色：△ 说话人（...）：或 △ 说话人：
                _m2 = _re.match(r'^[△▲]\s*([^（(：:]{1,12})', _l)
                if _m2:
                    _cn = _m2.group(1).strip()
                    if _cn and _cn not in chars:
                        chars.append(_cn)
        except Exception:
            pass
        return {'characters': chars, 'scenes': scenes, 'props': props}

    def _collect_generated_assets(self):
        """从 C/D/E 资产 tab 提取实际生成的资产卡列表"""
        assets = []
        try:
            for _k, _t in (('character', '角色'), ('scene', '场景'), ('prop', '道具')):
                _txt = ''
                try:
                    _txt = self.text_widgets.get(_k).get('1.0', tk.END) or ''
                except Exception:
                    pass
                _parsed = self._extract_assets_full(_txt)
                for _a in _parsed:
                    assets.append({'type': _a['type'], 'name': _a['name'], 'prompt_en': _a.get('prompt_en', '')})
        except Exception:
            pass
        return assets

    def _show_assets_confirm_dialog(self):
        """2026-08-21 资产确认对话框：剧本涉及的资产 vs 实际生成的资产卡"""
        import re as _re
        _script_assets = self._collect_script_assets()
        _generated = self._collect_generated_assets()
        _gen_names = set()
        for _a in _generated:
            _gen_names.add(_a['name'].strip())
        # 2026-08-21 道具对比：剧本正文 vs 生成的道具卡。
        # 剧本正文没有道具专属标记（不像 ○场景/△角色），用"生成道具卡名反查剧本"判定：
        # 道具名（或其中任意连续3字）出现在剧本正文 = 剧本涉及的道具；否则 = 可能多余。
        _script_text = ''
        try:
            _script_text = self.text_widgets.get('script').get('1.0', tk.END) or ''
        except Exception:
            _script_text = ''

        def _prop_in_script(_pn, _txt):
            if not _pn:
                return False
            if _pn in _txt:
                return True
            if len(_pn) >= 3:
                for _i in range(len(_pn) - 2):
                    if _pn[_i:_i + 3] in _txt:
                        return True
            return False

        _props_in_script = []
        _props_not_in_script = []
        for _a in _generated:
            if _a['type'] == 'prop':
                _pn = _a['name'].strip()
                if _prop_in_script(_pn, _script_text):
                    _props_in_script.append(_pn)
                else:
                    _props_not_in_script.append(_pn)
        # 剧本涉及 vs 生成 对比（字符匹配：剧本角色名是否在生成的角色卡里）
        _missing = []
        for _cn in _script_assets.get('characters', []):
            if _cn and not any(_cn in _g or _g in _cn for _g in _gen_names):
                _missing.append(('角色', _cn))
        for _sn in _script_assets.get('scenes', []):
            if _sn and not any(_sn in _g or _g in _sn for _g in _gen_names):
                _missing.append(('场景', _sn))

        win = tk.Toplevel(self.root)
        win.title('资产清单确认')
        win.configure(bg='#FFFFFF')
        win.geometry('860x640')
        win.transient(self.root)
        win.grab_set()
        # 标题
        tk.Label(win, text='📋 资产清单确认', font=('微软雅黑', 14, 'bold'),
                 bg='#FFFFFF', fg='#2C3E50').pack(anchor='w', padx=16, pady=(12, 4))
        tk.Label(win, text='请确认剧本中涉及的资产是否都已生成：',
                 font=('微软雅黑', 10), bg='#FFFFFF', fg='#7F8C8D').pack(anchor='w', padx=16)
        # 内容区（左右两栏对比）
        body = tk.Frame(win, bg='#FFFFFF')
        body.pack(fill='both', expand=True, padx=16, pady=8)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        # 左：剧本涉及
        left = tk.Frame(body, bg='#F8F9F9', relief='solid', bd=1)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        tk.Label(left, text='🎬 剧本涉及的资产', font=('微软雅黑', 11, 'bold'),
                 bg='#F8F9F9', fg='#2C3E50').pack(anchor='w', padx=8, pady=6)
        _lt = scrolledtext.ScrolledText(left, font=('微软雅黑', 9), wrap='word', height=14,
                                        bg='#FFFFFF', fg='#2C3E50', relief='flat')
        _lt.pack(fill='both', expand=True, padx=6, pady=(0, 6))
        _lt_txt = '【角色】\n' + ('\n'.join(_script_assets.get('characters', [])) or '（未识别到）')
        _lt_txt += '\n\n【场景】\n' + ('\n'.join(_script_assets.get('scenes', [])) or '（未识别到）')
        # 2026-08-21 道具段：剧本涉及的道具（生成道具卡中剧本正文出现的）
        _lt_txt += '\n\n【道具（剧本涉及）】\n' + ('\n'.join(_props_in_script) or '（未识别到）')
        _lt.insert('1.0', _lt_txt)
        _lt.config(state=tk.DISABLED)
        # 右：实际生成
        right = tk.Frame(body, bg='#F8F9F9', relief='solid', bd=1)
        right.grid(row=0, column=1, sticky='nsew', padx=(6, 0))
        tk.Label(right, text='🖼 实际生成的资产卡', font=('微软雅黑', 11, 'bold'),
                 bg='#F8F9F9', fg='#2C3E50').pack(anchor='w', padx=8, pady=6)
        _rt = scrolledtext.ScrolledText(right, font=('微软雅黑', 9), wrap='word', height=14,
                                        bg='#FFFFFF', fg='#2C3E50', relief='flat')
        _rt.pack(fill='both', expand=True, padx=6, pady=(0, 6))
        _rt_txt = ''
        for _a in _generated:
            _rt_txt += '[%s] %s\n' % ({'character': '角色', 'scene': '场景', 'prop': '道具'}.get(_a['type'], _a['type']), _a['name'])
        _rt.insert('1.0', _rt_txt or '（未生成任何资产卡）')
        _rt.config(state=tk.DISABLED)
        # 缺失提示
        if _missing:
            _miss_txt = '⚠️ 剧本中出现但可能未生成：\n' + '\n'.join('[%s] %s' % (t, n) for t, n in _missing)
            _miss_lbl = tk.Label(win, text=_miss_txt, font=('微软雅黑', 9, 'bold'),
                                 bg='#FDEDEC', fg='#C0392B', anchor='w', justify='left')
            _miss_lbl.pack(fill='x', padx=16, pady=(0, 6))
        else:
            tk.Label(win, text='✅ 剧本涉及的资产均已生成', font=('微软雅黑', 10, 'bold'),
                     bg='#EAF7EA', fg='#27AE60').pack(fill='x', padx=16, pady=(0, 6))
        # 2026-08-21 多余道具提示：生成但剧本正文未出现的道具（可能从小说全文/旧版本生成）
        if _props_not_in_script:
            _extra_txt = ('⚠️ 生成但剧本正文未涉及的道具（可能多余，请确认）：\n'
                          + '、'.join(_props_not_in_script[:30])
                          + ('…' if len(_props_not_in_script) > 30 else ''))
            tk.Label(win, text=_extra_txt, font=('微软雅黑', 9, 'bold'),
                     bg='#FEF9E7', fg='#B7950B', anchor='w', justify='left',
                     wraplength=820).pack(fill='x', padx=16, pady=(0, 6))
        # 输入框（补充指令）
        _inp_frame = tk.Frame(win, bg='#FFFFFF')
        _inp_frame.pack(fill='x', padx=16, pady=(2, 6))
        tk.Label(_inp_frame, text='📝 补充/修改资产指令（可选）：', font=('微软雅黑', 10, 'bold'),
                 bg='#FFFFFF', fg='#2C3E50').pack(anchor='w')
        _entry = tk.Text(_inp_frame, font=('微软雅黑', 10), height=2, wrap='word',
                         bg='#FEFEFE', fg='#2C3E50', relief='solid', bd=1)
        _entry.pack(fill='x', pady=(4, 6))
        win._assets_entry = _entry
        # 按钮
        btns = tk.Frame(win, bg='#FFFFFF')
        btns.pack(fill='x', padx=16, pady=(0, 12))
        b_supp = tk.Button(btns, text='🔄 重新生成资产（按指令）', font=('微软雅黑', 11),
                           bg='#E67E22', fg='white', relief='flat', padx=14, pady=6,
                           command=lambda: self._on_assets_supplement(win))
        b_supp.pack(side='right', padx=(8, 0))
        b_ok = tk.Button(btns, text='✅ 确认无误，继续生成分镜', font=('微软雅黑', 11),
                         bg='#27AE60', fg='white', relief='flat', padx=18, pady=6,
                         command=lambda: self._on_assets_confirm(win))
        b_ok.pack(side='right')
        win.update_idletasks()
        # 窗口居中
        try:
            _x = self.root.winfo_x() + max(0, (self.root.winfo_width() - 860) // 2)
            _y = self.root.winfo_y() + max(0, (self.root.winfo_height() - 640) // 2)
            win.geometry('+%d+%d' % (_x, _y))
        except Exception:
            pass

    def _on_assets_confirm(self, win):
        """2026-08-21 资产确认通过 → 继续分镜生成（阶段②B）"""
        try:
            win.destroy()
        except Exception:
            pass
        self.ctx.log('\n[系统日志] 资产清单已确认，开始生成分镜...\n')
        self._gen_review_text = ''
        self._run_stage2b()

    def _on_assets_supplement(self, win):
        """2026-08-21 补充资产指令 → 重跑资产段（携带用户指令）"""
        _user_cmd = ''
        try:
            _entry = getattr(win, '_assets_entry', None)
            if _entry is not None:
                _user_cmd = _entry.get('1.0', tk.END).strip()
        except Exception:
            _user_cmd = ''
        try:
            win.destroy()
        except Exception:
            pass
        if _user_cmd:
            self._gen_review_text = '【你的资产补充/修改要求】\n' + _user_cmd[:2000]
            self.ctx.log('\n[系统日志] 资产补充指令：%s\n' % _user_cmd[:100])
        else:
            self._gen_review_text = '请重新生成资产清单，确保剧本中所有角色、场景、道具都有对应资产卡。'
        self._run_stage2(regen=True)

    def _run_stage3(self):
        """阶段③：剪映剪辑指导方案(G) → [ALL_DONE] 全部完成"""
        try:
            self.ctx.stop_flag = False
            self.btn_generate.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.progress_bar.start()
            self._gen_stage = 3
            _extra = ('分镜已通过评级确认。现在开始第三阶段（最后一段）：'
                      '输出【剪映专业剪辑指导方案】（G段），输出完毕后输出 [ALL_DONE]')
            self.agent.generate_storyboard(self._gen_novel_text,
                                           self._gen_command_text,
                                           self._get_api_config(), self._gen_system_prompt,
                                           stop_marker='[ALL_DONE]',
                                           extra_context=_extra)
        except Exception as e:
            self.ctx.log('\n[系统日志] 阶段③生成启动异常: %s\n' % e)

    def _advance_episode(self):
        """2026-08-21 续写功能：全集链路完成（第三段 [ALL_DONE]）后推进集数记录并保存。

        正常生成（非续写）→ episode 至少记为 1；续写模式 → 记为本次目标集数。
        下次勾选「续写下一集」时据此自动生成下一集。
        """
        try:
            if not self.current_project:
                return
            _ep = int(self.current_project.get('episode', 0) or 0)
            _target = getattr(self, '_continue_episode_target', 0) or 1
            if _target > _ep:
                self.current_project['episode'] = _target
                try:
                    self._auto_save_project()
                except Exception:
                    pass
                self.ctx.log('[系统日志] ✅ 第 %d 集全链路完成，集数记录已推进（下次勾选「续写下一集」将自动生成第 %d 集）\n'
                             % (_target, _target + 1))
        except Exception as e:
            self.ctx.log('[系统日志] 集数推进异常: %s\n' % e)

    def _on_stop_click(self):
        self.ctx.stop_flag = True
        self.ctx.log('[系统日志] 用户已停止生成。\n')

    # ============ 清除资产 ============
    def _clear_all_assets(self):
        """清除当前项目下所有内容：剧本、角色/场景/道具资产、分镜、剪辑方案、图片/视频历史等"""
        if not messagebox.askyesno(APP_NAME,
                                   '确定清除当前项目的全部内容？\n'
                                   '将删除：剧本正文、角色资产、场景资产、道具资产、\n'
                                   '分镜资产、剪辑方案、图片历史、视频历史。\n'
                                   '该操作不可撤销，请谨慎操作！'):
            return
        # 停止进行中的任务
        self.ctx.stop_flag = True
        # 清空所有输出 Tab
        for k, w in self.text_widgets.items():
            w.config(state=tk.NORMAL)
            w.delete('1.0', tk.END)
            w.config(state=tk.DISABLED)
        # 清空内部状态
        self.line_buffer = ''
        self.current_section = 'script'
        # 2026-08-21 续写功能：清除资产=从头开始 → 重置集数记录
        try:
            if self.current_project:
                self.current_project['episode'] = 0
        except Exception:
            pass
        self.image_history = []
        self._selected_hist_idx = set()
        self.video_history = []
        self._video_local_paths = {}
        self._video_preview_frames = {}
        self.current_image_url = ''
        self.current_video_url = ''
        self.video_ref_image_urls = []
        self.video_ref_image_path = ''
        self.pending_video_ref_urls = []
        self.video_matched_ready = False
        self.storyboard_prompts = []
        self.story_prompt_vars = []
        self.story_prompt_texts = []
        self._rebuild_empty_sb_list()
        # 清空资产图匹配
        self.asset_images = {}
        self.story_asset_links = []
        self._asset_prompt_map = {}
        self._asset_checked = {}
        try:
            self._asset_placeholder_ui()
        except Exception:
            pass
        # 清空视频提示词（分镜列表）与参考图预览
        try:
            self._rebuild_empty_sb_list()
        except Exception:
            pass
        # 刷新 UI
        self._update_history_ui()
        self._update_video_history_ui()
        self._update_ref_preview()
        self.progress_bar.stop()
        self.btn_generate.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.label_gen_time.config(text='就绪')
        # 保存空项目
        try:
            self._auto_save_project()
        except Exception:
            pass
        self._show_toast('已清除全部资产', 'success')
        self.ctx.log('\n[系统日志] 已清除当前项目全部内容。\n')

    # ============ 图片生成 ============
    def _on_gen_single_image_click(self):
        prompt = self.entry_img_prompt.get('1.0', tk.END).strip()
        if not prompt:
            self._show_toast('请输入提示词', 'warning')
            return
        prompt = prompt + image_style_suffix(self.combo_global_style.get())
        # 人物地域：单图生成也注入人种特征（如提示词涉及人物）
        try:
            _eth = ethnicity_guide((self.current_project or {}).get('ethnicity', '') or '中国')
            if _eth:
                prompt = prompt + '，' + _eth
        except Exception:
            pass
        # 道具禁止人体：单图生成时若提示词明显是道具（含道具特征词）→ 附加禁止人体约束
        try:
            _p = prompt.lower()
            _is_prop_like = any(_w in prompt for _w in ('道具', '静物', '耳环', '戒指', '项链', '手表',
                                                        '雨伞', '高跟鞋', '背包', '手机', '眼镜',
                                                        '酒杯', '捧花', '钥匙', '钱包')) and not any(
                _w in _p for _w in ('人物', '角色', 'portrait', 'woman', 'man', 'girl', 'boy'))
            if _is_prop_like and 'no person' not in _p:
                prompt = prompt.rstrip() + self._no_human_suffix(prompt, 'prop')
        except Exception:
            pass
        self.ctx.log('[系统日志] 正在提交图片生成任务并轮询结果...\n')
        self.agent.image_skill.generate_single_image(prompt, self._get_api_config(),
                                         self.combo_img_ratio.get(), self.combo_img_res.get())

    def _on_gen_images_batch_click(self):
        full_text = self.text_widgets.get('all').get('1.0', tk.END)
        # 2026-08-09 全资产生成要求：资产卡提到的角色/场景/道具全部解析生成，不过滤、不发挥。
        # 用健壮版按行解析器替代 llm_skill.extract_assets（旧正则遇括号卡名跨行吞内容，
        # 导致小宫女名错乱、后续道具卡全部解析失败；本方法按行解析+去重，资产全部保留）。
        assets = self._extract_assets_full(full_text)
        if not assets:
            self._show_toast('未提取到资产，请先生成剧本', 'warning')
            return
        # 当前章节（图片按章节分类标记；跨章节复用判断）——取视频Tab章节下拉
        cur_chapter = self.combo_vid_chapter.get() if hasattr(self, 'combo_vid_chapter') else "全部章节"
        # 全局风格（图片生成统一遵循用户选择的风格）
        cur_chapter_style = self.combo_global_style.get() if hasattr(self, 'combo_global_style') else DEFAULT_VIDEO_STYLE
        # 人物地域：项目创建时选择（中国/海外）→ 人种特征注入资产生成提示词
        _ethnicity = (self.current_project or {}).get('ethnicity', '') or '中国'
        # 记录资产名→提示词（供资产图匹配区域"重新生成"使用）
        for a in assets:
            if isinstance(a, dict) and a.get('name'):
                self._asset_prompt_map[a['name']] = a.get('prompt_en') or a.get('prompt') or ''
        # 中文提示词映射（双击图片预览显示用，用户要求显示中文）——用通用提取方法
        self._rebuild_cn_prompt_map(full_text, assets)
        # 跨章节资产复用：勾选"跳过已生成"时跳过同名资产；取消则全部重新生成。
        # 2026-08-09 全资产生成要求：默认不跳过（无勾选框时也不跳过），保证资产卡提到的全部生成。
        to_gen = []
        skipped = 0
        skip_existing = getattr(self, '_var_skip_existing', None)
        do_skip = bool(skip_existing.get()) if skip_existing else False
        existing_names = set()
        if do_skip:
            for it in self.image_history:
                nm = it.get('name') or ''
                if nm:
                    existing_names.add(nm)
        for a in assets:
            nm = a.get('name') if isinstance(a, dict) else None
            if do_skip and nm and nm in existing_names:
                skipped += 1
                continue  # 之前章节已生成过 → 跳过，后续分镜自动引用
            to_gen.append(a)
        if skipped:
            self.ctx.log('[系统日志] 跨章节资产复用：%d 个资产已在前面章节生成过，跳过不重复生成（取消"跳过已生成"可强制全部重新生成）\n' % skipped)
        # 2026-08-09 全资产生成要求：不合并随身小物（BIG_PROP_KEEP 反选词表已停用），
        # 资产卡里提到的道具全部单独生成，不做任何过滤。
        # 统一附加全局风格后缀 + 人物地域特征（用户选择的全局风格 → 图片风格统一；地域 → 人种统一）
        # 道具类资产强制附加"禁止人物/人体"约束（统一走 _no_human_suffix，批量/单图/重新生成三路径一致）
        for a in to_gen:
            if isinstance(a, dict) and a.get('prompt_en'):
                _suffix = image_style_suffix(cur_chapter_style)
                # 人物类资产附加人种特征（角色/人物图）
                if str(a.get('type') or '') in ('character', '人物', '角色'):
                    _eth = ethnicity_guide(_ethnicity)
                    if _eth:
                        _suffix += '，' + _eth
                # 道具类资产：强制禁止人物（纯静物）；穿戴类道具用加强版约束
                elif str(a.get('type') or '') in ('prop', '道具'):
                    if 'NO person' not in a['prompt_en'] and 'no people' not in a['prompt_en']:
                        _suffix += self._no_human_suffix(a.get('name') or '', 'prop')
                a['prompt_en'] = a['prompt_en'] + _suffix
        self.ctx.log('[系统日志] 正在并发生成 ' + str(len(to_gen)) + ' 张图片（章节：%s）...\n' % cur_chapter)
        # 记录当前章节，供 _handle_image_done 标记
        self._gen_image_chapter = cur_chapter
        # 批量生图比例跟随 UI 选择（图片Tab比例下拉；修复：原来固定 16:9 横图）
        try:
            _cfg_img = self._get_api_config()
            _cfg_img['img_ratio'] = self.combo_img_ratio.get() if hasattr(self, 'combo_img_ratio') else '16:9'
        except Exception:
            _cfg_img = self._get_api_config()
        self.agent.generate_images(to_gen, _cfg_img)

    def _extract_latest_prompt(self):
        try:
            text = self.text_widgets.get('storyboard').get('1.0', tk.END)
        except Exception:
            text = ''
        if not text.strip():
            self._show_toast('未找到分镜提示词', 'warning')
            return
        en_match = re.search(r'【英文AI提示词】\**\s*\**\s*(.*?)(?=\n\s*\**【|\n\s*=====|\Z)', text, re.S)
        cn_match = re.search(r'【中文AI提示词】\**\s*\**\s*(.*?)(?=\n\s*\**【英文|\n\s*=====|\Z)', text, re.S)
        prompt = (en_match.group(1).strip() if en_match else '') or (cn_match.group(1).strip() if cn_match else '')
        if not prompt:
            self._show_toast('未找到分镜提示词', 'warning')
            return
        self.entry_img_prompt.delete('1.0', tk.END)
        self.entry_img_prompt.insert('1.0', prompt)
        self._show_toast('提示词已提取', 'success')

    # ============ 视频生成 ============
    def _on_gen_video_click(self):
        """旧入口兼容：等同于生成选中分镜视频"""
        self._on_gen_selected_sb_videos()

    def _do_gen_video(self, prompt):
        # 2026-08-09 提示词结构重构（用户要求，与批量一致）：
        #  ①【执行要求+语言要求】前置（H3 对开头指令执行度最高）
        #  ②画面描述（英文）+ 台词（内嵌，中文原文）
        #  ③导演控制（全英文标签）
        _dur_eff = int(self.combo_vid_duration.get())
        # 2026-08-19 用户要求：按提示词时间轴总时长生成——提示词写 8 秒就生成 8 秒，
        # 绝不被界面默认时长截断（时间轴未走完不得提前结束）。
        _h3_dur = None
        # 台词-时长自适应：仅当提示词未提供时间轴总时长时兜底
        _dialogue = ''
        try:
            _num = getattr(self, '_sb_batch_index', None) or ''
            for _p in getattr(self, 'storyboard_prompts', []) or []:
                if _num and str(_p.get('num')) == str(_num):
                    _dialogue = _p.get('dialogue', '')
                    _h3_dur = _p.get('h3_duration')
                    break
            if _h3_dur:
                _dur_eff = int(_h3_dur)
                self.ctx.log('[系统日志] 按提示词时间轴 %d 秒生成（详细画面动态时序总时长）\n' % _dur_eff)
            else:
                if not _dialogue and getattr(self, 'storyboard_prompts', []):
                    _dialogue = self.storyboard_prompts[-1].get('dialogue', '')
                _dur_eff, _auto = self._auto_duration_for_dialogue(_dialogue, self.combo_vid_duration.get())
                if _auto:
                    self.ctx.log('[系统日志] 台词较长（%d 字），时长自动调整为 %d 秒\n'
                                 % (len(str(_dialogue).strip()), _dur_eff))
        except Exception:
            pass
        # ③导演控制（机位运镜视角，全英文标签，用户要求必须传）
        try:
            _director = ''
            _num = getattr(self, '_sb_batch_index', None) or ''
            for _p in getattr(self, 'storyboard_prompts', []) or []:
                if _num and str(_p.get('num')) == str(_num):
                    _director = _p.get('director', '')
                    break
            if not _director and getattr(self, 'storyboard_prompts', []):
                _director = self.storyboard_prompts[-1].get('director', '')
            if _director and _director not in prompt:
                prompt = prompt.rstrip() + '\n' + _director
        except Exception:
            pass
        refs = list(getattr(self, 'pending_video_ref_urls', []))
        # 2026-08-19 分镜衔接修复：提示词注入参考素材说明（单镜生成同样生效）
        try:
            _meta = []
            _num2 = getattr(self, '_sb_batch_index', None) or ''
            for _ln in getattr(self, 'story_asset_links', []):
                if _num2 and str(_ln.get('num')) == str(_num2):
                    for _core in _ln.get('assets', []):
                        if isinstance(_core, str) and _core.startswith('hist:'):
                            _u2 = _core[5:]
                            for _it in getattr(self, 'image_history', []):
                                if _it.get('url') == _u2 and _it.get('url'):
                                    _meta.append((_it['url'], _it.get('name', ''), _it.get('type', '上传')))
                                    break
                        else:
                            _item = (self.asset_images or {}).get(_core)
                            if _item and _item.get('url'):
                                _meta.append(_item)
                    break
            _has_prev = bool(self.video_history)
            prompt = self._inject_h3_ref_defs(prompt, _meta, _has_prev)
        except Exception:
            pass
        self.video_matched_ready = False
        self.pending_video_ref_urls = []
        self.label_vid_status.config(text='生成中...')
        self.btn_gen_vid.config(state=tk.DISABLED)
        self.ctx.log('[系统日志] 正在生成视频...\n')
        # 分镜衔接 + 人物音色：单镜生成自动带上上一镜视频（video_history 最后一条）+ 最近分镜人物音色
        cfg = self._get_api_config()
        try:
            if self.video_history:
                cfg['prev_video_url'] = self.video_history[-1]
        except Exception:
            pass
        # 人物音色：取最近生成/同步的分镜涉及人物（_sb_batch_index 或最后一个 story_asset_links）
        try:
            _num = getattr(self, '_sb_batch_index', None) or ''
            _voices = self._voices_for_storyboard_num(_num) if _num else []
            if not _voices and getattr(self, 'story_asset_links', []):
                _voices = self._voices_for_storyboard_num(self.story_asset_links[-1].get('num', ''))
            if _voices:
                cfg['ref_audio_paths'] = _voices
        except Exception:
            pass
        self.agent.generate_video(prompt, cfg,
                                  _dur_eff, self.combo_vid_ratio.get(),
                                  self.combo_vid_res.get(), refs)

    def _on_vid_ref_select(self, event=None):
        if not hasattr(self, 'listbox_vid_ref'):
            return  # 生成器版已移除"选择历史图片"区域，该方法不再被触发
        sel = self.listbox_vid_ref.curselection()
        urls = []
        for i in sel:
            if 0 <= i < len(self.image_history):
                urls.append(self.image_history[i]['url'])
        self.video_ref_image_urls = urls
        self.video_matched_ready = False
        self.pending_video_ref_urls = urls
        self._update_ref_preview()

    def _update_ref_preview(self):
        if not hasattr(self, 'ref_preview_canvas'):
            return  # 生成器版参考图设置区域已隐藏
        self.ref_preview_canvas.delete('all')
        w = max(self.ref_preview_canvas.winfo_width(), 200)
        h = max(self.ref_preview_canvas.winfo_height(), 180)
        cx, cy = w // 2, h // 2
        if self.video_ref_image_urls:
            # 后台线程下载预览图（修复：原主线程 requests.get 网络慢时卡 UI），
            # 完成后 root.after 回主线程更新 canvas（tkinter 控件只能主线程操作）
            _url0 = self.video_ref_image_urls[0]
            def _load():
                try:
                    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': self.entry_media_base_url.get().strip()}
                    resp = requests.get(_url0, headers=headers, timeout=20, verify=False)
                    img = Image.open(io.BytesIO(resp.content))
                    img.thumbnail((w - 16, h - 16), Image.LANCZOS)
                    ph = ImageTk.PhotoImage(img)
                    self.root.after(0, lambda: self._apply_ref_preview(ph, cx, cy))
                except Exception:
                    self.root.after(0, lambda: self._apply_ref_preview(None, cx, cy))
            threading.Thread(target=_load, daemon=True).start()
        else:
            self.ref_preview_canvas.create_text(cx, cy, text='无参考图\n(从下方列表多选历史图片)',
                                                fill=COLOR_TEXT_DIM, font=('微软雅黑', 9), justify='center')

    def _apply_ref_preview(self, ph, cx, cy):
        """主线程：把后台下载的预览图画到 canvas（ph=None 显示预览失败）"""
        try:
            if not hasattr(self, 'ref_preview_canvas'):
                return
            self.ref_preview_canvas.delete('all')
            if ph is None:
                self.ref_preview_canvas.create_text(cx, cy, text='预览失败', fill=COLOR_DANGER,
                                                    font=('微软雅黑', 9))
                return
            self._ref_preview_photo = ph
            self.ref_preview_canvas.create_image(cx, cy, image=ph)
        except Exception:
            pass

    def _upload_image_for_video(self):
        path = filedialog.askopenfilename(title='选择参考图', filetypes=[
            ('图片文件', '*.png *.jpg *.jpeg *.webp'), ('所有文件', '*.*')])
        if not path:
            return
        try:
            self.video_ref_image_path = path
            img = Image.open(path)
            self.image_history.append({'url': '', 'img': img, 'name': os.path.basename(path)})
            self._update_history_ui()
            self.video_matched_ready = False
            self.pending_video_ref_urls = []
            self._show_toast('已上传本地图片\n(注意:平台可能不支持本地路径)', 'info')
        except Exception as e:
            self._show_toast('加载失败: ' + str(e), 'warning')

    def _clear_video_ref_image(self):
        self.video_ref_image_urls = []
        self.video_ref_image_path = ''
        self.pending_video_ref_urls = []
        self.video_matched_ready = False
        self._update_ref_preview()

    # ============ 历史记录 ============
    def _toggle_select_image(self, idx):
        """单击缩略图：切换选中状态（可多选，配合删除按钮使用）。
        只局部更新高亮（不重绘整个列表），否则 widget 销毁重建会导致双击事件永远无法触发。"""
        if idx in self._selected_hist_idx:
            self._selected_hist_idx.discard(idx)
        else:
            self._selected_hist_idx.add(idx)
        # 局部刷新：只更新该缩略图与其名字 label 的选中样式（不重建 widget，保证双击可用）
        try:
            for w in self.history_frame_inner.winfo_children():
                if getattr(w, '_hist_idx', None) != idx:
                    continue
                if not isinstance(w, tk.Label):
                    continue
                if w._hist_is_name:
                    w.configure(fg=COLOR_DANGER if idx in self._selected_hist_idx else COLOR_TEXT_DIM)
                else:
                    c = COLOR_DANGER if idx in self._selected_hist_idx else COLOR_BORDER
                    w.configure(highlightbackground=c, highlightcolor=c)
        except Exception:
            # 兜底：局部更新失败时退回全量重绘（双击失效可接受，总比状态错乱好）
            self._update_history_ui()

    def _upload_history_image(self):
        """2026-08-15 需求1：上传本地图片到图片历史记录（支持多选）。
        2026-08-21 需求1升级：弹对话框选择「替代现有资产图」或「新增资产图」——
        - 替代：选一个现有资产（角色/场景/道具）→ 上传后替换该资产图（image_history + asset_images）
        - 新增：直接加进 image_history（现状）
        选图 → 若媒体供应商是 ComfyUI 则上传拿 url（供视频参考图链路使用）→ 加入/替换 → 刷新 UI。"""
        # 先选模式：替代 or 新增
        dlg = tk.Toplevel(self.root)
        dlg.title('上传图片 - 选择模式')
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry('460x320+%d+%d' % (self.root.winfo_x() + 100, self.root.winfo_y() + 100))
        try:
            dlg.iconbitmap(resource_path('app.ico'))
        except Exception:
            pass
        tk.Label(dlg, text='📤 上传图片：想怎么用？', font=('微软雅黑', 12, 'bold'),
                 fg=COLOR_ACCENT_DARK, bg=COLOR_PANEL).pack(anchor='w', padx=16, pady=(14, 8))

        mode_var = tk.StringVar(value='new')

        # 替代模式：资产选择列表（从 image_history / asset_images 收集去重资产名）
        tk.Radiobutton(dlg, text='🔄 替代现有资产图（如替换「林雪」的角色图）', variable=mode_var, value='replace',
                       font=('微软雅黑', 10), bg=COLOR_PANEL, fg=COLOR_TEXT, selectcolor=COLOR_INPUT,
                       activebackground=COLOR_PANEL).pack(anchor='w', padx=16, pady=(6, 2))
        replace_frame = tk.Frame(dlg, bg=COLOR_PANEL)
        replace_frame.pack(fill='both', expand=True, padx=16)
        self._upload_replace_listbox = tk.Listbox(replace_frame, font=('微软雅黑', 9), height=5,
                                                  relief='solid', bd=1, bg=COLOR_INPUT, fg=COLOR_TEXT,
                                                  selectbackground=COLOR_ACCENT, activestyle='none')
        sb = ttk.Scrollbar(replace_frame, orient='vertical', command=self._upload_replace_listbox.yview)
        self._upload_replace_listbox.configure(yscrollcommand=sb.set)
        self._upload_replace_listbox.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        # 收集资产名（去重，优先 asset_images 键，其次 image_history name）
        _names = []
        for _k in (self.asset_images or {}).keys():
            if _k and _k not in _names:
                _names.append(_k)
        for _it in self.image_history:
            _n = _it.get('name') or ''
            if _n and _n not in _names:
                _names.append(_n)
        for _n in _names[:200]:
            self._upload_replace_listbox.insert(tk.END, _n)

        tk.Radiobutton(dlg, text='➕ 新增资产图（补充缺失的图）', variable=mode_var, value='new',
                       font=('微软雅黑', 10), bg=COLOR_PANEL, fg=COLOR_TEXT, selectcolor=COLOR_INPUT,
                       activebackground=COLOR_PANEL).pack(anchor='w', padx=16, pady=(6, 2))

        btns = tk.Frame(dlg, bg=COLOR_PANEL)
        btns.pack(fill='x', padx=16, pady=(8, 12))
        def _confirm():
            mode = mode_var.get()
            target = ''
            if mode == 'replace':
                sel = self._upload_replace_listbox.curselection()
                if not sel:
                    self._show_toast('请先选择要替代的资产', 'warning')
                    return
                target = self._upload_replace_listbox.get(sel[0])
            dlg.destroy()
            self._do_upload_history_image(mode, target)
        btn_ok = tk.Button(btns, text='✅ 下一步选择图片', font=('微软雅黑', 10, 'bold'),
                           bg=COLOR_ACCENT, fg='white', relief='flat', command=_confirm)
        btn_ok.pack(side='left', padx=(0, 8))
        bind_hover(btn_ok, COLOR_ACCENT, COLOR_ACCENT_DARK)
        tk.Button(btns, text='取消', font=('微软雅黑', 10), bg=COLOR_BORDER, fg=COLOR_TEXT,
                  relief='flat', command=dlg.destroy).pack(side='left')

    def _do_upload_history_image(self, mode, target):
        """2026-08-21 真正执行上传：mode='replace'（替代 target 资产）或 'new'（新增）"""
        paths = filedialog.askopenfilenames(title="选择要上传的本地图片（可多选）", filetypes=[
            ('图片文件', '*.png *.jpg *.jpeg *.webp *.bmp'), ('所有文件', '*.*')])
        if not paths:
            return
        def _worker():
            added = 0
            failed = []
            for path in paths:
                try:
                    img = Image.open(path)
                    img.load()
                    img.info.pop('icc_profile', None)
                    url = ''
                    # 若媒体供应商是 ComfyUI，上传拿 url（视频参考图链路需要可访问的 url）
                    try:
                        cfg = self._get_api_config()
                        base = (cfg.get('media_base_url') or '').strip().rstrip('/')
                        vtype = str(cfg.get('media_vendor_type') or '').strip().lower()
                        vmodel = (cfg.get('vid_model') or '').strip().lower()
                        if base and (vtype == 'comfyui' or vmodel.startswith('comfyui')
                                     or any(k in base.lower() for k in ('8188', '15794', '8800', 'comfy'))):
                            buf = io.BytesIO()
                            img.convert('RGB').save(buf, format='PNG')
                            buf.seek(0)
                            fname = 'up_%d_%s.png' % (int(time.time()), os.path.splitext(os.path.basename(path))[0][:20])
                            files = {'image': (fname, buf, 'image/png')}
                            r = requests.post(base + '/upload/image', files=files,
                                              data={'overwrite': 'true'}, timeout=60, verify=False)
                            if r.status_code == 200:
                                name = (r.json() or {}).get('name') or ''
                                if name:
                                    url = base + '/view?filename=' + name.replace(' ', '%20') + '&type=input'
                    except Exception:
                        url = ''
                    self.root.after(0, lambda u=url, im=img, p=path: self._finish_upload_history_image(u, im, p, mode, target))
                    added += 1
                except Exception as e:
                    failed.append(os.path.basename(path))
            self.root.after(0, lambda a=added, f=failed: self._show_toast(
                '已上传 %d 张图片%s' % (a, ('，失败 %d 张' % len(f)) if f else ''), 'success' if not f else 'warning'))
        threading.Thread(target=_worker, daemon=True).start()
        self._show_toast('正在上传图片...', 'info')

    def _finish_upload_history_image(self, url, img, path, mode='new', target=''):
        """主线程：上传完成的图片加入 image_history 并刷新 UI（2026-08-21 支持替代模式）"""
        try:
            name = os.path.splitext(os.path.basename(path))[0]
            local_path = self._save_asset_image_local(img, target or name, '')
            if mode == 'replace' and target:
                # 替代模式：替换该资产的所有引用（image_history + asset_images）
                replaced = False
                for _it in self.image_history:
                    if _it.get('name') == target:
                        _it.update({'url': url, 'img': img, 'local_path': local_path})
                        replaced = True
                        break
                if not replaced:
                    self.image_history.append({'url': url, 'img': img, 'name': target,
                                               'prompt': '', 'type': '', 'chapter': '上传图片',
                                               'prompt_cn': '', 'local_path': local_path})
                # 同步 asset_images（资产图匹配区）
                if target in self.asset_images:
                    _old = self.asset_images[target]
                    self.asset_images[target] = {'url': url, 'img': img,
                                                 'prompt': _old.get('prompt', ''),
                                                 'type': _old.get('type', '')}
                try:
                    self._match_assets_to_storyboard()
                except Exception:
                    pass
                try:
                    self._rebuild_asset_match_area()
                except Exception:
                    pass
                self._show_toast('已用上传图替代资产「%s」' % target, 'success')
            else:
                # 新增模式（原逻辑）
                self.image_history.append({'url': url, 'img': img,
                                           'name': name,
                                           'prompt': '', 'type': '', 'chapter': '上传图片',
                                           'prompt_cn': '', 'local_path': local_path})
                if len(self.image_history) > 500:
                    self.image_history.pop(0)
                self._show_toast('已新增资产图「%s」' % name, 'success')
            self._update_history_ui()
        except Exception:
            pass

    def _delete_selected_images(self):
        """删除选中的图片记录：从 image_history 移除，并同步清理视频参考引用"""
        if not self.image_history:
            self._show_toast('图片历史为空', 'warning')
            return
        sel = sorted(self._selected_hist_idx)
        if not sel:
            self._show_toast('请先单击选中要删除的图片，再点删除', 'warning')
            return
        if not messagebox.askyesno(APP_NAME, '确定删除选中的 %d 张图片记录？\n删除后将从图片历史与视频参考列表中移除。' % len(sel)):
            return
        # 记录被删 url，用于清理视频参考引用
        deleted_urls = set()
        for i in sel:
            if 0 <= i < len(self.image_history):
                deleted_urls.add(self.image_history[i].get('url') or '')
        for i in reversed(sel):
            if 0 <= i < len(self.image_history):
                self.image_history.pop(i)
        self._selected_hist_idx = set()
        # 同步清理视频参考引用（含已选中的参考图与待确认的匹配列表）
        self.video_ref_image_urls = [u for u in self.video_ref_image_urls if u not in deleted_urls]
        self.pending_video_ref_urls = [u for u in self.pending_video_ref_urls if u not in deleted_urls]
        self._update_history_ui()
        self._update_ref_preview()
        self._show_toast('已删除 %d 张图片记录' % len(sel), 'success')

    def _delete_image_at(self, idx):
        """从大图预览弹窗删除单张图片记录"""
        if not (0 <= idx < len(self.image_history)):
            return
        item = self.image_history[idx]
        if not messagebox.askyesno(APP_NAME, '确定删除图片「%s」？\n删除后将从图片历史与视频参考列表中移除。' % str(item.get('name', ''))):
            return
        deleted_urls = {item.get('url') or ''}
        self.image_history.pop(idx)
        self._selected_hist_idx = {i - 1 for i in self._selected_hist_idx if i > idx} | {i for i in self._selected_hist_idx if i < idx}
        self.video_ref_image_urls = [u for u in self.video_ref_image_urls if u not in deleted_urls]
        self.pending_video_ref_urls = [u for u in self.pending_video_ref_urls if u not in deleted_urls]
        self._update_history_ui()
        self._update_ref_preview()
        self._show_toast('已删除图片记录', 'success')

    def _fetch_history_image(self, idx, url):
        """后台线程下载历史图片（img 缺失时补拉），完成后主线程局部刷新。
        失败时标记 _img_fail（显示占位），避免无限重试 + 历史区永久空白。"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0', 'Referer': self.entry_media_base_url.get().strip()}
            resp = requests.get(url, headers=headers, timeout=30, verify=False)
            img = Image.open(io.BytesIO(resp.content))
            img.info.pop('icc_profile', None)
            if 0 <= idx < len(self.image_history):
                self.image_history[idx]['img'] = img
                self.image_history[idx].pop('_img_fail', None)
            self.root.after(0, self._update_history_ui)
        except Exception:
            # 拉取失败：打标记，历史区显示"加载失败"占位而非空白
            try:
                if 0 <= idx < len(self.image_history):
                    self.image_history[idx]['_img_fail'] = True
                self.root.after(0, self._update_history_ui)
            except Exception:
                pass

    def _update_history_ui(self):
        for w in self.history_frame_inner.winfo_children():
            w.destroy()
        self.image_history_images = []
        max_w = max(self.history_canvas.winfo_width() - 12, 120)
        cols = max(max_w // 130, 2)
        # 清理已失效的选中索引（删除/溢出后索引偏移）
        n = len(self.image_history)
        self._selected_hist_idx = {i for i in self._selected_hist_idx if 0 <= i < n}
        # 按章节分组显示：章节名 → [(idx, item)]，保持章节内原顺序
        groups = {}
        for i, item in enumerate(self.image_history):
            ch = str(item.get('chapter') or '未分类')
            groups.setdefault(ch, []).append((i, item))
        row = 0
        for ch, items in groups.items():
            # 章节标题行
            hd = tk.Label(self.history_frame_inner,
                          text='📖 %s（%d 张）' % (ch, len(items)),
                          font=('微软雅黑', 9, 'bold'),
                          fg=COLOR_ACCENT, bg=COLOR_PANEL)
            hd.grid(row=row, column=0, columnspan=cols, sticky='w', padx=4, pady=(8, 2))
            row += 1
            # 该章节图片网格：每组内按 (row*2, row*2+1) 排（标题行+图片行用累加行号，杜绝重叠）
            _group_rows = (len(items) + cols - 1) // cols  # 该章需要的图片行数
            for gi, (i, item) in enumerate(items):
                try:
                    img = item.get('img')
                    if img is None:
                        # 项目重新加载后 img 缺失：后台线程补拉（不在主线程下载，避免 UI 卡死）
                        url = item.get('url') or ''
                        if url and not item.get('_img_fail'):
                            threading.Thread(target=self._fetch_history_image, args=(i, url), daemon=True).start()
                        # 补拉失败/无 url：显示占位（避免历史区空白）
                        if not item.get('_img_fail'):
                            continue  # 本次先跳过（后台拉取完成后会自动补显示）
                    if img is None:
                        # 补拉失败占位：灰色块 + 名字
                        _ph = Image.new('RGB', (120, 120), (60, 60, 70))
                        ph = ImageTk.PhotoImage(_ph)
                        self.image_history_images.append(ph)
                        selected = i in self._selected_hist_idx
                        col = gi % cols
                        _r = row + (gi // cols) * 2
                        lb = tk.Label(self.history_frame_inner, image=ph, bg=COLOR_PANEL, cursor='hand2',
                                      highlightthickness=3,
                                      highlightbackground=COLOR_DANGER if selected else COLOR_BORDER,
                                      highlightcolor=COLOR_DANGER if selected else COLOR_BORDER)
                        lb.image = ph
                        lb._hist_idx = i
                        lb._hist_is_name = False
                        lb.grid(row=_r, column=col, padx=4, pady=(4, 0))
                        lb.bind('<Button-1>', lambda e, idx=i: self._toggle_select_image(idx))
                        lb.bind('<Double-Button-1>', lambda e, idx=i: self._show_large_image(idx))
                        nm = str(item.get('name', ''))[:14]
                        lbn = tk.Label(self.history_frame_inner, text='[' + str(i + 1) + '] ' + nm + '（加载失败）',
                                       font=('微软雅黑', 8),
                                       fg=COLOR_DANGER if selected else COLOR_TEXT_DIM,
                                       bg=COLOR_PANEL, cursor='hand2')
                        lbn._hist_idx = i
                        lbn._hist_is_name = True
                        lbn.grid(row=_r + 1, column=col, sticky='n', padx=4, pady=(0, 2))
                        lbn.bind('<Button-1>', lambda e, idx=i: self._toggle_select_image(idx))
                        continue
                    thumb = img.copy()
                    thumb.thumbnail((120, 120), Image.LANCZOS)
                    ph = ImageTk.PhotoImage(thumb)
                    self.image_history_images.append(ph)
                    selected = i in self._selected_hist_idx
                    col = gi % cols
                    _r = row + (gi // cols) * 2
                    lb = tk.Label(self.history_frame_inner, image=ph, bg=COLOR_PANEL, cursor='hand2',
                                  highlightthickness=3,
                                  highlightbackground=COLOR_DANGER if selected else COLOR_BORDER,
                                  highlightcolor=COLOR_DANGER if selected else COLOR_BORDER)
                    lb.image = ph
                    lb._hist_idx = i
                    lb._hist_is_name = False
                    lb.grid(row=_r, column=col, padx=4, pady=(4, 0))
                    lb.bind('<Button-1>', lambda e, idx=i: self._toggle_select_image(idx))
                    lb.bind('<Double-Button-1>', lambda e, idx=i: self._show_large_image(idx))
                    nm = str(item.get('name', ''))[:14]
                    lbn = tk.Label(self.history_frame_inner, text='[' + str(i + 1) + '] ' + nm,
                                   font=('微软雅黑', 8),
                                   fg=COLOR_DANGER if selected else COLOR_TEXT_DIM,
                                   bg=COLOR_PANEL, cursor='hand2')
                    lbn._hist_idx = i
                    lbn._hist_is_name = True
                    lbn.grid(row=_r + 1, column=col, sticky='n', padx=4, pady=(0, 2))
                    lbn.bind('<Button-1>', lambda e, idx=i: self._toggle_select_image(idx))
                except Exception:
                    continue
            # 该章结束后行号推进：标题1行 + 图片行数*2（图+名字各一行）
            row += _group_rows * 2

    def _show_large_image(self, idx):
        """双击放大图片 + 显示该图片提示词（可编辑）+ 重新生成（用户需求 2026-08-08）"""
        if idx >= len(self.image_history):
            return
        item = self.image_history[idx]
        dlg = tk.Toplevel(self.root)
        dlg.title('图片预览与编辑 - ' + str(item.get('name', '')))
        dlg.configure(bg=COLOR_PANEL)
        dlg.transient(self.root)
        try:
            dlg.iconbitmap(resource_path('app.ico'))
        except Exception:
            pass
        img = item.get('img')
        if img is None:
            # 项目重开后图片由后台线程补拉，若尚未完成则提示
            self._show_toast('图片尚未加载完成，请稍后重试', 'warning')
            url = item.get('url') or ''
            if url:
                threading.Thread(target=self._fetch_history_image, args=(idx, url), daemon=True).start()
            dlg.destroy()
            return
        sw, sh = self.root.winfo_screenwidth() - 120, self.root.winfo_screenheight() - 180
        img2 = img.copy()
        img2.thumbnail((min(sw, 700), min(sh, 500)), Image.LANCZOS)
        ph = ImageTk.PhotoImage(img2)
        dlg.photo = ph
        lb = tk.Label(dlg, image=ph, bg=COLOR_PANEL)
        lb.pack(padx=10, pady=(10, 4))
        # 提示词编辑区（显示该图片的提示词，可编辑）
        tk.Label(dlg, text='✏️ 图片提示词（可编辑，修改后点"重新生成"按新提示词重绘）：', font=("微软雅黑", 9),
                 bg=COLOR_PANEL, fg=COLOR_TEXT).pack(anchor='w', padx=14, pady=(6, 2))
        text_prompt = tk.Text(dlg, font=FONT_CODE, wrap=tk.WORD, height=6, relief='solid', bd=1,
                              bg=COLOR_INPUT, fg=COLOR_TEXT, insertbackground=COLOR_TEXT)
        text_prompt.pack(fill='x', padx=14)
        # 2026-08-08 用户要求：双击预览显示的提示词用中文（优先 prompt_cn；空则实时从全文提取，
        # 不再回退英文——用户明确要求中文版）
        _cur_prompt = item.get('prompt_cn') or ''
        if not _cur_prompt:
            try:
                _nm = str(item.get('name') or '')
                if _nm:
                    # 先从映射取，映射空则现提取
                    if not getattr(self, '_asset_prompt_cn_map', None):
                        _full = self.text_widgets.get('all').get('1.0', tk.END)
                        self._rebuild_cn_prompt_map(_full)
                    _cur_prompt = (self._asset_prompt_cn_map or {}).get(_nm, '')
                    if _cur_prompt:
                        item['prompt_cn'] = _cur_prompt  # 回填，下次直接用
            except Exception:
                pass
        text_prompt.insert('1.0', _cur_prompt)
        # 按钮行：重新生成 / 下载 / 删除 / 关闭
        btn_row = tk.Frame(dlg, bg=COLOR_PANEL)
        btn_row.pack(pady=(8, 10))
        btn_regen = tk.Button(btn_row, text='🔄 重新生成', font=FONT_MAIN, bg='#F0A500', fg='white',
                              relief='flat', padx=16, pady=4,
                              command=lambda: self._regen_image_with_prompt(idx, text_prompt, dlg))
        btn_regen.pack(side='left', padx=5)
        bind_hover(btn_regen, '#F0A500', '#D08A00')
        btn = tk.Button(btn_row, text='下载此图片', font=FONT_MAIN, bg=COLOR_ACCENT, fg='white',
                        relief='flat', padx=16, pady=4,
                        command=lambda: self._download_specific_image(item.get('url', '')))
        btn.pack(side='left', padx=5)
        bind_hover(btn, COLOR_ACCENT, COLOR_ACCENT_DARK)
        btn_del = tk.Button(btn_row, text='删除此图片', font=FONT_MAIN, bg=COLOR_DANGER, fg='white',
                            relief='flat', padx=16, pady=4,
                            command=lambda: [self._delete_image_at(idx), dlg.destroy()])
        btn_del.pack(side='left', padx=5)
        bind_hover(btn_del, COLOR_DANGER, "#D92B21")

    def _regen_image_with_prompt(self, idx, text_prompt, dlg):
        """用编辑后的提示词重新生成该图片（替换原图记录）"""
        new_prompt = text_prompt.get('1.0', tk.END).strip()
        if not new_prompt:
            self._show_toast('提示词不能为空', 'warning')
            return
        if idx >= len(self.image_history):
            return
        item = self.image_history[idx]
        name = item.get('name', '')
        atype = item.get('type', '')
        # 记录当前编辑的分镜索引与提示词，_finish_image_done 时回填替换
        self._regen_hist_idx = idx
        self._regen_asset_name = name
        self._regen_prompt = new_prompt
        # 同步更新资产提示词映射（重生成后再次编辑预览时能显示最新提示词）
        if name:
            self._asset_prompt_map[name] = new_prompt
            # 用户编辑的是中文提示词 → 同步更新中文映射与记录（双击预览继续显示中文）
            try:
                if not hasattr(self, '_asset_prompt_cn_map'):
                    self._asset_prompt_cn_map = {}
                self._asset_prompt_cn_map[name] = new_prompt
                self._regen_prompt_cn = new_prompt
            except Exception:
                pass
        # 提示词已含用户编辑内容（不再附加风格后缀，保持用户原样；若没有风格可加）
        try:
            _style = self.combo_global_style.get() if hasattr(self, 'combo_global_style') else DEFAULT_VIDEO_STYLE
            if 'photorealistic' not in new_prompt and 'anime' not in new_prompt and 'cinematic' not in new_prompt:
                new_prompt = new_prompt + image_style_suffix(_style)
        except Exception:
            pass
        self.ctx.log('[系统日志] 正在用编辑后的提示词重新生成图片 [%s]...\n' % name)
        self.agent.image_skill.generate_single_image(new_prompt, self._get_api_config(),
                                                     self.combo_img_ratio.get(), self.combo_img_res.get())
        self._show_toast('正在重新生成 [%s]...' % name, 'info')
        dlg.destroy()

    def _download_specific_image(self, url):
        if not url:
            self._show_toast('本地图片无法下载', 'warning')
            return
        path = filedialog.asksaveasfilename(defaultextension='.png',
                                            filetypes=[('PNG 图片', '*.png'), ('所有文件', '*.*')],
                                            title='保存图片')
        if not path:
            return
        try:
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30, verify=False)
            with open(path, 'wb') as f:
                f.write(resp.content)
            self._show_toast('图片已保存', 'success')
        except Exception as e:
            messagebox.showerror('下载失败', '错误详情: ' + str(e))

    def _update_video_history_ui(self):
        for w in self.frame_vid_history_inner.winfo_children():
            w.destroy()
        self.video_history_videos = []
        # 2026-08-21 缩略图引用池（PhotoImage 必须持有引用防 GC）
        self._vid_thumb_refs = []
        for i, url in enumerate(self.video_history):
            row = tk.Frame(self.frame_vid_history_inner, bg=COLOR_PANEL)
            row.pack(fill='x', padx=4, pady=2)
            # 2026-08-21 本地保存状态（已自动下载到本地显示 📁 标记）
            _local = ''
            try:
                _local = (getattr(self, '_video_local_paths', {}) or {}).get(url, '')
                if _local and not os.path.exists(_local):
                    _local = ''
            except Exception:
                _local = ''
            _tag = '📁 ' if _local else '⏳ '
            # 2026-08-21 视频首帧缩略图（画面代替文字行；hover 画面自动播放预览）
            _thumb = self._video_thumb_for(url)
            if _thumb is not None:
                img_lbl = tk.Label(row, image=_thumb, bg=COLOR_PANEL, cursor='hand2',
                                   relief='solid', bd=1, highlightbackground='#D0D0D0')
                img_lbl.pack(side='left', padx=(0, 8))
                img_lbl.bind('<Enter>', lambda e, u=url: self._show_video_preview(u))
                img_lbl.bind('<Leave>', lambda e: self._stop_video_preview())
                self._vid_thumb_refs.append(_thumb)
            # 2026-08-21 鼠标悬停"视频 N"标签 → 自动弹出预览（跑马灯播放）
            lbl = tk.Label(row, text=_tag + '视频 ' + str(i + 1), font=FONT_MAIN, bg=COLOR_PANEL,
                           fg=COLOR_TEXT, cursor='hand2')
            lbl.pack(side='left', padx=(0, 10))
            lbl.bind('<Enter>', lambda e, u=url: self._show_video_preview(u))
            lbl.bind('<Leave>', lambda e: self._stop_video_preview())
            # 2026-08-21 删除按钮：删除历史 + 本地文件同步删除（播放/下载按钮已移除——
            # 下载自动完成，播放=鼠标放到画面上自动播放）
            b3 = tk.Button(row, text='🗑 删除', font=('微软雅黑', 9), bg='#F5F5F5',
                           fg='#C0392B', relief='solid', bd=1, highlightbackground='#E0C0C0',
                           command=lambda u=url: self._delete_video_history_item(u))
            b3.pack(side='left')
            self.video_history_videos.append(url)
        # 2026-08-21 需求3：批量生成中 → 列表顶部渲染"正在生成"跑马灯进度行
        if getattr(self, '_sb_batch_in_progress', False):
            self._render_video_progress_marquee()

    def _video_thumb_for(self, url):
        """2026-08-21 视频首帧缩略图：预览帧目录第一张 PNG 缩放到 160x90；无帧返回 None"""
        try:
            _frames = (getattr(self, '_video_preview_frames', {}) or {}).get(url, '')
            if not _frames or not os.path.isdir(_frames):
                return None
            _fl = sorted(f for f in os.listdir(_frames) if f.lower().endswith('.png'))
            if not _fl:
                return None
            from PIL import ImageTk
            _img = Image.open(os.path.join(_frames, _fl[0])).convert('RGB')
            _img.thumbnail((160, 90), Image.LANCZOS)
            return ImageTk.PhotoImage(_img)
        except Exception:
            return None

    def _delete_video_history_item(self, url):
        """2026-08-21 删除视频历史条目：移除历史 + 本地文件同步删除（videos/ + 尾帧）"""
        if not url:
            return
        _local = ''
        try:
            _local = (getattr(self, '_video_local_paths', {}) or {}).get(url, '')
        except Exception:
            _local = ''
        _msg = '确定删除该视频历史记录？'
        if _local and os.path.exists(_local):
            _msg = '确定删除该视频？\n将同时删除本地保存的文件：\n' + os.path.basename(_local)
        elif getattr(self, '_video_local_paths', None):
            _msg = '确定删除该视频历史记录？'
        if not messagebox.askyesno('删除视频', _msg, icon='warning'):
            return
        # 1) 移除历史
        try:
            if url in self.video_history:
                self.video_history.remove(url)
        except Exception:
            pass
        # 2) 删除本地视频文件
        _deleted = []
        try:
            if _local and os.path.exists(_local):
                os.remove(_local)
                _deleted.append(_local)
        except Exception as e:
            self.ctx.log('\n[系统日志] 删除本地视频失败: %s\n' % e)
        # 3) 清理路径映射
        try:
            if hasattr(self, '_video_local_paths') and self._video_local_paths and url in self._video_local_paths:
                self._video_local_paths.pop(url, None)
        except Exception:
            pass
        # 4) 清理预览帧目录（项目/assets/video_previews/分镜N/）
        try:
            _pf = ''
            try:
                _pf = (getattr(self, '_video_preview_frames', {}) or {}).pop(url, '')
            except Exception:
                _pf = ''
            if _pf and os.path.isdir(_pf):
                import glob as _gl
                for _ff in _gl.glob(os.path.join(_pf, '*.png')):
                    try:
                        os.remove(_ff)
                    except Exception:
                        pass
                try:
                    os.rmdir(_pf)
                except Exception:
                    pass
        except Exception:
            pass
        # 5) 删除对应尾帧（由本地文件名"分镜N_xxx.mp4"反推分镜号）
        try:
            if _local:
                _bn = os.path.basename(_local)
                _m = re.match(r'^分镜(\d+)', _bn)
                if _m:
                    _tf = os.path.join(self._tail_frames_dir(), "分镜%s.png" % _m.group(1))
                    if os.path.exists(_tf):
                        os.remove(_tf)
                        _deleted.append(_tf)
        except Exception:
            pass
        self._stop_video_preview()
        self._update_video_history_ui()
        self._show_toast('视频已删除' + ('（本地文件已删除）' if _deleted else ''), 'success')
        # 保存项目（删除状态持久化）
        try:
            self._save_project()
        except Exception:
            pass

    def _render_video_progress_marquee(self):
        """2026-08-21 批量生成视频时：视频历史顶部显示跑马灯进度行（当前分镜/总数 + 动画）"""
        try:
            total = len(getattr(self, '_sb_batch_prompts', []) or [])
            cur = getattr(self, '_sb_batch_index', 0)
            # 清除旧的跑马灯
            try:
                if getattr(self, '_vid_marquee_lbl', None) is not None:
                    self._vid_marquee_lbl.destroy()
                    self._vid_marquee_lbl = None
            except Exception:
                pass
            row = tk.Frame(self.frame_vid_history_inner, bg=COLOR_PANEL)
            row.pack(fill='x', padx=4, pady=2, before=self.frame_vid_history_inner.winfo_children()[0] if self.frame_vid_history_inner.winfo_children() else None)
            # 先移除 before 参数的重试：用 pack 顺序——插到最前
            try:
                row.pack_forget()
                row.pack(fill='x', padx=4, pady=2, side='top')
            except Exception:
                row.pack(fill='x', padx=4, pady=2)
            _done = getattr(self, '_story_batch_done', 0)
            _fail = getattr(self, '_story_batch_fail_count', 0)
            lbl = tk.Label(row, text='', font=('微软雅黑', 9, 'bold'), bg=COLOR_PANEL,
                           fg=COLOR_ACCENT_DARK)
            lbl.pack(side='left', padx=(0, 10))
            self._vid_marquee_lbl = lbl
            self._vid_marquee_frame = row
            self._vid_marquee_step = 0
            self._vid_marquee_after = None

            def _tick():
                try:
                    if not getattr(self, '_sb_batch_in_progress', False):
                        try:
                            if self._vid_marquee_lbl is not None:
                                self._vid_marquee_lbl.destroy()
                            if self._vid_marquee_frame is not None:
                                self._vid_marquee_frame.destroy()
                            self._vid_marquee_lbl = None
                            self._vid_marquee_frame = None
                        except Exception:
                            pass
                        return
                    cur2 = getattr(self, '_sb_batch_index', 0)
                    done2 = getattr(self, '_story_batch_done', 0)
                    fail2 = getattr(self, '_story_batch_fail_count', 0)
                    step = getattr(self, '_vid_marquee_step', 0)
                    dots = '.' * (step % 4)
                    pct = int(done2 * 100.0 / total) if total else 0
                    txt = ('⏳ 正在生成 分镜 %s/%s%s | 已完成 %s · 失败 %s (%d%%)'
                           % (cur2, total, dots, done2, fail2, pct))
                    self._vid_marquee_lbl.config(text=txt)
                    self._vid_marquee_step = step + 1
                    self._vid_marquee_after = self.root.after(500, _tick)
                except Exception:
                    pass
            _tick()
        except Exception:
            pass

    def _stop_video_progress_marquee(self):
        """2026-08-21 停止跑马灯并移除"""
        try:
            if getattr(self, '_vid_marquee_after', None):
                try:
                    self.root.after_cancel(self._vid_marquee_after)
                except Exception:
                    pass
                self._vid_marquee_after = None
            if getattr(self, '_vid_marquee_lbl', None) is not None:
                try:
                    self._vid_marquee_lbl.destroy()
                except Exception:
                    pass
                self._vid_marquee_lbl = None
            if getattr(self, '_vid_marquee_frame', None) is not None:
                try:
                    self._vid_marquee_frame.destroy()
                except Exception:
                    pass
                self._vid_marquee_frame = None
        except Exception:
            pass

    # ============ 2026-08-21 视频 hover 预览（ffmpeg 抽帧 + PIL 循环，无 opencv）============
    def _show_video_preview(self, url):
        """鼠标悬停视频 → 弹固定尺寸小窗播放预览帧（PIL 循环）。优先本地已保存视频的预览帧。"""
        try:
            self._stop_video_preview()
            if not url:
                return
            # ① 有正式本地文件（videos/ 目录已自动保存）
            _formal = ''
            try:
                _formal = (getattr(self, '_video_local_paths', {}) or {}).get(url, '')
                if _formal and not os.path.exists(_formal):
                    _formal = ''
            except Exception:
                _formal = ''
            if _formal:
                # 预览帧已就绪 → 直接播放（秒开）
                _frames = (getattr(self, '_video_preview_frames', {}) or {}).get(url, '')
                if _frames and os.path.isdir(_frames):
                    _fl = [f for f in os.listdir(_frames) if f.lower().endswith('.png')]
                    if _fl:
                        self._play_preview_frames(_frames)
                        return
                # 帧未就绪 → 显示"加载中"，后台抽帧
                self._preview_hover_active = True
                self._preview_win = tk.Toplevel(self.root)
                self._preview_win.overrideredirect(True)
                self._preview_win.attributes('-topmost', True)
                self._preview_win.configure(bg='#111111')
                self._preview_lbl = tk.Label(self._preview_win, text='⏳ 正在生成预览...', fg='white',
                                             bg='#111111', font=('微软雅黑', 9), width=30, height=5)
                self._preview_lbl.pack()
                mx, my = self.root.winfo_pointerxy()
                self._preview_win.geometry('+%d+%d' % (mx + 15, my + 15))
                _sb = 0
                try:
                    _bn = os.path.basename(_formal)
                    _m = re.match(r'^分镜(\d+)', _bn)
                    if _m:
                        _sb = int(_m.group(1))
                except Exception:
                    _sb = 0
                threading.Thread(target=self._extract_preview_frames, args=(url, _formal, _sb), daemon=True).start()
                return
            # ② 无本地文件（罕见，理论上都已自动保存）→ 显示"加载中"并后台下载到临时缓存
            self._preview_hover_active = True
            self._preview_win = tk.Toplevel(self.root)
            self._preview_win.overrideredirect(True)
            self._preview_win.attributes('-topmost', True)
            self._preview_win.configure(bg='#111111')
            self._preview_lbl = tk.Label(self._preview_win, text='⏳ 加载预览中...', fg='white',
                                         bg='#111111', font=('微软雅黑', 9), width=30, height=5)
            self._preview_lbl.pack()
            mx, my = self.root.winfo_pointerxy()
            self._preview_win.geometry('+%d+%d' % (mx + 15, my + 15))
            threading.Thread(target=self._download_video_for_preview, args=(url,), daemon=True).start()
        except Exception:
            pass

    def _download_video_for_preview(self, url):
        """兜底：无本地文件时下载到临时缓存并抽帧（正常流程不会走到这里）"""
        try:
            tmp_dir = os.path.join(os.environ.get('TEMP', os.getcwd()), 'CineMaster_Videos')
            os.makedirs(tmp_dir, exist_ok=True)
            tmp_path = os.path.join(tmp_dir, 'preview_' + str(int(time.time() * 1000)) + '.mp4')
            resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=120, verify=False)
            resp.raise_for_status()
            with open(tmp_path, 'wb') as f:
                f.write(resp.content)
            _sb = int(time.time() * 1000) % 100000
            self._extract_preview_frames(url, tmp_path, _sb)
            # 抽帧后若鼠标仍悬停 → 播放（_extract_preview_frames 内部已处理）
        except Exception:
            try:
                self._close_preview_win()
            except Exception:
                pass

    def _play_preview_frames(self, frames_dir):
        """用 PIL 循环播放预览帧（固定 360x202，主线程 after 切换，无后台线程）"""
        try:
            self._stop_video_preview()
            if not frames_dir or not os.path.isdir(frames_dir):
                return
            _files = sorted([os.path.join(frames_dir, f) for f in os.listdir(frames_dir)
                             if f.lower().endswith('.png')])
            if not _files:
                return
            self._preview_hover_active = True
            # 一次性加载所有帧到内存（24 张 360x202 ≈ 7MB，可接受）
            _photos = []
            for _f in _files:
                try:
                    _img = Image.open(_f).convert('RGB')
                    _photos.append(ImageTk.PhotoImage(_img))
                except Exception:
                    pass
            if not _photos:
                return
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes('-topmost', True)
            win.configure(bg='#111111')
            lbl = tk.Label(win, bg='#111111', borderwidth=0, highlightthickness=0)
            lbl.pack()
            mx, my = self.root.winfo_pointerxy()
            # 固定尺寸窗口（帧本身 360x202，不随视频比例跳动）
            win.geometry('360x202+%d+%d' % (mx + 15, my + 15))
            self._preview_win = win
            self._preview_lbl = lbl
            self._preview_photos = _photos
            self._preview_frame_idx = 0
            self._preview_stop = False
            self._preview_after = None
            self._preview_tick()
        except Exception:
            pass

    def _preview_tick(self):
        """主线程定时切换预览帧（200ms/帧 ≈ 5fps）"""
        try:
            if getattr(self, '_preview_stop', False):
                return
            _photos = getattr(self, '_preview_photos', []) or []
            if not _photos:
                return
            _idx = getattr(self, '_preview_frame_idx', 0) % len(_photos)
            self._preview_frame_idx = _idx + 1
            if getattr(self, '_preview_lbl', None) is not None:
                self._preview_lbl.configure(image=_photos[_idx])
                self._preview_lbl.image = _photos[_idx]
            self._preview_after = self.root.after(200, self._preview_tick)
        except Exception:
            pass

    def _stop_video_preview(self):
        """停止预览并关闭窗口"""
        try:
            self._preview_stop = True
            self._preview_hover_active = False
            # 取消 after 定时器（PIL 帧循环用）
            if getattr(self, '_preview_after', None) is not None:
                try:
                    self.root.after_cancel(self._preview_after)
                except Exception:
                    pass
                self._preview_after = None
        except Exception:
            pass
        try:
            self._close_preview_win()
        except Exception:
            pass

    def _close_preview_win(self):
        try:
            if getattr(self, '_preview_win', None) is not None:
                try:
                    self._preview_win.destroy()
                except Exception:
                    pass
                self._preview_win = None
        except Exception:
            pass

    def _download_specific_video(self, url):
        # 2026-08-21 优先本地已保存文件：直接复制（无需联网）
        _local = ''
        try:
            _local = (getattr(self, '_video_local_paths', {}) or {}).get(url, '')
            if _local and not os.path.exists(_local):
                _local = ''
        except Exception:
            _local = ''
        path = filedialog.asksaveasfilename(defaultextension='.mp4',
                                            filetypes=[('MP4 视频', '*.mp4'), ('所有文件', '*.*')],
                                            title='保存视频')
        if not path:
            return
        try:
            if _local:
                import shutil as _sh
                _sh.copyfile(_local, path)
            else:
                resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=120, verify=False)
                with open(path, 'wb') as f:
                    f.write(resp.content)
            self._show_toast('视频已保存', 'success')
        except Exception as e:
            messagebox.showerror('下载失败', '错误详情: ' + str(e))

    def _play_specific_video(self, url):
        # 2026-08-21 优先本地已保存文件：直接打开（无需下载）
        _local = ''
        try:
            _local = (getattr(self, '_video_local_paths', {}) or {}).get(url, '')
            if _local and not os.path.exists(_local):
                _local = ''
        except Exception:
            _local = ''
        if _local:
            try:
                if sys.platform == 'win32':
                    os.startfile(_local)
                elif sys.platform == 'darwin':
                    import subprocess
                    subprocess.Popen(['open', _local])
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', _local])
            except Exception as e:
                messagebox.showerror('播放失败', '错误详情: ' + str(e))
            return
        # 下载放到后台线程，避免阻塞界面
        def _worker():
            try:
                tmp_dir = os.path.join(os.environ.get('TEMP', os.getcwd()), 'CineMaster_Videos')
                os.makedirs(tmp_dir, exist_ok=True)
                tmp_path = os.path.join(tmp_dir, 'video_' + str(int(time.time() * 1000)) + '.mp4')
                resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=120, verify=False)
                with open(tmp_path, 'wb') as f:
                    f.write(resp.content)
                if sys.platform == 'win32':
                    os.startfile(tmp_path)
                elif sys.platform == 'darwin':
                    import subprocess
                    subprocess.Popen(['open', tmp_path])
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', tmp_path])
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror('播放失败', '错误详情: ' + str(e)))
        threading.Thread(target=_worker, daemon=True).start()

    # ============ 其他 ============
    def _copy_all_text(self):
        try:
            text = self.text_widgets.get('all').get('1.0', tk.END)
        except Exception:
            text = ''
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._show_toast('全文已复制到剪贴板', 'success')

    def _show_toast(self, msg, kind='success'):
        try:
            toast = tk.Toplevel(self.root)
            toast.overrideredirect(True)
            toast.attributes('-topmost', True)
            toast.configure(bg=COLOR_SUCCESS if kind == 'success' else (COLOR_ACCENT if kind == 'info' else COLOR_DANGER))
            lbl = tk.Label(toast, text=msg, font=FONT_MAIN, fg='white',
                           bg=COLOR_SUCCESS if kind == 'success' else (COLOR_ACCENT if kind == 'info' else COLOR_DANGER),
                           padx=16, pady=8)
            lbl.pack()
            toast.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - toast.winfo_width()) // 2
            y = self.root.winfo_rooty() + self.root.winfo_height() - toast.winfo_height() - 60
            toast.geometry('+' + str(x) + '+' + str(y))
            self._fade_out_toast(toast, 1.0)
        except Exception:
            pass

    def _fade_out_toast(self, toast, alpha):
        try:
            if alpha > 0:
                toast.attributes('-alpha', alpha)
                self.root.after(50, lambda: self._fade_out_toast(toast, alpha - 0.1))
            else:
                toast.destroy()
        except Exception:
            pass

    def _draw_watermark(self):
        try:
            self.canvas_watermark.delete('all')
            self.canvas_watermark.create_text(10, 12, anchor='w', text=APP_NAME,
                                              font=('微软雅黑', 9), fill='#D0D0D0')
        except Exception:
            pass

    # ============ 配置读写 ============
    def _get_api_config(self):
        cfg = {
            'api_key': self.entry_api_key.get().strip(),
            'base_url': self.entry_base_url.get().strip(),
            'model_name': self.combo_text_model.get().strip(),
            'media_api_key': self.entry_media_api_key.get().strip(),
            'media_base_url': self.entry_media_base_url.get().strip(),
            'img_model': self.combo_img_model.get().strip(),
            'vid_model': self.combo_vid_model.get().strip(),
        }
        # 2026-08-21 兜底：UI 控件为空时（供应商回填未生效/旧项目），
        # 从 项目 vendors 或 config.json global_vendors 按角色 id 取文本/媒体供应商配置，
        # 根治"生成第一步卡死（拿不到 API key）"问题。
        try:
            _tv = None
            _mv = None
            _tid = ''
            _mid = ''
            if self.current_project:
                _tid = self.current_project.get("text_vendor_id") or ''
                _mid = self.current_project.get("media_vendor_id") or ''
                _pvs = self.current_project.get("vendors") or []
                _tv = next((v for v in _pvs if v.get("id") == _tid), None)
                _mv = next((v for v in _pvs if v.get("id") == _mid), None)
            # 项目里没有 → 回退 config.json 全局供应商
            if not _tv or not _mv:
                _gv = (self.current_config or {}).get("global_vendors") or []
                if isinstance(_gv, list):
                    if not _tv:
                        _tid2 = _tid or (self.current_config or {}).get("global_text_vendor_id") or ''
                        _tv = next((v for v in _gv if v.get("id") == _tid2), None)
                    if not _mv:
                        _mid2 = _mid or (self.current_config or {}).get("global_media_vendor_id") or ''
                        _mv = next((v for v in _gv if v.get("id") == _mid2), None)
            # 文本供应商回填
            if _tv and not cfg.get('api_key'):
                cfg['api_key'] = (_tv.get("api_key") or '').strip()
            if _tv and not cfg.get('base_url'):
                cfg['base_url'] = (_tv.get("base_url") or '').strip()
            if _tv and not cfg.get('model_name'):
                _tm = next((m for m in _tv.get("models", []) if m.get("type") == "text"), None)
                if _tm:
                    cfg['model_name'] = (_tm.get("name") or '').strip()
            # 媒体供应商回填
            if _mv:
                if not cfg.get('media_api_key'):
                    cfg['media_api_key'] = (_mv.get("api_key") or '').strip()
                if not cfg.get('media_base_url'):
                    cfg['media_base_url'] = (_mv.get("base_url") or '').strip()
                _img_m = next((m for m in _mv.get("models", []) if m.get("type") == "image"), None)
                _vid_m = next((m for m in _mv.get("models", []) if m.get("type") == "video"), None)
                if not cfg.get('img_model') and _img_m:
                    cfg['img_model'] = (_img_m.get("name") or '').strip()
                if not cfg.get('vid_model') and _vid_m:
                    cfg['vid_model'] = (_vid_m.get("name") or '').strip()
                cfg['media_vendor_type'] = (_mv.get("type") or '')
        except Exception:
            pass
        # 显式供应商类型标记（comfyui / openai / 其他），供生成模块路由判断
        mv = None
        if self.current_project:
            mv = next((v for v in self.current_project.get("vendors", [])
                       if v.get("id") == self.current_project.get("media_vendor_id")), None)
        cfg['media_vendor_type'] = (mv or {}).get("type", "") if mv else ""
        # ComfyUI 公网地址自动转 https：AutoDL 公网服务必须 https（http 直连 400 plain HTTP to HTTPS port）
        # 本地地址（127.0.0.1/localhost/内网IP）保持 http 不变
        try:
            _mb = (cfg.get('media_base_url') or '').strip()
            if _mb and _mb.startswith('http://'):
                _host = _mb.split('://', 1)[1].split('/', 1)[0].split(':')[0]
                _is_public = _host and _host not in ('127.0.0.1', 'localhost', '0.0.0.0') and not _host.startswith(('10.', '192.168.', '172.'))
                if _is_public:
                    cfg['media_base_url'] = 'https://' + _mb.split('://', 1)[1]
        except Exception:
            pass
        return cfg

    def _save_config(self):
        cfg = self._get_api_config()
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            self._show_toast('配置已保存', 'success')
        except Exception as e:
            messagebox.showerror('保存失败', str(e))

    def _load_config_to_ui(self):
        cfg = self.current_config
        self.entry_api_key.delete(0, tk.END)
        self.entry_api_key.insert(0, cfg.get('api_key', ''))
        self.entry_base_url.delete(0, tk.END)
        self.entry_base_url.insert(0, cfg.get('base_url', ''))
        self.combo_text_model.delete(0, tk.END)
        self.combo_text_model.insert(0, cfg.get('model_name', ''))
        self.entry_media_api_key.delete(0, tk.END)
        self.entry_media_api_key.insert(0, cfg.get('media_api_key', ''))
        self.entry_media_base_url.delete(0, tk.END)
        self.entry_media_base_url.insert(0, cfg.get('media_base_url', ''))
        self.combo_img_model.delete(0, tk.END)
        self.combo_img_model.insert(0, cfg.get('img_model', ''))
        self.combo_vid_model.delete(0, tk.END)
        self.combo_vid_model.insert(0, cfg.get('vid_model', ''))
        # 全局风格恢复（项目保存时记录；无则默认写实电影）
        try:
            _gs = cfg.get('global_style') or DEFAULT_VIDEO_STYLE
            if _gs in VIDEO_STYLE_PRESETS and hasattr(self, 'combo_global_style'):
                self._style_var.set(_gs)
            if hasattr(self, 'label_vid_style'):
                self.label_vid_style.config(text=_gs if _gs in VIDEO_STYLE_PRESETS else DEFAULT_VIDEO_STYLE)
        except Exception:
            pass


# ================= 程序入口 =================
def main():
    # 兼容旧调用入口：root = tk.Tk(); app = CineMasterUI(root)
    import tkinter as tk
    import traceback as _tb
    import os as _os
    _LOG = _os.path.join(_os.environ.get('TEMP', '.'), 'wave_license_debug.log')
    def _log(msg):
        try:
            with open(_LOG, 'a', encoding='utf-8') as _f:
                _f.write(msg + '\n')
        except Exception:
            pass
    _log('=== main 启动 ===')
    root = tk.Tk()
    app = CineMasterUI(root)
    _log('UI 构建完成')
    # 激活检查：未激活/已过期/机器码不符 → 隐藏主界面，强制弹出激活窗口（激活成功才显示）
    try:
        from skills.license_guard import is_activated
        _log('import license_guard OK')
        _activated = is_activated()
        _log('is_activated = %r' % _activated)
        if not _activated:
            root.withdraw()  # 隐藏主窗口
            _log('root.withdraw 完成')
            def _show_license():
                try:
                    _log('_show_license 回调执行')
                    root.deiconify()  # 确保主窗口存在（对话框作为 Toplevel 置顶）
                    root.withdraw()   # 再隐藏，只留激活对话框
                    _log('调用 _show_license_dialog')
                    app._show_license_dialog(blocking=True)
                    _log('_show_license_dialog 返回')
                except Exception as _e:
                    _log('_show_license 异常: %s' % _tb.format_exc())
            root.after(200, _show_license)
            _log('root.after 已注册')
    except Exception:
        _log('激活检查异常: %s' % _tb.format_exc())
    # 本地控制接口（OpenClaw/QQ 机器人遥控，2026-08-20 新增；端口可在 config.json 的 control_port 覆盖）
    try:
        if ControlServer is not None:
            _port = 8712
            try:
                _cfg = load_config()
                _port = int((_cfg or {}).get('control_port', 8712) or 8712)
            except Exception:
                pass
            _cs = ControlServer(app, port=_port)
            if _cs.start():
                app._ctrl_port = _port
                app.ctrl_server = _cs
                _log('控制接口已启动: http://127.0.0.1:%d' % _port)
            else:
                _log('控制接口启动失败（端口 %d 可能被占用）' % _port)
    except Exception:
        _log('控制接口启动异常: %s' % _tb.format_exc())
    # QQ 机器人桥接（进程内模式，2026-08-20 新增；未启用/未配置时跳过，不影响主程序）
    try:
        _qq_cfg2 = (load_config() or {}).get('qq_bot', {}) or {}
        if _qq_cfg2.get('enabled') and _qq_cfg2.get('appid'):
            # 若配置了 MiniMax key，先初始化 OpenClaw（客户自己的 key）
            try:
                _adl_cfg2 = (load_config() or {}).get('autodl', {}) or {}
                _mm_key = (_adl_cfg2 or {}).get('minimax_key', '')
                if _mm_key:
                    from openclaw_launcher import setup_openclaw, start_gateway
                    _ok, _msg = setup_openclaw(_mm_key)
                    _log('OpenClaw 配置: %s' % _msg)
                    if _ok:
                        start_gateway(_mm_key)
                        _log('OpenClaw gateway 已启动')
            except Exception:
                _log('OpenClaw 初始化异常: %s' % _tb.format_exc())
            from qq_bridge import run_bot_internal
            threading.Thread(target=run_bot_internal, args=(_qq_cfg2, app), daemon=True).start()
            _log('QQ 机器人桥接已启动')
        else:
            _log('QQ 机器人未启用（配置页「AI 遥控」可开启）')
    except Exception:
        _log('QQ 桥接启动异常: %s' % _tb.format_exc())
    # 2026-08-21 需求2：批量生成按钮 3 分钟超时自动恢复看门狗
    try:
        app._start_btn_timeout_watch()
        _log('按钮超时看门狗已启动')
    except Exception:
        pass
    root.mainloop()
    return app

if __name__ == '__main__':
    main()
