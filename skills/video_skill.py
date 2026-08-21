# -*- coding: utf-8 -*-
"""skills.video_skill —— ComfyUI 云端版（LTX 2.3 图生视频 + 音频）

与 Toonflow 的「comfyui_local_ltx23_v6.ts」适配器逻辑 1:1 对齐：
  参考图 base64 → easy loadImageBase64 → LTX 2.3 i2v 管线（含音频）→ SaveVideo mp4。
方法签名与原方舟版完全一致（execute_generation），仅当媒体供应商为 ComfyUI
（vid_model 以 comfyui 开头 或 base_url 含 8188）时走本流程。
"""
import json, base64, time, random, os
import requests
# 公网 HTTPS（AutoDL 自定义服务自签证书）时关闭证书校验并抑制警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from skills.base_skill import BaseSkill

# 统一的请求参数：AutoDL 自定义服务是 HTTPS+自签证书，必须 verify=False
REQ_KW = {"verify": False}

DEFAULT_BASE = "http://127.0.0.1:8188"

# ── Wan 2.2 i2v 14B 720P 工作流（已弃用 2026-08-06：AutoDL 实例无 wan2.2_i2v 模型，全部改用 MiniMax H3）──
# WORKFLOW_TEMPLATE = {
#     "1": {"inputs": {"unet_name": "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}, "class_type": "UNETLoader"},
#     "2": {"inputs": {"unet_name": "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}, "class_type": "UNETLoader"},
#     "3": {"inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}, "class_type": "CLIPLoader"},
#     "4": {"inputs": {"vae_name": "wan_2.1_vae.safetensors"}, "class_type": "VAELoader"},
#     "5": {"inputs": {"text": "", "clip": ["3", 0]}, "class_type": "CLIPTextEncode"},
#     "6": {"inputs": {"text": "", "clip": ["3", 0]}, "class_type": "CLIPTextEncode"},
#     "7": {"inputs": {"positive": ["5", 0], "negative": ["6", 0], "vae": ["4", 0], "width": 1280, "height": 720, "length": 81, "batch_size": 1, "start_image": ["16", 0]}, "class_type": "WanImageToVideo"},
#     "8": {"inputs": {"model": ["1", 0], "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["7", 2], "add_noise": True, "noise_seed": 0, "steps": 20, "cfg": 3.5, "sampler_name": "euler", "scheduler": "simple", "start_at_step": 0, "end_at_step": 10, "return_with_leftover_noise": True}, "class_type": "KSamplerAdvanced"},
#     "9": {"inputs": {"model": ["2", 0], "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["8", 0], "add_noise": False, "noise_seed": 0, "steps": 20, "cfg": 3.5, "sampler_name": "euler", "scheduler": "simple", "start_at_step": 10, "end_at_step": 10000, "return_with_leftover_noise": False}, "class_type": "KSamplerAdvanced"},
#     "10": {"inputs": {"samples": ["9", 0], "vae": ["4", 0]}, "class_type": "VAEDecode"},
#     "11": {"inputs": {"fps": 16, "images": ["10", 0]}, "class_type": "CreateVideo"},
#     "12": {"inputs": {"filename_prefix": "video/Wan2.2_i2v", "format": "mp4", "codec": "h264", "video": ["11", 0]}, "class_type": "SaveVideo"},
#     "16": {"inputs": {"base64_data": "", "image_output": "Preview", "save_prefix": "ComfyUI"}, "class_type": "easy loadImageBase64"},
# }

