# -*- coding: utf-8 -*-
"""skills.base_skill —— 从 wave漫流 exe PYZ 精确重构（2026-08-20）"""
import queue


class AppContext:
    def __init__(self):
        self.ui_queue = queue.Queue()
        self.stop_flag = False
        self.image_history = []

    def push_ui_event(self, event_type, data=None):
        self.ui_queue.put((event_type, data))

    def log(self, text):
        self.push_ui_event('log', {'text': text})


class BaseSkill:
    def __init__(self, ctx):
        self.ctx = ctx
