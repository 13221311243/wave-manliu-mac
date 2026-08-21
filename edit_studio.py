# -*- coding: utf-8 -*-
"""wave漫流 剪映式剪辑工作台（三区布局）：
┌────────────────────────────────────────────────┐
│ 顶部工具条：同步轨道/导出XML/导出SRT/导入XML/导入SRT │
├──────────┬──────────────────────┬─────────────┤
│ 左侧素材区 │  中间预览区(OpenCV播放) │ 右侧属性区   │
│ 分镜视频  │  ▶播放/⏸暂停/进度条    │ 裁剪/变速/   │
│ 本地导入  │  大画面预览           │ 音量/静音/   │
│ 点选入轨  │                      │ 转场/复制/删除│
├──────────┴──────────────────────┴─────────────┤
│ 底部时间线：多轨横向Canvas（剪映式）→ 拖拽排序/选中/播放头 │
└────────────────────────────────────────────────┘
"""
import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog

try:
    import cv2
    HAVE_CV2 = True
except Exception:
    HAVE_CV2 = False

try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False


class EditStudio:
    """剪映式剪辑工作台三区布局（素材区 / 预览区 / 属性区 + 底部时间线）"""

    def __init__(self, parent, host, colors=None, fonts=None, bind_hover=None):
        """host: 宿主 CineMasterUI 实例（复用其数据与方法）；colors/fonts: 主题"""
        self.host = host
        self.colors = colors or {}
        self.fonts = fonts or {}
        self.bind_hover = bind_hover
        self.parent = parent
        self._tk = getattr(EditStudio, '_tk', tk)  # 类属性可被测试覆盖
        # 数据
        self.tracks = []            # [{num,prompt,dialogue,video_url,duration,trim_start,speed,volume,muted,transition,enabled,type}]
        self.materials = []         # 素材区列表 [(url_or_path, name)]
        self.selected = None        # 时间线选中索引
        self.material_sel = None    # 素材区选中索引
        self.play_state = {'running': False, 'idx': None, 'cap': None,
                           'thread': None, 'stop': False}
        self._build()

    # ================= 布局构建 =================
    def _build(self):
        C = self.colors
        frm = self._tk.Frame(self.parent, bg=C.get('panel', '#1E1E2E'))
        frm.pack(fill="both", expand=True, padx=10, pady=8)
        # 顶部工具条
        top = self._tk.Frame(frm, bg=C.get('panel', '#1E1E2E'))
        top.pack(fill="x", pady=(0, 6))
        self._build_topbar(top)
        # 中部三区：素材 | 预览 | 属性
        mid = self._tk.Frame(frm, bg=C.get('panel', '#1E1E2E'))
        mid.pack(fill="both", expand=True)
        self._build_materials(mid)   # 左
        self._build_preview(mid)     # 中
        self._build_props(mid)       # 右
        # 底部时间线
        self._build_timeline(frm)

    def _build_topbar(self, top):
        C = self.colors
        btns = [
            ("🔄 同步轨道", self.sync_tracks, C.get('border', '#333')),
            ("📂 导入FCP XML", self.import_xml, C.get('border', '#333')),
            ("💬 导入SRT", self.import_srt, C.get('border', '#333')),
            ("🎬 导出成片XML", self.export_xml, '#28A745'),
            ("💬 导出SRT", self.export_srt, C.get('border', '#333')),
        ]
        for text, cmd, bg in btns:
            b = self._tk.Button(top, text=text, font=self.fonts.get('main', ('微软雅黑', 9)),
                          bg=bg, fg="#FFFFFF", relief=tk.FLAT, command=cmd)
            b.pack(side="left", padx=(0, 6))
            if self.bind_hover:
                self.bind_hover(b, bg, "#555")
        self._tk.Label(top, text="  帧率:", font=self.fonts.get('main', ('微软雅黑', 9)),
                 fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E')).pack(side="left")
        self.fps_combo = ttk.Combobox(top, values=("24", "25", "30"), width=4,
                                      state="readonly", font=self.fonts.get('main', ('微软雅黑', 9)))
        self.fps_combo.set("25")
        self.fps_combo.pack(side="left")

    def _build_materials(self, mid):
        """左侧素材区：分镜视频 + 本地导入，点选入轨"""
        C = self.colors
        box = self._tk.Frame(mid, bg=C.get('panel', '#1E1E2E'), width=220)
        box.pack(side="left", fill="y", padx=(0, 6))
        box.pack_propagate(False)
        self._tk.Label(box, text="📁 素材区", font=self.fonts.get('main', ('微软雅黑', 9, 'bold')),
                 fg=C.get('accent', '#8B5CF6'), bg=C.get('panel', '#1E1E2E')).pack(anchor="w")
        bar = self._tk.Frame(box, bg=C.get('panel', '#1E1E2E'))
        bar.pack(fill="x", pady=2)
        self._tk.Button(bar, text="＋ 导入本地视频", font=self.fonts.get('main', ('微软雅黑', 8)),
                  bg=C.get('border', '#333'), fg="#FFF", relief=tk.FLAT,
                  command=self.import_local_video).pack(side="left", padx=(0, 4))
        self._tk.Button(bar, text="全部入轨", font=self.fonts.get('main', ('微软雅黑', 8)),
                  bg=C.get('border', '#333'), fg="#FFF", relief=tk.FLAT,
                  command=self.add_all_to_track).pack(side="left")
        self.material_list = self._tk.Listbox(box, font=self.fonts.get('main', ('微软雅黑', 9)),
                                        bg=C.get('input', '#26263A'), fg=C.get('text', '#EEE'),
                                        selectbackground=C.get('accent', '#8B5CF6'),
                                        highlightthickness=0, height=12)
        self.material_list.pack(fill="both", expand=True, pady=(2, 0))
        self.material_list.bind("<Double-Button-1>", lambda e: self.add_material_to_track())
        # 2026-08-17 选中素材自动预览（单击选中 → 自动加入时间线并播放）
        self.material_list.bind("<ButtonRelease-1>", lambda e: self._auto_preview_material())
        tk.Label(box, text="单击素材自动预览，双击加入时间线", font=self.fonts.get('main', ('微软雅黑', 7)),
                 fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E')).pack(anchor="w", pady=(2, 0))

    def _auto_preview_material(self):
        """单击素材：自动加入时间线并播放"""
        try:
            sel = self.material_list.curselection()
            if not sel:
                return
            if sel[0] >= len(self.materials):
                return
            # 如果该素材已在时间线，直接选中；否则加入
            url, name = self.materials[sel[0]]
            for i, tr in enumerate(self.tracks):
                if tr.get('video_url') == url:
                    self.selected = i
                    self.render_timeline()
                    self._update_prop_display()
                    self.play_selected()
                    return
            self.add_material_to_track()
            self.play_selected()
        except Exception:
            pass

    def _build_preview(self, mid):
        """中间预览区：OpenCV 播放器"""
        C = self.colors
        box = self._tk.Frame(mid, bg=C.get('panel', '#1E1E2E'))
        box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._tk.Label(box, text="▶ 预览区", font=self.fonts.get('main', ('微软雅黑', 9, 'bold')),
                 fg=C.get('accent', '#8B5CF6'), bg=C.get('panel', '#1E1E2E')).pack(anchor="w")
        self.preview_label = self._tk.Label(box, text="（选中时间线片段或素材后自动预览）",
                                      font=self.fonts.get('main', ('微软雅黑', 9)),
                                      bg=C.get('input', '#26263A'), fg=C.get('dim', '#999'))
        self.preview_label.pack(fill="both", expand=True, pady=(2, 0))
        # 播放控制条
        ctrl = self._tk.Frame(box, bg=C.get('panel', '#1E1E2E'))
        ctrl.pack(fill="x", pady=(4, 0))
        self.btn_play = self._tk.Button(ctrl, text="▶ 播放全部", font=self.fonts.get('main', ('微软雅黑', 9)),
                                  bg=C.get('accent', '#8B5CF6'), fg="#FFF", relief=tk.FLAT,
                                  command=self.toggle_play_all)
        self.btn_play.pack(side="left", padx=(0, 6))
        if self.bind_hover:
            self.bind_hover(self.btn_play, C.get('accent', '#8B5CF6'), C.get('accent_dark', '#6D3FD1'))
        self.btn_stop = self._tk.Button(ctrl, text="⏹ 停止", font=self.fonts.get('main', ('微软雅黑', 9)),
                                  bg=C.get('border', '#333'), fg="#FFF", relief=tk.FLAT,
                                  command=self.stop_play)
        self.btn_stop.pack(side="left")
        self.preview_status = self._tk.Label(ctrl, text="未播放", font=self.fonts.get('main', ('微软雅黑', 8)),
                                       fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E'))
        self.preview_status.pack(side="left", padx=(8, 0))

    def _build_props(self, mid):
        """右侧属性区：裁剪/变速/音量/静音/转场/复制/删除"""
        C = self.colors
        box = self._tk.Frame(mid, bg=C.get('panel', '#1E1E2E'), width=230)
        box.pack(side="left", fill="y")
        box.pack_propagate(False)
        self._tk.Label(box, text="⚙ 片段属性", font=self.fonts.get('main', ('微软雅黑', 9, 'bold')),
                 fg=C.get('accent', '#8B5CF6'), bg=C.get('panel', '#1E1E2E')).pack(anchor="w")
        self.prop_label = self._tk.Label(box, text="（未选中片段）", font=self.fonts.get('main', ('微软雅黑', 9)),
                                   fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E'), anchor="w")
        self.prop_label.pack(fill="x", pady=(2, 4))

        def _row(label, key, default):
            r = self._tk.Frame(box, bg=C.get('panel', '#1E1E2E'))
            r.pack(fill="x", pady=2)
            self._tk.Label(r, text=label, font=self.fonts.get('main', ('微软雅黑', 8)),
                     fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E'), width=8, anchor="w").pack(side="left")
            e = self._tk.Entry(r, width=6, font=self.fonts.get('main', ('微软雅黑', 9)),
                         bg=C.get('input', '#26263A'), fg=C.get('text', '#EEE'),
                         insertbackground=C.get('text', '#EEE'))
            e.insert(0, default)
            e.pack(side="left")
            return e

        self.entry_trim = _row("裁剪(s)", "trim", "0")
        self.entry_speed = _row("变速(x)", "speed", "1")
        self.entry_vol = _row("音量(%)", "vol", "100")
        # 静音 + 转场
        r = self._tk.Frame(box, bg=C.get('panel', '#1E1E2E'))
        r.pack(fill="x", pady=2)
        self.var_mute = self._tk.BooleanVar(value=False)
        self._tk.Checkbutton(r, text="静音", variable=self.var_mute, font=self.fonts.get('main', ('微软雅黑', 8)),
                       fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E'),
                       activebackground=C.get('panel', '#1E1E2E'),
                       selectcolor=C.get('input', '#26263A')).pack(side="left")
        self._tk.Label(r, text="转场:", font=self.fonts.get('main', ('微软雅黑', 8)),
                 fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E')).pack(side="left", padx=(8, 2))
        self.combo_trans = ttk.Combobox(r, values=("无", "交叉溶解"), width=7,
                                        state="readonly", font=self.fonts.get('main', ('微软雅黑', 8)))
        self.combo_trans.set("无")
        self.combo_trans.pack(side="left")
        # 操作按钮
        ops = self._tk.Frame(box, bg=C.get('panel', '#1E1E2E'))
        ops.pack(fill="x", pady=(8, 0))
        self._tk.Button(ops, text="应用", font=self.fonts.get('main', ('微软雅黑', 9)),
                  bg=C.get('accent', '#8B5CF6'), fg="#FFF", relief=tk.FLAT,
                  command=self.apply_props).pack(side="left", padx=(0, 4))
        self._tk.Button(ops, text="✂ 分割", font=self.fonts.get('main', ('微软雅黑', 8)),
                  bg=C.get('border', '#333'), fg="#FFF", relief=tk.FLAT,
                  command=self.split_clip).pack(side="left", padx=(0, 4))
        self._tk.Button(ops, text="📄复制", font=self.fonts.get('main', ('微软雅黑', 8)),
                  bg=C.get('border', '#333'), fg="#FFF", relief=tk.FLAT,
                  command=self.duplicate_clip).pack(side="left", padx=(0, 4))
        self._tk.Button(ops, text="🗑删除", font=self.fonts.get('main', ('微软雅黑', 8)),
                  bg="#C0392B", fg="#FFF", relief=tk.FLAT,
                  command=self.delete_clip).pack(side="left")
        self.prop_hint = self._tk.Label(box, text="提示：点时间线片段→改属性→应用",
                                  font=self.fonts.get('main', ('微软雅黑', 7)),
                                  fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E'),
                                  anchor="w", wraplength=210, justify="left")
        self.prop_hint.pack(fill="x", pady=(8, 0))

    def _build_timeline(self, frm):
        """底部时间线：多轨横向 Canvas + 播放头"""
        C = self.colors
        box = self._tk.Frame(frm, bg=C.get('panel', '#1E1E2E'))
        box.pack(fill="both", expand=True, pady=(4, 0))
        head = self._tk.Frame(box, bg=C.get('panel', '#1E1E2E'))
        head.pack(fill="x")
        self._tk.Label(head, text="⏱ 时间线（点击片段选中，双击播放）", font=self.fonts.get('main', ('微软雅黑', 9, 'bold')),
                 fg=C.get('accent', '#8B5CF6'), bg=C.get('panel', '#1E1E2E')).pack(side="left")
        # 缩放控件（放大可精确到帧）
        zoom = self._tk.Frame(head, bg=C.get('panel', '#1E1E2E'))
        zoom.pack(side="left", padx=(12, 0))
        self._tk.Button(zoom, text="🔍−", font=self.fonts.get('main', ('微软雅黑', 8)),
                        bg=C.get('border', '#333'), fg="#FFF", relief=tk.FLAT, width=2,
                        command=self.zoom_out).pack(side="left", padx=(0, 2))
        self._tk.Button(zoom, text="🔍+", font=self.fonts.get('main', ('微软雅黑', 8)),
                        bg=C.get('border', '#333'), fg="#FFF", relief=tk.FLAT, width=2,
                        command=self.zoom_in).pack(side="left")
        self.zoom_label = self._tk.Label(head, text="缩放 x1", font=self.fonts.get('main', ('微软雅黑', 8)),
                                         fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E'))
        self.zoom_label.pack(side="left", padx=(4, 0))
        self.tl_status = self._tk.Label(head, text="暂无轨道", font=self.fonts.get('main', ('微软雅黑', 8)),
                                  fg=C.get('dim', '#999'), bg=C.get('panel', '#1E1E2E'))
        self.tl_status.pack(side="right")
        wrap = self._tk.Frame(box, bg=C.get('panel', '#1E1E2E'))
        wrap.pack(fill="both", expand=True)
        self.tl_canvas = self._tk.Canvas(wrap, bg=C.get('input', '#26263A'), highlightthickness=0, height=170)
        self.tl_canvas.pack(side="left", fill="both", expand=True)
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.tl_canvas.yview)
        self.tl_canvas.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        self.tl_canvas.bind("<Button-1>", self.on_timeline_click)
        self.tl_canvas.bind("<Double-Button-1>", self.on_timeline_double)
        self.tl_canvas.bind("<B1-Motion>", self.on_timeline_drag)
        # 滚轮 = 缩放（放大可精确到帧；纵向滚动用滚动条）
        self.tl_canvas.bind("<MouseWheel>", self.on_timeline_zoom)
        self._tl_x0 = 80
        self._tl_pps = 14.0
        self._drag_from = None
        self._dragging_playhead = False
        self._playhead_manual = None

    # ================= 素材区 =================
    def refresh_materials(self):
        """从 host.video_history 刷新素材区（分镜视频）"""
        self.materials = []
        hist = list(getattr(self.host, 'video_history', []) or [])
        for i, url in enumerate(hist):
            if url:
                self.materials.append((url, "视频%d" % (i + 1)))
        self.material_list.delete(0, self._tk.END)
        for _, name in self.materials:
            self.material_list.insert(self._tk.END, name)

    def import_local_video(self):
        """导入本地视频到素材区"""
        paths = filedialog.askopenfilenames(title="选择视频文件", filetypes=[
            ('视频文件', '*.mp4 *.avi *.mov *.mkv *.webm'), ('所有文件', '*.*')])
        if not paths:
            return
        for p in paths:
            name = os.path.basename(p)
            if (p, name) not in self.materials:
                self.materials.append((p, name))
                self.material_list.insert(self._tk.END, name)
        self.show_toast("已导入 %d 个本地视频到素材区" % len(paths))

    def add_material_to_track(self):
        """选中素材加入时间线末尾"""
        sel = self.material_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self.materials):
            return
        url, name = self.materials[idx]
        self.tracks.append({
            'num': len(self.tracks) + 1, 'prompt': name[:40], 'dialogue': '',
            'video_url': url, 'duration': 5, 'trim_start': 0.0, 'speed': 1.0,
            'volume': 100, 'muted': False, 'transition': '无', 'enabled': True, 'type': 'video',
        })
        self.selected = len(self.tracks) - 1
        self.render_timeline()
        self.show_toast("已将「%s」加入时间线" % name)

    def add_all_to_track(self):
        """全部素材入轨"""
        if not self.materials:
            self.show_toast("素材区为空，请先生成分镜视频或导入本地视频", 'warning')
            return
        for url, name in self.materials:
            self.tracks.append({
                'num': len(self.tracks) + 1, 'prompt': name[:40], 'dialogue': '',
                'video_url': url, 'duration': 5, 'trim_start': 0.0, 'speed': 1.0,
                'volume': 100, 'muted': False, 'transition': '无', 'enabled': True, 'type': 'video',
            })
        self.render_timeline()
        self.show_toast("已将 %d 个素材全部加入时间线" % len(self.materials))

    # ================= 时间线 =================
    def sync_tracks(self):
        """从分镜+视频历史同步轨道"""
        prompts = list(getattr(self.host, 'storyboard_prompts', []) or [])
        videos = list(getattr(self.host, 'video_history', []) or [])
        self.tracks = []
        for idx, p in enumerate(prompts):
            url = videos[idx] if idx < len(videos) else ""
            self.tracks.append({
                'num': p.get('num', idx + 1), 'prompt': str(p.get('prompt', ''))[:40],
                'dialogue': str(p.get('dialogue', '') or ''), 'video_url': url,
                'duration': 5, 'trim_start': 0.0, 'speed': 1.0, 'volume': 100,
                'muted': False, 'transition': '无', 'enabled': True, 'type': 'video',
            })
        self.selected = None
        self.refresh_materials()
        self.render_timeline()
        self.show_toast("已同步 %d 条轨道" % len(self.tracks))

    def render_timeline(self):
        """绘制剪映式时间线（单轨横向拼接，剪映标准布局）"""
        c = self.tl_canvas
        c.delete("all")
        if not self.tracks:
            c.create_text(20, 30, anchor="w", text="暂无轨道：点击「同步轨道」或从素材区双击加入",
                          font=self.fonts.get('main', ('微软雅黑', 10)),
                          fill=self.colors.get('dim', '#999'))
            self.tl_status.config(text="暂无轨道")
            return
        C = self.colors
        row_h = 44          # 单轨高度（大一点好看）
        y = 40              # 轨道 y（时间刻度下方）
        x0 = self._tl_x0
        pps = self._tl_pps  # 每像素秒数（缩放控制）
        total_dur = sum(max(0.5, t['duration'] / max(0.1, t['speed'])) if t['enabled'] else 0
                        for t in self.tracks)
        # 时间刻度（自适应间隔：放大时 1s/0.5s，缩小时 5s/10s）
        tick = 5
        if pps >= 40:
            tick = 1
        elif pps >= 15:
            tick = 2
        elif pps >= 8:
            tick = 5
        else:
            tick = 10
        c.create_text(x0 + 10, 6, anchor="w", text="时间→", font=self.fonts.get('main', ('微软雅黑', 7)),
                      fill=C.get('dim', '#999'))
        for sec in range(0, int(total_dur) + tick, tick):
            px = x0 + sec * pps
            c.create_line(px, 14, px, 22, fill=C.get('border', '#333'))
            # 帧级刻度：tick=1 时每帧（1/25s）也画小刻度
            c.create_text(px + 2, 24, anchor="w", text="%ds" % sec,
                          font=self.fonts.get('main', ('微软雅黑', 6)), fill=C.get('dim', '#999'))
        # 轨道背景
        c.create_rectangle(x0, y, x0 + max(300, total_dur * pps), y + row_h,
                           fill=C.get('input', '#26263A'), outline=C.get('border', '#333'))
        # 单轨：所有片段横向拼接在同一行
        cursor = 0.0
        for idx, tr in enumerate(self.tracks):
            if not tr['enabled']:
                cursor += tr['duration'] / max(0.1, tr['speed'])
                continue
            dur_px = max(6, tr['duration'] / max(0.1, tr['speed']) * pps)
            bx = x0 + cursor * pps
            by = y + 4
            bh = row_h - 8
            fill = "#8B5CF6" if idx == self.selected else "#3B3F6E"
            c.create_rectangle(bx, by, bx + dur_px, by + bh, fill=fill,
                               outline=C.get('accent', '#8B5CF6') if idx == self.selected else C.get('border', '#333'),
                               width=2 if idx == self.selected else 1)
            # 片段文字（放大到一定比例才显示，避免重叠）
            if dur_px >= 30:
                c.create_text(bx + 6, by + 6, anchor="w", text="分镜%s" % tr['num'],
                              font=self.fonts.get('main', ('微软雅黑', 8, 'bold')), fill="#FFF")
                spd = "" if abs(tr['speed'] - 1.0) < 0.01 else " x%.1f" % tr['speed']
                c.create_text(bx + 6, by + bh - 12, anchor="w",
                              text="%ss%s%s" % (tr['duration'], spd, " 🔇" if tr['muted'] else ""),
                              font=self.fonts.get('main', ('微软雅黑', 6)), fill="#C9CCE8")
            # 转场标记
            if tr.get('transition', '无') != '无' and idx > 0:
                tw = min(14, dur_px / 2)
                c.create_rectangle(bx - tw, by + bh - 6, bx, by + bh, fill="#F59E0B", outline="")
            cursor += tr['duration'] / max(0.1, tr['speed'])
        # 播放头（红色竖线，贯穿时间刻度+轨道）
        self._playhead_x = x0 + self._playhead_sec() * pps
        c.create_line(self._playhead_x, 14, self._playhead_x, y + row_h,
                      fill="#FF4757", width=2)
        c.create_text(6, y + row_h + 12, anchor="w",
                      text="总时长：%.1fs ｜ 缩放：%.1fpx/s（滚轮/按钮放大可精确到帧）" % (total_dur, pps),
                      font=self.fonts.get('main', ('微软雅黑', 8)), fill=C.get('credits', '#00D4AA'))
        c.configure(scrollregion=(0, 0, x0 + max(300, total_dur * pps), y + row_h + 30))

    def _playhead_sec(self):
        """播放头当前秒数（可手动拖动；默认 0，不随选中跳变）"""
        if getattr(self, '_playhead_manual', None) is not None:
            return self._playhead_manual
        return 0.0

    def zoom_in(self):
        """放大时间线（可精确到帧级分割）"""
        self._tl_pps = min(120.0, self._tl_pps * 1.5)
        self._update_zoom_label()
        self.render_timeline()

    def zoom_out(self):
        """缩小时间线"""
        self._tl_pps = max(2.0, self._tl_pps / 1.5)
        self._update_zoom_label()
        self.render_timeline()

    def _update_zoom_label(self):
        try:
            self.zoom_label.config(text="缩放 x%.1f" % (self._tl_pps / 14.0))
        except Exception:
            pass

    def on_timeline_zoom(self, event):
        """滚轮缩放时间线（放大可精确到帧）"""
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        return 'break'

    def on_timeline_click(self, event):
        """点击时间线：顶部时间刻度区=拖动播放头；轨道区=选中片段"""
        x, y = event.x, event.y
        if not self.tracks:
            return
        # 顶部区域（时间刻度 y<40）：点击/拖动移动播放头
        if y < 40:
            self._playhead_manual = max(0.0, (x - self._tl_x0) / self._tl_pps)
            self._dragging_playhead = True
            self.render_timeline()
            self._update_preview_status_playhead()
            # 画面跟随（scrub）
            try:
                if getattr(self, '_scrub_after_id', None):
                    self.host.root.after_cancel(self._scrub_after_id)
                self._scrub_after_id = self.host.root.after(80, self._scrub_frame)
            except Exception:
                pass
            return
        # 轨道区（单轨 y 40~84）：按 x 定位片段
        x_sec = (x - self._tl_x0) / self._tl_pps  # 点击处秒数
        if x_sec < 0:
            return
        # 找该秒数落在哪个片段
        cursor = 0.0
        hit = None
        for i, tr in enumerate(self.tracks):
            if not tr['enabled']:
                cursor += tr['duration'] / max(0.1, tr['speed'])
                continue
            dur = tr['duration'] / max(0.1, tr['speed'])
            if cursor <= x_sec < cursor + dur:
                hit = i
                break
            cursor += dur
        if hit is not None:
            self.selected = hit
            # 2026-08-17 修复：选中片段时不再把播放头跳回片头——保持当前位置（用户要自由定位）
            self._update_prop_display()
        else:
            self.selected = None
            self._update_prop_display()
        self.render_timeline()

    def on_playhead_drag(self, event):
        """拖动播放头（B1-Motion）：仅顶部区域响应"""
        if not getattr(self, '_dragging_playhead', False):
            return
        if event.y < 34:
            self._playhead_manual = max(0.0, (event.x - self._tl_x0) / self._tl_pps)
            self.render_timeline()
            self._update_preview_status_playhead()

    def _update_preview_status_playhead(self):
        """拖动播放头时更新状态栏显示时间"""
        try:
            sec = self._playhead_sec()
            total = sum(max(0.5, t['duration'] / max(0.1, t['speed'])) if t['enabled'] else 0 for t in self.tracks)
            self.tl_status.config(text="播放头：%.1fs / %.1fs（拖动顶部刻度移动）" % (sec, total))
        except Exception:
            pass

    def on_timeline_double(self, event):
        """双击时间线片段：预览该片段"""
        self.on_timeline_click(event)
        if self.selected is not None:
            self.play_selected()

    def on_timeline_drag(self, event):
        """拖拽：在任意位置拖动 → 播放头自由跟随 + 预览区画面实时跟随（scrub）"""
        if not self.tracks:
            return
        x = event.x
        self._playhead_manual = max(0.0, (x - self._tl_x0) / self._tl_pps)
        self.render_timeline()
        self._update_preview_status_playhead()
        # 预览区画面跟随指针（防抖：合并 0.08s 内的连续拖动）
        try:
            if getattr(self, '_scrub_after_id', None):
                self.host.root.after_cancel(self._scrub_after_id)
            self._scrub_after_id = self.host.root.after(80, self._scrub_frame)
        except Exception:
            pass

    def _scrub_frame(self):
        """抽取播放头位置的单帧显示到预览区（指针到哪、画面到哪帧）"""
        try:
            self._scrub_after_id = None
            if self.play_state.get('running'):
                return  # 正在播放时不 scrub
            sec = self._playhead_sec()
            # 找该秒数落在哪个片段
            cursor = 0.0
            target = None
            for i, tr in enumerate(self.tracks):
                if not tr.get('enabled', True):
                    cursor += tr['duration'] / max(0.1, tr['speed'])
                    continue
                dur = tr['duration'] / max(0.1, tr['speed'])
                if cursor <= sec < cursor + dur:
                    target = (i, tr, sec - cursor)  # 片段内相对秒
                    break
                cursor += dur
            if target is None:
                return
            i, tr, rel = target
            url = tr.get('video_url') or ''
            if not url:
                return
            # 片段内实际时间点（含 trim_start + 变速换算）
            speed = max(0.1, float(tr.get('speed', 1) or 1))
            src_sec = float(tr.get('trim_start', 0) or 0) + rel * speed
            ffmpeg = self._find_ffmpeg()
            if not ffmpeg:
                return
            # 后台线程抽帧（避免拖拽卡 UI）
            threading.Thread(target=self._scrub_worker, args=(url, src_sec), daemon=True).start()
        except Exception:
            pass

    def _scrub_worker(self, url, src_sec):
        """后台：ffmpeg 抽取指定秒的单帧 PNG → 主线程显示"""
        import subprocess as _sp
        import tempfile
        local = url
        try:
            # 远程下载（带缓存：同 URL 短时间不重复下载）
            if url.startswith(('http://', 'https://')):
                cache = os.path.join(tempfile.gettempdir(), 'wv_scrub_' + str(abs(hash(url)))[:10] + '.mp4')
                if not os.path.exists(cache):
                    import requests
                    r = requests.get(url, timeout=60, verify=False,
                                     headers={"User-Agent": "Mozilla/5.0"},
                                     **getattr(self.host, 'REQ_KW', {}))
                    if r.status_code != 200:
                        return
                    with open(cache, 'wb') as f:
                        f.write(r.content)
                local = cache
            if not os.path.exists(local):
                return
            ffmpeg = self._find_ffmpeg()
            # 抽单帧：-ss 定位 + 1 帧 PNG 到 stdout
            cmd = [ffmpeg, '-y', '-ss', '%.3f' % src_sec, '-i', local,
                   '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png',
                   '-vf', 'scale=480:-2', '-loglevel', 'error', 'pipe:1']
            proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.DEVNULL)
            data = proc.stdout.read()
            proc.wait(timeout=10)
            if data:
                self.host.root.after(0, lambda d=data: self._show_frame(d))
        except Exception:
            pass

    def _update_prop_display(self):
        if self.selected is None or not (0 <= self.selected < len(self.tracks)):
            self.prop_label.config(text="（未选中片段）")
            return
        tr = self.tracks[self.selected]
        self.prop_label.config(text="分镜%s（%ss）" % (tr['num'], tr['duration']))
        self.entry_trim.delete(0, self._tk.END)
        self.entry_trim.insert(0, "%.1f" % tr['trim_start'])
        self.entry_speed.delete(0, self._tk.END)
        self.entry_speed.insert(0, "%.1f" % tr['speed'])
        self.entry_vol.delete(0, self._tk.END)
        self.entry_vol.insert(0, str(tr['volume']))
        try:
            self.var_mute.set(bool(tr['muted']))
            self.combo_trans.set(tr.get('transition', '无'))
        except Exception:
            pass

    # ================= 属性 =================
    def apply_props(self):
        if self.selected is None:
            self.show_toast("请先点击时间线选中片段", 'warning')
            return
        tr = self.tracks[self.selected]
        try:
            tr['trim_start'] = max(0.0, float(self.entry_trim.get() or 0))
            tr['speed'] = max(0.1, min(4.0, float(self.entry_speed.get() or 1)))
            tr['volume'] = max(0, min(200, int(float(self.entry_vol.get() or 100))))
            tr['muted'] = bool(self.var_mute.get())
            tr['transition'] = self.combo_trans.get() or '无'
        except ValueError:
            self.show_toast("属性格式错误（裁剪/变速填数字，音量填0-100）", 'warning')
            return
        self.render_timeline()
        self.show_toast("✅ 已应用分镜%s属性" % tr['num'])

    def duplicate_clip(self):
        if self.selected is None:
            self.show_toast("请先点击时间线选中片段", 'warning')
            return
        src = dict(self.tracks[self.selected])
        src['num'] = str(src['num']) + "′"
        self.tracks.insert(self.selected + 1, src)
        self.selected += 1
        self.render_timeline()
        self.show_toast("已复制分镜%s" % src['num'])

    def delete_clip(self):
        if self.selected is None:
            self.show_toast("请先点击时间线选中片段", 'warning')
            return
        tr = self.tracks.pop(self.selected)
        self.selected = None
        self.render_timeline()
        self.show_toast("已删除分镜%s" % tr['num'])

    def split_clip(self):
        """在播放头位置把选中片段一分为二（剪映式分割）"""
        if self.selected is None or not (0 <= self.selected < len(self.tracks)):
            self.show_toast("请先点击时间线选中要分割的片段", 'warning')
            return
        tr = self.tracks[self.selected]
        # 计算播放头在该片段内的相对秒数
        cursor = 0.0
        for i in range(self.selected):
            t = self.tracks[i]
            if t['enabled']:
                cursor += t['duration'] / max(0.1, t['speed'])
        ph = self._playhead_sec()
        rel = ph - cursor  # 播放头在片段内的秒数（变速后）
        if rel <= 0.3 or rel >= tr['duration'] / max(0.1, tr['speed']) - 0.3:
            self.show_toast("播放头需在片段中间位置才能分割", 'warning')
            return
        # 原片段时长（变速后）→ 切分点（原时长秒）
        orig_speed = max(0.1, tr['speed'])
        split_orig = rel * orig_speed  # 换算回原始时长秒
        # 第一段：保留前 split_orig 秒
        part1 = dict(tr)
        part1['num'] = str(tr['num']) + '-1'
        part1_dur = max(1, int(round(split_orig)))
        part1['duration'] = part1_dur
        # 第二段：剩余部分，trim_start 前移（保证两段时长和 = 原时长）
        part2 = dict(tr)
        part2['num'] = str(tr['num']) + '-2'
        part2['duration'] = max(1, int(tr['duration']) - part1_dur)
        part2['trim_start'] = tr['trim_start'] + split_orig
        # 替换原片段为两段
        self.tracks[self.selected:self.selected + 1] = [part1, part2]
        self.selected = self.selected  # 保持选中第一段
        self.render_timeline()
        self._update_prop_display()
        self.show_toast("✂ 已在播放头位置分割分镜%s → %s / %s" % (tr['num'], part1['num'], part2['num']))

    # ================= 预览（内嵌播放器：ffmpeg 抽帧 + PIL 显示） =================
    def _find_ffmpeg(self):
        """探测 ffmpeg：exe 同目录 → PATH → 系统 Python imageio_ffmpeg → 常见安装路径"""
        import shutil, glob
        cands = []
        # 1. exe 同目录
        base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        cands.append(os.path.join(base, 'ffmpeg.exe'))
        # 2. PATH
        try:
            p = shutil.which('ffmpeg')
            if p:
                return p
        except Exception:
            pass
        # 3. 系统 Python site-packages imageio_ffmpeg（开发机本机环境）
        for py in glob.glob(r'C:\Users\*\AppData\Local\Programs\Python\Python3*\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg*.exe'):
            cands.append(py)
        # 4. 常见安装路径
        cands += [r'C:\ffmpeg\bin\ffmpeg.exe', r'C:\Program Files\ffmpeg\bin\ffmpeg.exe']
        for c in cands:
            if c and os.path.exists(c):
                return c
        return None

    def play_all(self):
        """播放全部片段（从播放头位置开始，依次播完剩余片段）"""
        if not self.tracks:
            self.show_toast("时间线为空", 'warning')
            return
        enabled = [i for i, t in enumerate(self.tracks) if t.get('enabled', True) and t.get('video_url')]
        if not enabled:
            self.show_toast("没有可播放的片段", 'warning')
            return
        self.stop_play()
        self.play_state['idx'] = None  # 全片播放
        self.play_state['stop'] = False
        self.play_state['running'] = True
        self.btn_play.config(text="⏸ 暂停")
        self.preview_status.config(text="正在播放全部片段...")
        self.play_state['thread'] = threading.Thread(target=self._play_all_worker, daemon=True)
        self.play_state['thread'].start()

    def _play_all_worker(self):
        """后台线程：依次播放每个片段（用 ffmpeg 帧文件方案，一个接一个）"""
        import tempfile
        import subprocess as _sp
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            self.host.root.after(0, lambda: self.preview_status.config(text="未找到 ffmpeg，无法内嵌播放"))
            self.host.root.after(0, lambda: self.btn_play.config(text="▶ 播放"))
            self.play_state['running'] = False
            return
        try:
            # 先收集有视频的片段索引（无视频的跳过）
            playable = [(i, tr) for i, tr in enumerate(self.tracks)
                        if tr.get('enabled', True) and tr.get('video_url')]
            if not playable:
                self.host.root.after(0, lambda: self.preview_status.config(text="没有可播放的片段"))
                return
            # 播放头起始位置：从播放头所在片段开始，该片段从播放头位置起播
            ph = self._playhead_sec()
            start_idx = 0
            start_offset = 0.0  # 起始片段内的偏移（变速后秒）
            cursor = 0.0
            for pi, (i, tr) in enumerate(playable):
                dur = tr['duration'] / max(0.1, tr['speed'])
                if cursor <= ph < cursor + dur:
                    start_idx = pi
                    start_offset = ph - cursor
                    break
                cursor += dur
            else:
                # 播放头超出总时长 → 从头播
                start_idx = 0
                start_offset = 0.0
            for idx in range(start_idx, len(playable)):
                i, tr = playable[idx]
                if self.play_state['stop'] or not self.play_state['running']:
                    break
                self.selected = i
                self.host.root.after(0, lambda: self._update_prop_display())
                self.host.root.after(0, lambda: self.render_timeline())
                url = tr['video_url']
                local = url
                # 远程下载
                if url.startswith(('http://', 'https://')):
                    try:
                        import requests
                        self.host.root.after(0, lambda: self.preview_status.config(
                            text="正在下载片段 %d/%d..." % (idx + 1, len(playable))))
                        r = requests.get(url, timeout=180, verify=False,
                                         headers={"User-Agent": "Mozilla/5.0"},
                                         **getattr(self.host, 'REQ_KW', {}))
                        if r.status_code != 200:
                            continue
                        tmp = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
                        tmp.write(r.content)
                        tmp.close()
                        local = tmp.name
                    except Exception:
                        continue
                if not os.path.exists(local):
                    continue
                self.host.root.after(0, lambda: self.preview_status.config(
                    text="正在播放片段 %d/%d（分镜%s）..." % (idx + 1, len(playable), tr['num'])))
                # ffmpeg 抽帧到临时目录
                trim = max(0.0, float(tr.get('trim_start', 0) or 0))
                speed = max(0.1, min(4.0, float(tr.get('speed', 1) or 1)))
                vf = 'setpts=%.4f*PTS' % (1.0 / speed)
                tmpdir = tempfile.mkdtemp(prefix='wv_prev_')
                frame_pat = os.path.join(tmpdir, 'f_%05d.png')
                cmd = [ffmpeg, '-y']
                # 2026-08-17 播放头起播：第一个片段从播放头位置起播（trim + 偏移换算回源秒）
                src_ss = trim
                if idx == start_idx and start_offset > 0:
                    src_ss += start_offset * speed
                if src_ss > 0:
                    cmd += ['-ss', '%.3f' % src_ss]
                cmd += ['-i', local, '-f', 'image2', '-vcodec', 'png',
                        '-vf', vf + ',scale=480:-2', frame_pat, '-loglevel', 'error']
                proc = _sp.Popen(cmd, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                # 逐个显示帧（限速）；片段播完 = 帧读完
                n = 1
                frames_shown = 0
                while self.play_state['running'] and not self.play_state['stop']:
                    fp = os.path.join(tmpdir, 'f_%05d.png' % n)
                    if os.path.exists(fp):
                        with open(fp, 'rb') as f:
                            data = f.read()
                        self.host.root.after(0, lambda d=data: self._show_frame(d))
                        n += 1
                        frames_shown += 1
                        time.sleep(0.04)
                    else:
                        # ffmpeg 结束且该帧不再出现 → 片段播完
                        if proc.poll() is not None:
                            # 等所有已生成帧都显示完
                            time.sleep(0.05)
                            break
                        time.sleep(0.05)
                try:
                    proc.kill()
                except Exception:
                    pass
                # 清理：等 ffmpeg 完全退出后再删
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                try:
                    import shutil
                    shutil.rmtree(tmpdir, ignore_errors=True)
                except Exception:
                    pass
                # 下载的临时文件清理
                if local != url:
                    try:
                        os.remove(local)
                    except Exception:
                        pass
        except Exception as e:
            print('[EditStudio._play_all_worker]', e)
        finally:
            self.play_state['running'] = False
            self.host.root.after(0, lambda: self.btn_play.config(text="▶ 播放"))
            self.host.root.after(0, lambda: self.preview_status.config(text="全部播放结束"))

    def play_selected(self):
        """播放：优先素材区选中项（自动入轨并预览）；否则播放时间线选中片段"""
        # 素材区选中：自动加入时间线并选中播放
        try:
            sel = self.material_list.curselection()
            if sel:
                self.add_material_to_track()
        except Exception:
            pass
        if self.selected is None or not (0 <= self.selected < len(self.tracks)):
            self.show_toast("请先选中要预览的片段（点时间线片段或双击素材）", 'warning')
            self.preview_status.config(text="未选中片段")
            return
        tr = self.tracks[self.selected]
        url = tr.get('video_url') or ''
        if not url:
            self.show_toast("该片段无视频", 'warning')
            self.preview_status.config(text="该片段无视频")
            return
        self.stop_play()
        self.play_state['idx'] = self.selected
        self.play_state['stop'] = False
        self.play_state['thread'] = threading.Thread(target=self._play_worker, args=(url,), daemon=True)
        self.play_state['thread'].start()

    def toggle_play(self):
        if self.play_state['running']:
            self.stop_play()
        else:
            self.play_selected()

    def toggle_play_all(self):
        """播放全部 / 停止"""
        if self.play_state['running']:
            self.stop_play()
        else:
            self.play_all()

    def stop_play(self):
        self.play_state['stop'] = True
        self.play_state['running'] = False
        self.btn_play.config(text="▶ 播放")
        self.preview_status.config(text="已停止")

    def _play_worker(self, url):
        """后台线程：ffmpeg 内嵌播放（应用裁剪/变速/音量）→ 预览区显示；无 ffmpeg 回退系统播放器"""
        local = url
        # 远程先下载
        if url.startswith(('http://', 'https://')):
            try:
                import requests
                import tempfile
                r = requests.get(url, timeout=120, verify=False,
                                 headers={"User-Agent": "Mozilla/5.0"},
                                 **getattr(self.host, 'REQ_KW', {}))
                if r.status_code == 200:
                    tmp = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
                    tmp.write(r.content)
                    tmp.close()
                    local = tmp.name
                else:
                    self.host.root.after(0, lambda: self.preview_status.config(text="下载失败 HTTP %d" % r.status_code))
                    self.host.root.after(0, lambda: self.btn_play.config(text="▶ 播放"))
                    return
            except Exception as e:
                self.host.root.after(0, lambda: self.preview_status.config(text="下载失败: %s" % e))
                self.host.root.after(0, lambda: self.btn_play.config(text="▶ 播放"))
                return
        if not os.path.exists(local):
            self.host.root.after(0, lambda: self.preview_status.config(text="视频文件不存在"))
            self.host.root.after(0, lambda: self.btn_play.config(text="▶ 播放"))
            return
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            # 回退：系统默认播放器
            try:
                if os.name == 'nt':
                    os.startfile(local)
                else:
                    import subprocess
                    subprocess.Popen(['xdg-open', local])
                self.play_state['running'] = True
                self.host.root.after(0, lambda: self.preview_status.config(text="已在系统播放器中打开"))
                self.host.root.after(0, lambda: self.btn_play.config(text="▶ 播放"))
                def _reset():
                    self.play_state['running'] = False
                self.host.root.after(5000, _reset)
            except Exception as e:
                self.host.root.after(0, lambda: self.preview_status.config(text="播放失败: %s" % e))
                self.host.root.after(0, lambda: self.btn_play.config(text="▶ 播放"))
                self.play_state['running'] = False
            return
        # 内嵌播放：ffmpeg 输出 PNG 帧文件到临时目录 → 后台线程逐个显示
        tmpdir = None
        try:
            import subprocess as _sp
            import tempfile
            tr = self.tracks[self.selected] if self.selected is not None and self.selected < len(self.tracks) else {}
            trim = max(0.0, float(tr.get('trim_start', 0) or 0))
            speed = max(0.1, min(4.0, float(tr.get('speed', 1) or 1)))
            vol = max(0, min(200, int(tr.get('volume', 100) or 100)))
            vf = 'setpts=%.4f*PTS' % (1.0 / speed)
            af = []
            if abs(speed - 1.0) > 0.01:
                af.append('atempo=%.3f' % min(2.0, speed))
                if speed > 2.0:
                    af.append('atempo=%.3f' % (speed / 2.0))
            if vol != 100:
                af.append('volume=%.2f' % (vol / 100.0))
            tmpdir = tempfile.mkdtemp(prefix='wv_prev_')
            frame_pat = os.path.join(tmpdir, 'f_%05d.png')
            cmd = [ffmpeg, '-y']
            if trim > 0:
                cmd += ['-ss', '%.3f' % trim]
            cmd += ['-i', local, '-f', 'image2', '-vcodec', 'png',
                    '-vf', vf + ',scale=480:-2', frame_pat]
            if af:
                cmd += ['-af', ','.join(af)]
            cmd += ['-loglevel', 'error']
            proc = _sp.Popen(cmd, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            self.play_state['running'] = True
            self.host.root.after(0, lambda: self.btn_play.config(text="⏸ 暂停"))
            self.host.root.after(0, lambda: self.preview_status.config(text="正在播放（内嵌预览）"))
            # 后台线程：等 ffmpeg 生成帧文件，逐个显示（ffmpeg 从 f_00001.png 开始）
            n = 1
            while self.play_state['running'] and not self.play_state['stop']:
                fp = os.path.join(tmpdir, 'f_%05d.png' % n)
                if os.path.exists(fp):
                    with open(fp, 'rb') as f:
                        data = f.read()
                    self.host.root.after(0, lambda d=data: self._show_frame(d))
                    n += 1
                    time.sleep(0.04)  # ~25fps
                else:
                    if proc.poll() is not None:
                        # ffmpeg 结束且没有更多帧
                        remaining = [x for x in os.listdir(tmpdir) if x.startswith('f_')]
                        if not remaining:
                            break
                        time.sleep(0.05)
                    else:
                        time.sleep(0.05)
            try:
                proc.kill()
            except Exception:
                pass
            self.play_state['running'] = False
            self.host.root.after(0, lambda: self.btn_play.config(text="▶ 播放"))
            self.host.root.after(0, lambda: self.preview_status.config(text="播放结束"))
        except Exception as e:
            self.host.root.after(0, lambda: self.preview_status.config(text="预览异常: %s" % e))
            self.host.root.after(0, lambda: self.btn_play.config(text="▶ 播放"))
            self.play_state['running'] = False
        finally:
            # 清理临时帧目录
            if tmpdir:
                try:
                    import shutil
                    shutil.rmtree(tmpdir, ignore_errors=True)
                except Exception:
                    pass

    def _show_frame(self, frame_bytes):
        """主线程：解码 PNG 帧并显示到预览区（PhotoImage 必须在主线程创建）"""
        try:
            import io as _io
            img = Image.open(_io.BytesIO(frame_bytes))
            img = img.convert('RGB')
            tkimg = ImageTk.PhotoImage(img)
            self._tkimg = tkimg  # 防 GC
            self.preview_label.config(image=tkimg, text="")
        except Exception as e:
            print('[EditStudio._show_frame] 失败:', e)

    # ================= 导入/导出（独立实现，用 self.tracks） =================
    def show_toast(self, msg, kind='info'):
        try:
            if hasattr(self.host, '_show_toast'):
                self.host._show_toast(msg, kind)
            else:
                self.show_toast(msg, kind)
        except Exception:
            print('[EditStudio]', msg)

    def import_xml(self):
        """导入 FCP XML 到时间线"""
        path = filedialog.askopenfilename(title="选择 FCP XML 文件",
                                          filetypes=[("FCP XML", "*.xml"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(path)
            root = tree.getroot()
            clips = []
            for clipitem in root.iter('clipitem'):
                name = clipitem.findtext('name') or ''
                start = int(clipitem.findtext('start') or 0)
                end = int(clipitem.findtext('end') or 0)
                dur = int(clipitem.findtext('duration') or (end - start))
                file_el = clipitem.find('file')
                pathurl = ''
                if file_el is not None:
                    pathurl = file_el.findtext('pathurl') or ''
                    if pathurl.startswith('file://localhost/'):
                        pathurl = pathurl.replace('file://localhost/', '')
                        pathurl = pathurl.replace('/', os.sep)
                clips.append({'name': name, 'duration': max(1, dur), 'pathurl': pathurl,
                              'start': start, 'end': end})
            if not clips:
                self.show_toast("XML 中未找到 clipitem", 'warning')
                return
            self.tracks = []
            for i, c in enumerate(clips):
                fps = int(self.fps_combo.get())
                self.tracks.append({
                    'num': i + 1, 'prompt': c['name'][:40], 'dialogue': '',
                    'video_url': c['pathurl'], 'duration': max(1, c['duration'] // fps),
                    'trim_start': 0.0, 'speed': 1.0, 'volume': 100,
                    'muted': False, 'transition': '无', 'enabled': True, 'type': 'video',
                })
            self.render_timeline()
            self.show_toast("已导入 %d 个片段" % len(clips))
        except Exception as e:
            self.show_toast("XML 解析失败: %s" % e, 'warning')

    def export_xml(self):
        """导出 FCP 7 XML（含 trim/speed/muted/transition）"""
        if not self.tracks:
            self.show_toast("轨道为空，请先同步轨道", 'warning')
            return
        out_dir = filedialog.askdirectory(title="选择导出目录（视频将下载到该目录）")
        if not out_dir:
            return
        fps = int(self.fps_combo.get())
        threading.Thread(target=self._export_worker, args=(out_dir, fps), daemon=True).start()
        self.show_toast("正在导出...（视频将下载到所选目录）")

    def _export_worker(self, out_dir, fps):
        try:
            import requests
            clips = []
            for tr in self.tracks:
                if not tr.get('enabled', True):
                    continue
                local = ""
                url = tr.get('video_url') or ''
                if url:
                    try:
                        if url.startswith(('http://', 'https://')):
                            r = requests.get(url, timeout=120, verify=False,
                                             headers={"User-Agent": "Mozilla/5.0"},
                                             **getattr(self.host, 'REQ_KW', {}))
                            r.raise_for_status()
                            local = os.path.join(out_dir, "片段%02d.mp4" % int(tr['num']))
                            with open(local, 'wb') as f:
                                f.write(r.content)
                        elif os.path.exists(url):
                            local = url  # 本地视频直接引用
                    except Exception as e:
                        print('[导出] %s 下载失败: %s' % (tr['num'], e))
                clips.append({
                    'num': tr['num'], 'local': local,
                    'duration': max(1, int(tr['duration'])),
                    'trim_start': max(0.0, float(tr.get('trim_start', 0) or 0)),
                    'speed': max(0.1, min(4.0, float(tr.get('speed', 1) or 1))),
                    'volume': max(0, min(200, int(tr.get('volume', 100) or 100))),
                    'muted': bool(tr.get('muted', False)),
                    'transition': tr.get('transition', '无'),
                })
            dur_frames = [int(c['duration'] / c['speed'] * fps) for c in clips]
            total_frames = sum(dur_frames)
            xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>',
                         '<!DOCTYPE xmeml>', '<xmeml version="4">',
                         '  <sequence id="seq-main">',
                         '    <name>wave漫流成片</name>',
                         '    <duration>%d</duration>' % total_frames,
                         '    <rate><timebase>%d</timebase></rate>' % fps,
                         '    <media><video>',
                         '      <format><samplecharacteristics><rate><timebase>%d</timebase></rate><width>1920</width><height>1080</height></samplecharacteristics></format>' % fps,
                         '        <track>']
            offset = 0
            for i, c in enumerate(clips):
                d = dur_frames[i]
                name = "片段%02d" % int(c['num'])
                pathurl = ""
                if c['local']:
                    pathurl = "file://localhost/" + c['local'].replace('\\', '/')
                xml_parts += [
                    '          <clipitem id="clip-%d">' % i,
                    '            <name>%s</name>' % name,
                    '            <duration>%d</duration>' % d,
                    '            <in>%d</in>' % int(c['trim_start'] * fps),
                    '            <out>%d</out>' % (int(c['trim_start'] * fps) + d),
                    '            <start>%d</start>' % offset,
                    '            <end>%d</end>' % (offset + d),
                    '            <rate><timebase>%d</timebase></rate>' % fps,
                    '            <file id="file-%d"><name>%s</name><pathurl>%s</pathurl></file>' % (i, name, pathurl),
                    '          </clipitem>']
                if i > 0 and c['transition'] not in (None, '', '无'):
                    tf = min(int(0.5 * fps), d // 2)
                    if tf > 0:
                        xml_parts += [
                            '          <transitionitem id="trans-%d">' % i,
                            '            <rate><timebase>%d</timebase></rate>' % fps,
                            '            <start>%d</start>' % (offset - tf),
                            '            <end>%d</end>' % (offset + tf),
                            '            <alignment>center</alignment>',
                            '            <effect><name>Cross Dissolve</name><effectid>Cross Dissolve</effectid></effect>',
                            '          </transitionitem>']
                offset += d
            xml_parts += ['        </track></video>', '<audio><track>']
            aoffset = 0
            for i, c in enumerate(clips):
                d = dur_frames[i]
                name = "片段%02d" % int(c['num'])
                pathurl = ""
                if c['local']:
                    pathurl = "file://localhost/" + c['local'].replace('\\', '/')
                vol = 0 if c['muted'] else c['volume']
                xml_parts += [
                    '          <clipitem id="aclip-%d">' % i,
                    '            <name>%s</name>' % name,
                    '            <duration>%d</duration>' % d,
                    '            <in>%d</in>' % int(c['trim_start'] * fps),
                    '            <out>%d</out>' % (int(c['trim_start'] * fps) + d),
                    '            <start>%d</start>' % aoffset,
                    '            <end>%d</end>' % (aoffset + d),
                    '            <rate><timebase>%d</timebase></rate>' % fps,
                    '            <file id="afile-%d"><name>%s</name><pathurl>%s</pathurl></file>' % (i, name, pathurl),
                    '            <volume><level>%.2f</level></volume>' % (vol / 100.0),
                    '          </clipitem>']
                aoffset += d
            xml_parts += ['</track></audio>', '</media>', '  </sequence>', '</xmeml>']
            xml_path = os.path.join(out_dir, "wave漫流成片.fcpxml")
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(xml_parts))
            done = sum(1 for c in clips if c['local'])
            self.show_toast("✅ 导出完成：%s（已备 %d/%d 视频）" % (xml_path, done, len(clips)))
        except Exception as e:
            self.show_toast("导出失败: %s" % e, 'warning')

    def import_srt(self):
        """导入 SRT 字幕：匹配到时间线片段"""
        path = filedialog.askopenfilename(title="选择 SRT 字幕文件",
                                          filetypes=[("SRT 字幕", "*.srt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            import re as _re
            cues = []
            with open(path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
            for block in _re.split(r'\n\s*\n', content.strip()):
                lines = [l.strip() for l in block.split('\n') if l.strip()]
                if len(lines) < 2:
                    continue
                tl = next((l for l in lines if '-->' in l), None)
                if not tl:
                    continue
                m = _re.match(r'(\d{1,2}):(\d{2}):(\d{2})[,.]\d{3}\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.]\d{3}', tl)
                if not m:
                    continue
                h1, m1, s1, h2, m2, s2 = map(int, m.groups())
                start = (h1 * 3600 + m1 * 60 + s1) * 1000
                end = (h2 * 3600 + m2 * 60 + s2) * 1000
                text = ' '.join(l for l in lines if '-->' not in l and not l.strip().isdigit())
                if text:
                    cues.append((start, end, text))
            if not cues:
                self.show_toast("SRT 中未解析到有效字幕", 'warning')
                return
            t = 0
            matched = 0
            for tr in self.tracks:
                dur_ms = max(1, int(tr['duration'] / max(0.1, tr['speed']))) * 1000
                hit = next(((c[2]) for c in cues if t <= c[0] < t + dur_ms), None)
                if hit:
                    tr['dialogue'] = hit
                    matched += 1
                t += dur_ms
            self.render_timeline()
            self.show_toast("已导入 %d 条字幕，匹配 %d 个片段" % (len(cues), matched))
        except Exception as e:
            self.show_toast("SRT 解析失败: %s" % e, 'warning')

    def export_srt(self):
        """导出 SRT 字幕（按时间线顺序+时长）"""
        if not self.tracks:
            self.show_toast("轨道为空", 'warning')
            return
        path = filedialog.asksaveasfilename(title="保存字幕文件", defaultextension=".srt",
                                            filetypes=[("SRT 字幕", "*.srt")])
        if not path:
            return
        lines = []
        idx = 1
        t = 0
        for tr in self.tracks:
            if not tr.get('enabled', True):
                continue
            dur_ms = max(1, int(tr['duration'] / max(0.1, tr['speed']))) * 1000
            dlg = str(tr.get('dialogue') or '').strip()
            if dlg:
                def _fmt(ms):
                    h, rem = divmod(ms, 3600000)
                    m, rem = divmod(rem, 60000)
                    s, ms = divmod(rem, 1000)
                    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)
                lines.append("%d\n%s --> %s\n%s\n" % (idx, _fmt(t), _fmt(t + dur_ms), dlg))
                idx += 1
            t += dur_ms
        try:
            with open(path, 'w', encoding='utf-8-sig') as f:
                f.write('\n'.join(lines))
            self.show_toast("SRT 已导出（%d 条）" % (idx - 1))
        except Exception as e:
            self.show_toast("导出失败: %s" % e, 'warning')