# ── MiniMax H3 多图参考生视频工作流（U04 加速版结构）──
# 核心：MiniMaxH3ReferenceToVideo（prompt + 多图 ref + 视频/音频双 VAE + 采样 → SaveVideo）
# 特点：① Qwen3VL-32B 编码器原生支持中文提示词（直接拼中文，无需翻译成英文）
#       ② 视频+音频联合生成（原生立体声，audio_vae 必填）
#       ③ 多图参考最多 9 张（ref_images.ref_image_0~8，角色/场景/道具全进）
#       ④ 帧数 = 17k+5 网格（24fps；124≈5秒，训练区间 124~362≈5~15秒）
H3_WORKFLOW_TEMPLATE = {
    "92":  {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video/H3_i2v", "format": "auto", "codec": "auto", "video": ["130", 0]}},
    "119": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
    "120": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
    "121": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["125", 0], "vae": ["120", 0]}},
    "122": {"class_type": "VAEDecode", "inputs": {"samples": ["125", 0], "vae": ["119", 0]}},
    "123": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}},
    "124": {"class_type": "BasicScheduler", "inputs": {"scheduler": "simple", "steps": 25, "denoise": 1, "model": ["148", 0]}},
    "125": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["129", 0], "guider": ["126", 0], "sampler": ["123", 0], "sigmas": ["124", 0], "latent_image": ["136", 1]}},
    "126": {"class_type": "BasicGuider", "inputs": {"model": ["148", 0], "conditioning": ["136", 0]}},
    "127": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax/minimax_h3_ref2va_int8_convrot.safetensors", "weight_dtype": "default"}},
    "128": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors", "type": "minimax", "device": "default"}},
    "129": {"class_type": "RandomNoise", "inputs": {"noise_seed": 0}},
    "130": {"class_type": "CreateVideo", "inputs": {"fps": 24, "bit_depth": 8, "images": ["122", 0], "audio": ["121", 0]}},
    "131": {"class_type": "ComfyMathExpression", "inputs": {"expression": "max(5, round(a * 24)) + (5 - (max(5, round(a * 24)) % 17)) % 17", "values.a": ["147", 0]}},
    "136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"prompt": ["146", 0], "width": ["145", 1], "height": ["145", 2], "length": ["131", 1], "ref_image_size": "match", "clip": ["128", 0], "vae": ["119", 0], "audio_vae": ["120", 0]}},
    "145": {"class_type": "WJILatentPreset", "inputs": {"预设分辨率": "自定义", "横竖对调": False, "批量大小": 1, "自定义宽": 864, "自定义高": 480, "缩放倍数": "32"}},
    "146": {"class_type": "CR Prompt Text", "inputs": {"prompt": ""}},
    "147": {"class_type": "PrimitiveFloat", "inputs": {"value": 10}},
    "148": {"class_type": "PathchSageAttentionKJ", "inputs": {"sage_attention": "auto", "allow_compile": False, "model": ["127", 0]}},
}
# H3 采样步数
H3_STEPS = 25
# H3 帧率（固定 24fps，模型按 17k+5 网格对齐）
H3_FPS = 24
# H3 最大参考图数（官方节点上限 9）
H3_MAX_REFS = 9
# 无 BGM 指令（2026-08-07 用户要求：不要背景音乐，保留道具音/世界环境音，BGM 用户后期自己添加）
# 2026-08-15 用户要求：禁环境人声——除非提示词明确写了"周围窃窃私语/低声议论"等才生成环境人声，
# 且环境人声必须用汉语普通话（严禁外语人声/外语语音）。
H3_NO_BGM_GUIDE = ("\n【声音要求】本视频严禁任何背景音乐、配乐、旋律、节奏打击乐或鼓点——包括武打/对抗/演武场景的激昂配乐也一律禁止。"
                   "全片只允许以下声音：①人物台词（若有）；②环境声与动作声（脚步声、衣袂翻动、风声、器物碰撞、鸟鸣、流水等自然/环境音）；③道具音。"
                   "【背景人声】默认禁止任何背景人声、环境人声——画面中除台词外不得出现任何人说话声、人群声、喧哗声、交谈声。"
                   "**唯一例外**：仅当提示词中明确写有「周围窃窃私语」「低声议论」「议论纷纷」等环境人声描述字样时，才允许生成轻微的环境人声（如远处细碎的窃窃私语声），"
                   "且该环境人声**必须是中国普通话的说话声**——窃窃私语/低声议论的内容必须用中文普通话发出（如\"在聊什么\"\"听说…\"等中文话音），"
                   "严禁任何外语发音（英语/日语/韩语/其他语言），严禁带外语口音，音量必须压到**极低**——如同远处几乎听不清的细碎耳语，音量不超过台词/环境声的20%，"
                   "作为极远处背景氛围存在，绝不能盖过人声，绝不能清晰可辨。"
                   "【语言铁律】无论本视频画面采用何种视觉风格（包括日系动漫/和风/欧美风等任何风格），所有说话声、人声、环境人声、背景人声必须全部使用中文普通话，"
                   "严禁因画面风格是日系动漫就把人声生成日语，严禁出现任何外语语音。"
                   "除台词和环境声外不得出现任何音乐性声音。"
                   "人物台词必须用标准普通话清晰念出，咬字清楚、语速自然，禁止含糊吞音。"
                   "本镜环境声类型与上一镜保持一致（如室内/室外/街市/战场），但环境声不得盖过人声。")
