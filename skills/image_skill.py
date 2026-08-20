# -*- coding: utf-8 -*-
"""skills.image_skill —— ComfyUI 云端版（Flux2-Klein 三图参考工作流）

与 Toonflow 的「三图参考.ts」适配器逻辑 1:1 对齐：
  0 参考图 → 纯文生图；1/2/3+ 参考图 → ReferenceLatent 多图参考。
方法签名与原方舟版完全一致（execute_batch_generation / generate_single_image），
仅当媒体供应商为 ComfyUI（img_model 以 comfyui 开头 或 base_url 含 8188）时走本流程。
"""
import json, base64, time, random
import requests
# 公网 HTTPS（AutoDL 自定义服务自签证书）时关闭证书校验并抑制警告
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from skills.base_skill import BaseSkill

# 统一的请求参数：AutoDL 自定义服务是 HTTPS+自签证书，必须 verify=False
REQ_KW = {"verify": False}

# ── 云端 ComfyUI 模型配置（对应 D:\Toonflaw工作流和模型 部署的模型文件）──
COMFY_CLIP = "qwen_3_8b_fp8mixed.safetensors"
COMFY_VAE = "flux2-vae.safetensors"
COMFY_UNET = "flux/flux-2-klein-9b-fp8.safetensors"  # 注意：实例模型在 diffusion_models/flux/ 子目录，必须带 flux/ 前缀
COMFY_STEPS = 6
COMFY_CFG = 1.0
COMFY_SAMPLER = "euler"
COMFY_SCHEDULER = "simple"
COMFY_DENOISE = 1.0
DEFAULT_BASE = "http://127.0.0.1:8188"

# ── 负面提示词（源自 CineMaster 角色一致性控制参数，2026-08-08 集成）──
# 所有 flux2 生图统一防畸形：肢体/手指/面部扭曲/低质渲染/卡通化
NEGATIVE_PROMPT = ("(deformed, distorted, disfigured:1.0), poorly drawn, bad anatomy, wrong anatomy, "
                   "extra limb, missing limb, floating limbs, (mutated hands and fingers:1.4), "
                   "disconnected limbs, mutation, mutated, ugly, disgusting, blurry, amputation, "
                   "3d, cg, render, unreal engine, blender, octane render, illustration, painting, "
                   "anime, cartoon, doll, plastic skin")

# 比例 → 宽高（1K 基准，Flux2-Klein 训练尺寸友好）
RATIO_MAP = {
    "1:1": (1088, 1088),
    "16:9": (1280, 720),
    "9:16": (720, 1280),
    "3:4": (960, 1280),
    "4:3": (1280, 960),
    "2:3": (853, 1280),
    "3:2": (1280, 853),
}

# ── 基础工作流（与 三图参考.ts 的 BASE_WORKFLOW 一致）──
BASE_WORKFLOW = {
    "104": {"inputs": {"samples": ["146", 0], "vae": ["110", 0]}, "class_type": "VAEDecode"},
    "107": {"inputs": {"clip_name": "", "type": "flux2", "device": "default"}, "class_type": "CLIPLoader"},
    "108": {"inputs": {"text": "", "clip": ["107", 0]}, "class_type": "CLIPTextEncode"},
    "109": {"inputs": {"text": "", "clip": ["107", 0]}, "class_type": "CLIPTextEncode"},
    "110": {"inputs": {"vae_name": ""}, "class_type": "VAELoader"},
    "128": {"inputs": {"width": 1280, "height": 720, "batch_size": 1}, "class_type": "EmptyFlux2LatentImage"},
    "146": {
        "inputs": {
            "seed": 0, "steps": 6, "cfg": 1,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1,
            "model": ["197", 0],
            "positive": ["108", 0],
            "negative": ["109", 0],
            "latent_image": ["128", 0],
        },
        "class_type": "KSampler",
    },
    "195": {"inputs": {"filename_prefix": "ComfyUI", "images": ["104", 0]}, "class_type": "SaveImage"},
    "197": {"inputs": {"unet_name": "", "weight_dtype": "default"}, "class_type": "UNETLoader"},
}


