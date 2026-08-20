# -*- coding: utf-8 -*-
"""core.agent —— 从 wave漫流 exe PYZ 精确重构（2026-08-20，逻辑逐字节对齐原 code 对象）"""
import threading
from skills.llm_skill import LLMSkill
from skills.image_skill import ImageSkill
from skills.video_skill import VideoSkill


class Agent:
    def __init__(self, ctx):
        self.ctx = ctx
        self.llm_skill = LLMSkill(ctx)
        self.image_skill = ImageSkill(ctx)
        self.video_skill = VideoSkill(ctx)

    def generate_storyboard(self, novel_text, command_text, api_config, system_prompt):
        self.ctx.stop_flag = False
        threading.Thread(target=self.llm_skill.execute_generation,
                         args=(novel_text, command_text, api_config, system_prompt),
                         daemon=True).start()

    def generate_images(self, assets, api_config):
        self.ctx.stop_flag = False
        threading.Thread(target=self.image_skill.execute_batch_generation,
                         args=(assets, api_config),
                         daemon=True).start()

    def generate_video(self, prompt, api_config, duration, aspect_ratio, resolution, ref_urls):
        def task():
            try:
                self.ctx.log('[系统日志] 视频生成任务已启动...\n')
                self.video_skill.execute_generation(prompt, api_config, duration,
                                                    aspect_ratio, resolution, ref_urls)
            except Exception as e:
                self.ctx.log('\n[系统日志] 视频生成线程异常: ' + str(e) + '\n')
                self.ctx.push_ui_event('status', {'btn_gen_vid': 'normal', 'progress': False})
        threading.Thread(target=task, daemon=True).start()