# 无台词版声音要求（2026-08-15：无台词分镜必须人物闭嘴沉默，禁止任何说话声/嘴部动作/环境人声）
H3_SILENT_GUIDE = ("\n【声音要求】本视频没有任何台词、没有任何人物说话声。"
                   "画面中所有人物必须全程闭嘴沉默，嘴巴闭合不动、不张嘴、不做说话口型、不发出任何说话声。"
                   "严禁任何人声、说话声、嘟囔声、呻吟声、叹息声、咳嗽声——人物不得发出任何发音。"
                   "【背景人声】默认禁止任何背景人声、环境人声——不得出现任何人说话声、人群声、交谈声。"
                   "**唯一例外**：仅当提示词中明确写有「周围窃窃私语」「低声议论」「议论纷纷」等环境人声描述字样时，才允许生成轻微的环境人声（如远处细碎的窃窃私语声），"
                   "且该环境人声**必须是中国普通话的说话声**——窃窃私语/低声议论的内容必须用中文普通话发出（如\"在聊什么\"\"听说…\"等中文话音），"
                   "严禁任何外语发音（英语/日语/韩语/其他语言），严禁带外语口音，音量必须压到**极低**——如同远处几乎听不清的细碎耳语，音量不超过环境声的20%，"
                   "作为极远处背景氛围存在，绝不能清晰可辨。"
                   "【语言铁律】无论本视频画面采用何种视觉风格（包括日系动漫/和风/欧美风等任何风格），所有说话声、人声、环境人声、背景人声必须全部使用中文普通话，"
                   "严禁因画面风格是日系动漫就把人声生成日语，严禁出现任何外语语音。"
                   "全片只允许以下声音：①环境声与动作声（脚步声、衣袂翻动、风声、器物碰撞、鸟鸣、流水等自然/环境音）；②道具音；③提示词明确写出的轻微环境人声。"
                   "严禁任何背景音乐、配乐、旋律、节奏打击乐或鼓点——包括武打/对抗/演武场景的激昂配乐也一律禁止。"
                   "本镜环境声类型与上一镜保持一致（如室内/室外/街市/战场）。")
# H3 模型名（区分 H3 流程）
H3_UNET = "minimax/minimax_h3_ref2va_int8_convrot.safetensors"
H3_CLIP = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
H3_VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
H3_AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
# H3 分辨率 → 宽高（AutoDL 4090 48G 实测：864x480 起步；1280x720 待实测显存余量）
H3_RES_MAP = {
    ("480p", "16:9"): (864, 480),
    ("480p", "9:16"): (480, 864),
    ("720p", "16:9"): (1280, 720),
    ("720p", "9:16"): (720, 1280),
    ("1080p", "16:9"): (1280, 720),
    ("1080p", "9:16"): (720, 1280),
}
H3_FALLBACK_RES = ("720p", "16:9")

# ── Wan 2.2 分辨率/帧率（已弃用，随 Wan2.2 分支一起注释）──
# RES_MAP = {
#     ("480p", "16:9"): (832, 480),
#     ("480p", "9:16"): (480, 832),
#     ("720p", "16:9"): (1280, 720),
#     ("720p", "9:16"): (720, 1280),
#     ("1080p", "16:9"): (1280, 720),
#     ("1080p", "9:16"): (720, 1280),
# }
# FALLBACK_RES = ("720p", "16:9")
# WAN_FPS = 16
# WAN_MAX_FRAMES = 121


def _is_comfy(api_config):
    # 显式供应商类型标记（UI 层传入），任意端口/IP 均可靠
    if str(api_config.get("media_vendor_type") or "").strip().lower() == "comfyui":
        return True
    vid_model = (api_config.get("vid_model") or "").strip().lower()
    if vid_model.startswith("comfyui"):
        return True
    base = (api_config.get("media_base_url") or "").strip().lower()
    return any(k in base for k in ("8188", "15794", "8800", "6006", "comfy", "seetacloud", "autodl"))


def _comfy_base(api_config):
    base = (api_config.get("media_base_url") or DEFAULT_BASE).strip().rstrip("/")
    # 协议头清洗：历史配置可能污染成 "http://https://..."（协议重复）→ 归一为单个协议
    import re as _re
    while True:
        m = _re.match(r'^(https?://)(https?://)', base)
        if not m:
            break
        base = base[len(m.group(1)):]
    # 公网 ComfyUI 地址 http → https（AutoDL 公网服务必须 https，http 直连 400；本地保持 http）
    try:
        if base.startswith('http://'):
            _host = base.split('://', 1)[1].split('/', 1)[0].split(':')[0]
            _is_public = _host and _host not in ('127.0.0.1', 'localhost', '0.0.0.0') and not _host.startswith(('10.', '192.168.', '172.'))
            if _is_public:
                base = 'https://' + base.split('://', 1)[1]
    except Exception:
        pass
    return base or DEFAULT_BASE