def _is_comfy(api_config):
    """判断当前媒体供应商是否为云端 ComfyUI"""
    # 显式供应商类型标记（UI 层传入），任意端口/IP 均可靠
    if str(api_config.get("media_vendor_type") or "").strip().lower() == "comfyui":
        return True
    img_model = (api_config.get("img_model") or "").strip().lower()
    if img_model.startswith("comfyui"):
        return True
    base = (api_config.get("media_base_url") or "").strip().lower()
    return any(k in base for k in ("8188", "15794", "8800", "comfy"))


def _comfy_base(api_config):
    base = (api_config.get("media_base_url") or DEFAULT_BASE).strip().rstrip("/")
    # 协议头清洗：历史配置可能污染成 "http://https://..."（协议重复）→ 归一为单个协议
    # 规则：去掉 "http://http://" / "http://https://" / "https://http://" 等重复协议
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


def _clean_b64(b64):
    """去掉 data URL 前缀与空白"""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    return b64.replace(" ", "").replace("\n", "").replace("\r", "")


def _build_img_workflow(prompt, width, height, refs_b64):
    """构建三图参考工作流（0/1/2/3+ 分支，与 ts 的 getWorkflowJson 一致）"""
    w = json.loads(json.dumps(BASE_WORKFLOW))
    w["107"]["inputs"]["clip_name"] = COMFY_CLIP
    w["110"]["inputs"]["vae_name"] = COMFY_VAE
    w["197"]["inputs"]["unet_name"] = COMFY_UNET
    w["108"]["inputs"]["text"] = prompt
    w["109"]["inputs"]["text"] = NEGATIVE_PROMPT  # 负面提示词（防畸形，CineMaster 集成）
    w["146"]["inputs"]["seed"] = random.randint(0, 10 ** 18)
    w["146"]["inputs"]["steps"] = COMFY_STEPS
    w["146"]["inputs"]["cfg"] = COMFY_CFG
    w["146"]["inputs"]["sampler_name"] = COMFY_SAMPLER
    w["146"]["inputs"]["scheduler"] = COMFY_SCHEDULER
    w["128"]["inputs"]["width"] = width
    w["128"]["inputs"]["height"] = height

    valid = [r for r in refs_b64 if r and r.strip()]
    n = len(valid)

    # CASE 0：纯文生图
    if n == 0:
        w["146"]["inputs"]["denoise"] = 1
        w["146"]["inputs"]["positive"] = ["108", 0]
        w["146"]["inputs"]["negative"] = ["109", 0]
        return w

    # GROUP1
    w["76"] = {"class_type": "easy loadImageBase64",
               "inputs": {"base64_data": "", "image_output": "Preview", "save_prefix": "ComfyUI"}}
    w["112"] = {"class_type": "ImageScaleToTotalPixels",
                "inputs": {"upscale_method": "lanczos", "megapixels": 1, "resolution_steps": 64, "image": ["76", 0]}}
    w["114"] = {"inputs": {"image": ["112", 0]}, "class_type": "GetImageSize"}
    w["116"] = {"inputs": {"pixels": ["112", 0], "vae": ["110", 0]}, "class_type": "VAEEncode"}
    w["115"] = {"inputs": {"conditioning": ["109", 0], "latent": ["116", 0]}, "class_type": "ReferenceLatent"}
    w["117"] = {"inputs": {"conditioning": ["108", 0], "latent": ["116", 0]}, "class_type": "ReferenceLatent"}
    w["76"]["inputs"]["base64_data"] = _clean_b64(valid[0])

    if n == 1:
        w["146"]["inputs"]["denoise"] = COMFY_DENOISE
        w["146"]["inputs"]["positive"] = ["117", 0]
        w["146"]["inputs"]["negative"] = ["115", 0]
        return w

    # GROUP2
    w["164"] = {"class_type": "easy loadImageBase64",
                "inputs": {"base64_data": "", "image_output": "Preview", "save_prefix": "ComfyUI"}}
    w["165"] = {"class_type": "ImageScaleToTotalPixels",
                "inputs": {"upscale_method": "lanczos", "megapixels": 1, "resolution_steps": 64, "image": ["164", 0]}}
    w["163"] = {"inputs": {"pixels": ["165", 0], "vae": ["110", 0]}, "class_type": "VAEEncode"}
    w["166"] = {"inputs": {"conditioning": ["117", 0], "latent": ["163", 0]}, "class_type": "ReferenceLatent"}
    w["167"] = {"inputs": {"conditioning": ["115", 0], "latent": ["163", 0]}, "class_type": "ReferenceLatent"}
    w["164"]["inputs"]["base64_data"] = _clean_b64(valid[1])

    if n == 2:
        w["146"]["inputs"]["denoise"] = COMFY_DENOISE
        w["146"]["inputs"]["positive"] = ["166", 0]
        w["146"]["inputs"]["negative"] = ["167", 0]
        return w

    # GROUP3（n >= 3）
    w["179"] = {"class_type": "easy loadImageBase64",
                "inputs": {"base64_data": "", "image_output": "Preview", "save_prefix": "ComfyUI"}}
    w["176"] = {"class_type": "ImageScaleToTotalPixels",
                "inputs": {"upscale_method": "lanczos", "megapixels": 1, "resolution_steps": 64, "image": ["179", 0]}}
    w["178"] = {"inputs": {"pixels": ["176", 0], "vae": ["110", 0]}, "class_type": "VAEEncode"}
    w["180"] = {"inputs": {"conditioning": ["166", 0], "latent": ["178", 0]}, "class_type": "ReferenceLatent"}
    w["182"] = {"inputs": {"conditioning": ["167", 0], "latent": ["178", 0]}, "class_type": "ReferenceLatent"}
    w["179"]["inputs"]["base64_data"] = _clean_b64(valid[2])

    w["146"]["inputs"]["denoise"] = COMFY_DENOISE
    w["146"]["inputs"]["positive"] = ["180", 0]
    w["146"]["inputs"]["negative"] = ["182", 0]
    return w


