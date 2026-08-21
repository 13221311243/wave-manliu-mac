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

    def generate_storyboard(self, novel_text, command_text, api_config, system_prompt,
                            stop_marker=None, extra_context=''):
        self.ctx.stop_flag = False
        threading.Thread(target=self.llm_skill.execute_generation,
                         args=(novel_text, command_text, api_config, system_prompt,
                               stop_marker, extra_context),
                         daemon=True).start()

    def review_output(self, api_config, review_prompt, system_prompt):
        """2026-08-21 监督层评级调用（线程内执行，避免阻塞 UI）"""
        result = {}

        def _task():
            try:
                result['report'] = self.llm_skill.execute_review(api_config, review_prompt, system_prompt)
            except Exception as e:
                result['error'] = str(e)

        t = threading.Thread(target=_task, daemon=True)
        t.start()
        t.join(timeout=90)
        return result.get('report')

    def generate_images(self, assets, api_config):
        self.ctx.stop_flag = False
        threading.Thread(target=self.image_skill.execute_batch_generation,
                         args=(assets, api_config),
                         daemon=True).start()

    def generate_video(self, prompt, api_config, duration, aspect_ratio, resolution, ref_urls, local_refs=None):
        def task():
            try:
                self.ctx.log('[系统日志] 视频生成任务已启动...\n')
                self.video_skill.execute_generation(prompt, api_config, duration,
                                                    aspect_ratio, resolution, ref_urls,
                                                    local_refs=local_refs)
            except Exception as e:
                self.ctx.log('\n[系统日志] 视频生成线程异常: ' + str(e) + '\n')
                self.ctx.push_ui_event('status', {'btn_gen_vid': 'normal', 'progress': False})
        threading.Thread(target=task, daemon=True).start()