def _submit_and_wait(base, workflow, timeout=1200):
    """POST /prompt → 轮询 /history → 返回 outputs dict"""
    resp = requests.post(base + "/prompt",
                         json={"prompt": workflow, "client_id": "wave"}, timeout=30, **REQ_KW)
    resp.raise_for_status()
    pid = resp.json().get("prompt_id")
    if not pid:
        raise RuntimeError("ComfyUI 提交失败: " + resp.text[:300])
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(5)
        try:
            h = requests.get(base + "/history/" + pid, timeout=15, **REQ_KW)
            if h.status_code != 200:
                continue
            run = h.json().get(pid)
        except Exception:
            continue
        if not run:
            continue
        st = run.get("status", {})
        if st.get("status_str") in ("error", "failed"):
            raise RuntimeError("ComfyUI 执行失败: %s" % str(st.get("exception_message", st))[:500])
        if st.get("completed"):
            return run.get("outputs", {})
    raise TimeoutError("ComfyUI 视频生成超时（%s 秒）" % timeout)


def _output_url(base, outputs, node_id="75"):
    """从 outputs 取指定节点（默认 SaveVideo 75）的第一个文件 URL"""
    out = outputs.get(node_id) or {}
    for items in out.values():
        if not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict) and it.get("filename"):
                fn = it["filename"].replace(" ", "%20")
                sub = it.get("subfolder") or ""
                if sub:
                    sub = sub.replace(" ", "%20") + "/"
                typ = it.get("type", "output")
                return "%s/view?filename=%s&type=%s&subfolder=%s" % (base, fn, typ, sub)
    return None