def _submit_and_wait(base, workflow, timeout=600):
    """POST /prompt → 轮询 /history → 返回 outputs dict"""
    resp = requests.post(base + "/prompt",
                         json={"prompt": workflow, "client_id": "wave"}, timeout=30, **REQ_KW)
    resp.raise_for_status()
    pid = resp.json().get("prompt_id")
    if not pid:
        raise RuntimeError("ComfyUI 提交失败: " + resp.text[:300])
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
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
    raise TimeoutError("ComfyUI 生成超时（%s 秒）" % timeout)


def _output_url(base, outputs, node_id="195"):
    """从 outputs 中取指定节点（默认 SaveImage 195）的第一个文件 URL"""
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


class ImageSkill(BaseSkill):
    """ComfyUI 云端图片生成（Flux2-Klein 三图参考）"""

    def execute_batch_generation(self, assets, api_config):
        """批量资产生图：assets 为 list[dict]（含 name/type/prompt_en）"""
        if not _is_comfy(api_config):
            raise RuntimeError("当前媒体供应商不是云端 ComfyUI（请将 ComfyUI 供应商设为媒体供应商）")
        base = _comfy_base(api_config)
        total = len(assets)
        self.ctx.log("\n[系统日志] 检测到 %d 个资产，准备并发图（ComfyUI 云端）...\n" % total)
        self.ctx.push_ui_event("status", {
            "text": "\n[系统日志] ComfyUI 开始批量生图...\n",
            "btn_gen_img": "disabled", "progress": True,
            "img_status_text": "ComfyUI 批量生图中 0/%d" % total,
        })
        ok = 0
        failed = []  # 失败清单（2026-08-09：单张失败不中断整批，避免"场景图没了但无提示"）
        try:
            for i, asset in enumerate(assets, 1):
                if getattr(self.ctx, "stop_flag", False):
                    self.ctx.log("\n[系统日志] 用户已停止批量生图。\n")
                    break
                name = asset.get("name") or ("资产%d" % i)
                atype = asset.get("type") or "asset"
                prompt = asset.get("prompt_en") or asset.get("prompt") or ""
                if not prompt:
                    self.ctx.log("\n[系统日志] 跳过 %s（无提示词）\n" % name)
                    continue
                self.ctx.log("\n[系统日志] [%d/%d] 正在生成：%s ...\n" % (i, total, name))
                self.ctx.push_ui_event("status", {
                    "text": "", "btn_gen_img": "disabled", "progress": True,
                    "img_status_text": "ComfyUI 批量生图中 %d/%d" % (i, total),
                })
                # 比例跟随 UI 选择（combo_img_ratio，UI 层写入 api_config['img_ratio']）——
                # 修复：批量生图原来固定 1280x720 横图，竖屏项目（9:16）资产图比例全错
                _ratio = str((api_config or {}).get('img_ratio') or '16:9')
                width, height = RATIO_MAP.get(_ratio, (1280, 720))
                try:
                    wf = _build_img_workflow(prompt, width, height, [])
                    outputs = _submit_and_wait(base, wf, timeout=600)
                    url = _output_url(base, outputs, "195")
                    if not url:
                        raise RuntimeError("未找到输出图片")
                    self.ctx.push_ui_event("image_done", {"name": name, "type": atype, "url": url})
                    ok += 1
                except Exception as _ae:
                    # 单张失败：记录并继续（不中断整批——场景/某张失败不再导致后续全停）
                    failed.append(name)
                    self.ctx.log("\n[系统日志] 图片生成失败（跳过继续）: %s - %s\n" % (name, _ae))
            _fail_msg = ("；失败：%s" % "、".join(failed)) if failed else ""
            self.ctx.push_ui_event("status", {
                "text": "\n[系统日志] 批量生图完成（成功 %d 张%s）\n" % (ok, _fail_msg),
                "btn_gen_img": "normal", "progress": False,
                "img_status_text": "批量生图完成（成功 %d 张%s）" % (ok, _fail_msg),
            })
            if failed:
                self.ctx.log("\n[系统日志] ⚠️ 以下 %d 张图片生成失败，请检查后重试：%s\n" % (len(failed), "、".join(failed)))
        except Exception as e:
            self.ctx.log("\n[系统日志] 批量生图异常: %s\n" % e)
            self.ctx.push_ui_event("status", {
                "text": "\n[系统日志] 批量生图异常: %s\n" % e,
                "btn_gen_img": "normal", "progress": False,
                "img_status_text": "批量生图异常",
            })
            raise

    def generate_single_image(self, prompt, api_config, ratio, res):
        """单图生成（UI 直接调用，不返回，结果经 image_done 事件推送）"""
        if not _is_comfy(api_config):
            raise RuntimeError("当前媒体供应商不是云端 ComfyUI（请将 ComfyUI 供应商设为媒体供应商）")
        base = _comfy_base(api_config)
        ratio = str(ratio or "16:9")
        width, height = RATIO_MAP.get(ratio, (1280, 720))
        self.ctx.log("\n[系统日志] 正在提交图片生成任务并轮询结果（ComfyUI 云端）...\n")
        self.ctx.push_ui_event("status", {
            "text": "", "btn_gen_img": "disabled", "progress": True,
            "img_status_text": "ComfyUI 生成中 %s %s" % (ratio, res),
        })
        try:
            wf = _build_img_workflow(prompt, width, height, [])
            outputs = _submit_and_wait(base, wf, timeout=600)
            url = _output_url(base, outputs, "195")
            if not url:
                raise RuntimeError("未找到输出图片")
            self.ctx.push_ui_event("image_done", {"name": "单图", "type": "image", "url": url})
            self.ctx.push_ui_event("status", {
                "text": "\n[系统日志] 单图生成成功\n",
                "btn_gen_img": "normal", "progress": False,
                "img_status_text": "单图生成成功",
            })
        except Exception as e:
            self.ctx.log("\n[系统日志] 单图生成异常: %s\n" % e)
            self.ctx.push_ui_event("status", {
                "text": "\n[系统日志] 单图生成异常: %s\n" % e,
                "btn_gen_img": "normal", "progress": False,
                "img_status_text": "单图生成异常",
            })
            raise