class VideoSkill(BaseSkill):
    """ComfyUI 云端视频生成（LTX 2.3 图生视频 + 音频）"""

    MAX_REFS = 9  # 最多接收 9 张参考图（多图 → batch 起始帧引导）
    # 商用一致性模式：默认只用第 1 张参考图（角色图优先）做起始帧。
    # 多图 batch 起始帧会让 LTX 特征混合 → 人物变脸严重，单图一致性最好。
    # 需要多图引导时可改为 False（保留 ImageBatch 链拼逻辑）。
    SINGLE_REF_CONSISTENCY = True
    # LTXVPreprocess 图像压缩率（33=默认，压掉约2/3细节→面部崩；调低保留参考图细节）
    IMG_COMPRESSION = 10
    # 身份一致性引导句（拼到提示词末尾，约束 LTX 保持参考图人物形象）
    IDENTITY_GUIDE = (", same person as the reference image, keep the exact same face, "
                      "same facial features, same hairstyle, same outfit and colors, "
                      "stable identity, no facial deformation")
    # 首帧合成模式：用 flux2 以参考图（角色+场景）为参考，生成"角色在该场景中"的静态首帧，
    # 再以该首帧做 LTX 视频首帧 → 场景与人物双锁定。
    # 若 False：直接用参考图（第1张）做 LTX 首帧（场景图不会进画面）。
    FIRST_FRAME_GEN = True
    # flux2 首帧参考图数量（角色+场景，最多3张；参考越多越贴近，但可能引入特征混合）
    FRAME_REF_LIMIT = 3

    def execute_generation(self, prompt, api_config, duration, aspect_ratio, resolution, ref_urls):
        if not _is_comfy(api_config):
            raise RuntimeError("当前媒体供应商不是云端 ComfyUI（请将 ComfyUI 供应商设为媒体供应商）")
        base = _comfy_base(api_config)
        if not prompt:
            raise RuntimeError("缺少视频生成提示词")
        # ── 2026-08-06 起视频生成全部走 MiniMax H3（Wan2.2/LTX 分支已注释弃用）──
        return self._execute_h3(prompt, base, api_config, duration, aspect_ratio, resolution, ref_urls)
        # 以下是已弃用的 Wan2.2 流程（保留供参考，不再执行）
        # refs = [u for u in (ref_urls or []) if u][:self.MAX_REFS]
        # if not refs:
        #     raise RuntimeError("缺少参考图片（请先生成图片或在历史中选择参考图）")
        # # 首帧合成模式：参考图保留多张（角色+场景），由 flux2 合成首帧；不再截断为单图
        #
        # self.ctx.log("\n[系统日志] 正在下载 %d 张参考图并提交 ComfyUI 视频任务...\n" % len(refs))
        # self.ctx.push_ui_event("status", {
        #     "text": "", "btn_gen_vid": "disabled", "progress": True,
        # })
        # try:
        #     # 1. 下载全部参考图 → base64
        #     b64_list = []
        #     for u in refs:
        #         r = requests.get(u, timeout=60,
        #                          headers={"User-Agent": "Mozilla/5.0"})
        #         r.raise_for_status()
        #         b64_list.append(base64.b64encode(r.content).decode())
        #
        #     # 1.5 首帧合成：flux2 以参考图（角色+场景）为参考，生成"角色在该场景中"的静态首帧。
        #     #     成功 → 该首帧做 LTX 首帧（场景+人物双锁定）；失败 → 回退第 1 张参考图。
        #     first_b64 = b64_list[0]
        #     if getattr(self, "FIRST_FRAME_GEN", True):
        #         try:
        #             from skills import image_skill as _imgskill
        #             frame_refs = b64_list[:self.FRAME_REF_LIMIT]
        #             frame_prompt = prompt.rstrip()
        #             _fg = (", keep the same scene environment and layout as the reference images, "
        #                    "same person and outfit as the reference character, same camera framing")
        #             if _fg not in frame_prompt:
        #                 frame_prompt = frame_prompt + _fg
        #             frame_wf = _imgskill._build_img_workflow(frame_prompt, 1280, 720, frame_refs)
        #             fo = _imgskill._submit_and_wait(base, frame_wf, timeout=600)
        #             fu = _imgskill._output_url(base, fo, "195")
        #             if fu:
        #                 fr = requests.get(fu, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        #                 fr.raise_for_status()
        #                 first_b64 = base64.b64encode(fr.content).decode()
        #                 self.ctx.log("\n[系统日志] 首帧合成完成（角色+场景参考，共 %d 张）\n" % len(frame_refs))
        #         except Exception as _fe:
        #             self.ctx.log("\n[系统日志] 首帧合成失败，回退使用第1张参考图: %s\n" % _fe)
        #             first_b64 = b64_list[0]
        #
        #     # 2. 组装工作流（Wan 2.2 i2v）
        #     wf = json.loads(json.dumps(WORKFLOW_TEMPLATE))
        #     wf["16"] = {
        #         "class_type": "easy loadImageBase64",
        #         "inputs": {"base64_data": first_b64, "image_output": "Preview", "save_prefix": "ComfyUI"},
        #     }
        #     wf["5"]["inputs"]["text"] = prompt
        #     try:
        #         _guide = self.IDENTITY_GUIDE
        #         if _guide and _guide not in prompt:
        #             wf["5"]["inputs"]["text"] = prompt.rstrip() + _guide
        #     except Exception:
        #         pass
        #     wf["6"]["inputs"]["text"] = ""
        #     seconds = max(1, int(duration or 5))
        #     frames = min(seconds * WAN_FPS + 1, WAN_MAX_FRAMES)
        #     wf["7"]["inputs"]["length"] = frames
        #     res_key = str(resolution or "1080p").lower()
        #     ratio_key = str(aspect_ratio or "16:9")
        #     w, h = RES_MAP.get((res_key, ratio_key)) or RES_MAP.get(FALLBACK_RES)
        #     wf["7"]["inputs"]["width"] = w
        #     wf["7"]["inputs"]["height"] = h
        #     self.ctx.log("\n[系统日志] 视频参数：%s | %s | %sx%s | %d 帧（%.1f 秒）| Wan2.2 i2v 14B\n" % (
        #         ratio_key, res_key, w, h, frames, frames / WAN_FPS))
        #
        #     # 3. 提交 + 轮询
        #     outputs = _submit_and_wait(base, wf, timeout=1800)
        #     url = _output_url(base, outputs, "12")
        #     if not url:
        #         raise RuntimeError("未找到输出视频")
        #     self.ctx.push_ui_event("video_done", {"url": url})
        #     self.ctx.push_ui_event("status", {
        #         "text": "\n[系统日志] 视频生成成功（Wan 2.2）\n",
        #         "btn_gen_vid": "normal", "progress": False,
        #     })
        # except Exception as e:
        #     self.ctx.log("\n[系统日志] 视频生成异常: %s\n" % e)
        #     self.ctx.push_ui_event("video_failed", {"error": str(e)})
        #     self.ctx.push_ui_event("status", {
        #         "text": "\n[系统日志] 视频生成异常: %s\n" % e,
        #         "btn_gen_vid": "normal", "progress": False,
        #     })
        #     raise

    def _execute_h3(self, prompt, base, api_config, duration, aspect_ratio, resolution, ref_urls):
        """MiniMax H3 多图参考生视频（含原生立体声 + 分镜衔接 + 自定义音色）。

        与 Wan2.2 流程区别：
        - 提示词直接走 Qwen3VL-32B（原生支持中文，无需翻译成英文）
        - 多图参考（角色/场景/道具全进，最多 9 张），H3 自己处理参考关系
        - 视频+音频联合生成（原生立体声，audio_vae 必填）
        - 帧数 = 17k+5 网格（24fps；5 秒→124 帧，10 秒→244 帧，15 秒→362 帧）
        - 不需要首帧合成（H3 多图参考天然锁人物+场景）

        分镜衔接（2026-08-07 改为方案1+方案4：不再传整段视频帧）：
        - api_config['prev_video_url']：上一镜视频 URL → 上传 → 抽**最后一帧**作参考图
          （ref_images.ref_image_N，首帧衔接；2026-08-15 起不传上一镜音频——含台词人声会被 H3
          延续/复现到本镜 → 台词乱入+混合声污染念白含糊；声音由 H3 按提示词自生成）
        - 人物音色：2026-08-15 起不传（用户决定），H3 自己生成匹配音色
        - 提示词自动追加 H3_NO_BGM_GUIDE（无背景音乐，保留环境音效）
        """
        refs = [u for u in (ref_urls or []) if u][:H3_MAX_REFS]
        if not refs:
            raise RuntimeError("缺少参考图片（请先生成图片或在历史中选择参考图）")
        prev_video_url = (api_config.get("prev_video_url") or "").strip()
        # 2026-08-21 本地尾帧优先：app_ui 已把上一镜尾帧保存为本地文件并传入 prev_tail_frame，
        # 云实例重启/URL 失效时仍能衔接（比下载上一镜视频抽帧更稳）。
        prev_tail_frame = (api_config.get("prev_tail_frame") or "").strip()
        if prev_tail_frame and not os.path.exists(prev_tail_frame):
            prev_tail_frame = ""
        # 若有上一镜衔接（URL 或本地尾帧），参考图留 1 个位置给末帧图（refs 最多 8 张 + 末帧图 = 9 张）
        if (prev_video_url or prev_tail_frame) and len(refs) >= H3_MAX_REFS:
            refs = refs[:H3_MAX_REFS - 1]

        self.ctx.log("\n[系统日志] 正在下载 %d 张参考图并提交 MiniMax H3 视频任务（多图参考+原生立体声）...\n" % len(refs))
        if prev_video_url or prev_tail_frame:
            self.ctx.log("[系统日志] 分镜衔接：只传上一镜最后一帧（首帧衔接，不传音频防台词乱入）\n")
        self.ctx.push_ui_event("status", {
            "text": "", "btn_gen_vid": "disabled", "progress": True,
        })
        try:
            # 1. 下载全部参考图 → base64
            b64_list = []
            for u in refs:
                r = requests.get(u, timeout=60,
                                 headers={"User-Agent": "Mozilla/5.0"}, **REQ_KW)
                r.raise_for_status()
                b64_list.append(base64.b64encode(r.content).decode())

            # 2. 组装 H3 工作流
            wf = json.loads(json.dumps(H3_WORKFLOW_TEMPLATE))
            # 禁用缓存：批量生成时参考图/提示词常重复，ComfyUI 按输入哈希缓存会跳过执行
            # （分镜2-5 缓存命中 0 秒完成 → SaveVideo 无输出 → "未找到输出视频"）。
            # 在 H3 主节点加 ignore_cache + 参考图节点用唯一 ID。
            _uid = int(time.time() * 1000) % 100000
            # 提示词直接进 CR Prompt Text（146），Qwen3VL 原生支持中文
            wf["146"]["inputs"]["prompt"] = prompt
            # 随机种子（每次必不同 → 主节点不缓存）
            wf["129"]["inputs"]["noise_seed"] = random.randint(0, 10 ** 18)
            # H3 主节点强制不缓存（输入哈希相同也会重新执行）
            wf["136"]["execution"] = {"ignore_cache": True}
            wf["92"]["execution"] = {"ignore_cache": True}
            # 参考图（最多 9 张）→ ref_images.ref_image_N（节点 ID 带唯一后缀，防缓存）
            # 2026-08-15 修复分镜衔接：H3 的 ref_image_0 是首帧锚定槽位。
            #   有上一镜衔接时，ref_image_0 必须留给上一镜末帧图（下一镜从上一镜尾帧开始），
            #   普通参考图从 ref_image_1 开始排；无衔接时普通参考图从 ref_image_0 开始。
            _ref_offset = 1 if (prev_video_url or prev_tail_frame) else 0
            for i, b64 in enumerate(b64_list):
                key = "ref_images.ref_image_%d" % (i + _ref_offset)
                wf["%d_ref_%d" % (1000 + _uid, i)] = {
                    "class_type": "easy loadImageBase64",
                    "inputs": {"base64_data": b64, "image_output": "Preview", "save_prefix": "ComfyUI"},
                }
                wf["136"]["inputs"][key] = ["%d_ref_%d" % (1000 + _uid, i), 0]

            # 2.5 分镜衔接（方案1+方案4）：本地尾帧优先 → 直接进 ref_image_0 首帧锚定槽位；
            #     无本地尾帧时回退：下载上一镜视频 → 抽最后一帧作参考图（不传音频、不传视频帧）
            _prev_ok = False
            if prev_tail_frame:
                try:
                    with open(prev_tail_frame, "rb") as _f:
                        _tb64 = base64.b64encode(_f.read()).decode()
                    # 本地尾帧图 → ref_images.ref_image_0（首帧锚定槽位！2026-08-15 修复：
                    # H3 多图参考中 ref_image_0 是首帧，必须让上一镜末帧占首帧位，
                    # 下一镜才能从上一镜尾帧的姿态/位置开始，否则 H3 自由发挥导致分镜连不上）
                    wf["154t_%d" % _uid] = {"class_type": "easy loadImageBase64",
                                            "inputs": {"base64_data": _tb64, "image_output": "Preview",
                                                       "save_prefix": "ComfyUI"}}
                    wf["136"]["inputs"]["ref_images.ref_image_0"] = ["154t_%d" % _uid, 0]
                    _prev_ok = True
                    self.ctx.log("[系统日志] 上一镜本地尾帧已接入首帧位（ref_images.ref_image_0）\n")
                except Exception as _te:
                    self.ctx.log("[系统日志] 本地尾帧接入失败，回退视频抽帧: %s\n" % _te)
            if not _prev_ok and prev_video_url:
                try:
                    rv = requests.get(prev_video_url, timeout=90,
                                      headers={"User-Agent": "Mozilla/5.0"}, **REQ_KW)
                    rv.raise_for_status()
                    up_name = "prev_%d.mp4" % int(time.time())
                    requests.post(base + "/upload/image",
                                  files={"image": (up_name, rv.content, "video/mp4")}, timeout=60, **REQ_KW)
                    # VHS_VideoInfo 拿总帧数 → ComfyMathExpression 算末帧索引 → VHS_LoadVideo 取最后一帧
                    # （节点 ID 带 _uid 后缀防缓存）
                    # ⚠️ 输入名铁律（实测实例 object_info）：
                    #   - VHS_VideoInfo 必需输入 = video_info（VHS_VIDEOINFO 类型，来自 VHS_LoadVideo 输出 [3]），不是 video
                    #   - VHS_LoadVideo 输出 = [0]IMAGE [1]frame_count [2]audio [3]video_info
                    #   - ComfyMathExpression 输出 = [FLOAT, INT, BOOL]，取 [1]=INT 接 skip_first_frames
                    #   - ImageFromBatch 必需输入 = image（单数！不是 images）+ batch_index + length
                    # 流程：第一次 LoadVideo(取 video_info) → VideoInfo(loaded_frame_count[5]) → Math(a-1, INT)
                    #       → 第二次 LoadVideo(skip=末帧索引, cap=1) → ImageFromBatch(取唯一帧) + audio
                    wf["150f_%d" % _uid] = {"class_type": "VHS_LoadVideo",
                                 "inputs": {"video": up_name, "force_rate": 24,
                                            "custom_width": 0, "custom_height": 0,
                                            "frame_load_cap": 1, "skip_first_frames": 0,
                                            "select_every_nth": 1}}
                    wf["151_%d" % _uid] = {"class_type": "VHS_VideoInfo",
                                           "inputs": {"video_info": ["150f_%d" % _uid, 3]}}
                    wf["152_%d" % _uid] = {"class_type": "ComfyMathExpression",
                                 "inputs": {"expression": "a - 1", "values.a": ["151_%d" % _uid, 5]}}
                    wf["150_%d" % _uid] = {"class_type": "VHS_LoadVideo",
                                 "inputs": {"video": up_name, "force_rate": 24,
                                            "custom_width": 0, "custom_height": 0,
                                            "frame_load_cap": 1, "skip_first_frames": ["152_%d" % _uid, 1],
                                            "select_every_nth": 1}}
                    # 末帧图 → ref_images.ref_image_0（首帧锚定槽位！2026-08-15 修复：
                    # H3 多图参考中 ref_image_0 是首帧，必须让上一镜末帧占首帧位，
                    # 下一镜才能从上一镜尾帧的姿态/位置开始，否则 H3 自由发挥导致分镜连不上）
                    wf["154_%d" % _uid] = {"class_type": "ImageFromBatch",
                                 "inputs": {"image": ["150_%d" % _uid, 0], "batch_index": 0, "length": 1}}
                    wf["136"]["inputs"]["ref_images.ref_image_0"] = ["154_%d" % _uid, 0]
                    # 2026-08-15 用户决定：不传上一镜音频（含台词人声会被 H3 延续/复现到本镜
                    # → 台词乱入+混合声污染念白含糊），只传末帧图做画面衔接；声音由 H3 按提示词自生成。
                    self.ctx.log("[系统日志] 上一镜末帧已接入首帧位（ref_images.ref_image_0，不传音频防台词乱入）\n")
                except Exception as _ve:
                    self.ctx.log("[系统日志] 上一镜衔接接入失败，本镜按无衔接生成: %s\n" % _ve)
                    for _k in list(wf.keys()):
                        if _k in ("150_%d" % _uid, "151_%d" % _uid, "152_%d" % _uid, "154_%d" % _uid, "150f_%d" % _uid):
                            wf.pop(_k, None)
                    for _ki in list(wf["136"]["inputs"].keys()):
                        if _ki == "ref_images.ref_image_0":
                            wf["136"]["inputs"].pop(_ki, None)

            # 2.6 人物音色：2026-08-15 用户决定不传人物音色——H3 直接自己生成匹配音色，
            #     避免 preset 音色文件（纯音色无语义）干扰 H3 的语音生成质量。
            #     （原逻辑：本地音色文件 → 上传 → LoadAudio → ref_audios.ref_audio_N，已废弃）

            # 时长 → 帧数（17k+5 网格）
            seconds = max(1, int(duration or 5))
            wf["147"]["inputs"]["value"] = seconds
            # 分辨率
            res_key = str(resolution or "1080p").lower()
            ratio_key = str(aspect_ratio or "16:9")
            w, h = H3_RES_MAP.get((res_key, ratio_key)) or H3_RES_MAP.get(H3_FALLBACK_RES)
            wf["145"]["inputs"]["自定义宽"] = w
            wf["145"]["inputs"]["自定义高"] = h
            # 采样步数
            wf["124"]["inputs"]["steps"] = H3_STEPS
            self.ctx.log("\n[系统日志] H3 视频参数：%s | %s | %sx%s | %d 秒（24fps，17k+5 网格）| MiniMax H3 Ref2VA int8\n" % (
                ratio_key, res_key, w, h, seconds))

            # 3. 提交 + 轮询（H3 视频+音频联合生成，耗时更长，给 3600 秒）
            outputs = _submit_and_wait(base, wf, timeout=3600)
            url = _output_url(base, outputs, "92")
            if not url:
                raise RuntimeError("未找到输出视频")
            self.ctx.push_ui_event("video_done", {"url": url})
            self.ctx.push_ui_event("status", {
                "text": "\n[系统日志] 视频生成成功（MiniMax H3，多图参考+原生立体声）\n",
                "btn_gen_vid": "normal", "progress": False,
            })
        except Exception as e:
            self.ctx.log("\n[系统日志] H3 视频生成异常: %s\n" % e)
            self.ctx.push_ui_event("video_failed", {"error": str(e)})
            self.ctx.push_ui_event("status", {
                "text": "\n[系统日志] H3 视频生成异常: %s\n" % e,
                "btn_gen_vid": "normal", "progress": False,
            })
            raise
