# -*- coding: utf-8 -*-
"""skills.llm_skill —— 从 wave漫流 exe PYZ 精确重构（2026-08-20，逻辑逐字节对齐原 code 对象）

execute_generation: OpenAI 兼容流式聊天 + 断线续写 + 长内容自动续写循环（max_loops=15）
extract_assets:     从分镜全文提取角色/道具/场景资产（英文提示词）
"""
import time
import openai
import httpx
import re
from skills.base_skill import BaseSkill


class LLMSkill(BaseSkill):
    def execute_generation(self, novel_text, command_text, api_config, system_prompt,
                           stop_marker=None, extra_context=''):
        """生成主调用。stop_marker: 检测到该标记即停止（分段生成用，如 [STAGE1_DONE]）；
        extra_context: 追加到用户消息的额外上下文（重新生成时携带评级意见）。"""
        current_chunk = ''
        first_chunk_received = False

        api_key = api_config.get('api_key')
        base_url = api_config.get('base_url')
        model_name = api_config.get('model_name')

        timeout_config = httpx.Timeout(60.0, read=120.0)
        http_client = httpx.Client(timeout=timeout_config, trust_env=False)
        client = openai.OpenAI(api_key=api_key, base_url=base_url,
                               timeout=timeout_config, http_client=http_client)

        user_prompt = '【小说文本】\n' + novel_text
        if command_text:
            user_prompt += '【附加指令】\n' + command_text + '\n\n'
        if extra_context:
            user_prompt += '【本轮生成要求】\n' + extra_context + '\n\n'

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]

        max_loops = 15
        is_done = False

        try:
            for i in range(max_loops):
                if self.ctx.stop_flag:
                    break
                if is_done:
                    break

                retry_count = 0
                max_retries = 5
                chunk_content = ''
                stream = None
                stream_closed_normally = False

                while retry_count < max_retries:
                    try:
                        self.ctx.log('[系统日志] 正在发起第 %d 次请求...\n' % (i + 1))
                        stream = client.chat.completions.create(
                            model=model_name,
                            messages=messages,
                            stream=True,
                            temperature=0.7,
                        )
                        for chunk in stream:
                            if self.ctx.stop_flag:
                                stream.close()
                                break
                            if not chunk.choices:
                                continue
                            delta = chunk.choices[0].delta
                            if delta.content is None:
                                continue
                            text = delta.content
                            chunk_content += text
                            if not first_chunk_received:
                                first_chunk_received = True
                                self.ctx.log('[系统日志] 已收到响应，正在生成内容...\n\n')
                            # 2026-08-21 修复：每个内容块都必须推送到 UI（此前只在
                            # [ALL_DONE]/stop_marker 时推送，导致界面看不到任何生成内容）
                            self.ctx.push_ui_event('stream', {'text': text})
                            if '[ALL_DONE]' in text:
                                self.ctx.push_ui_event('stream', {'text': text})
                            elif stop_marker and stop_marker in text:
                                self.ctx.push_ui_event('stream', {'text': text})
                        stream_closed_normally = True
                        # 2026-08-21 修复致命死循环：流式正常结束后必须跳出重试循环，
                        # 否则 retry_count 恒为 0 → while 条件永远满足 → 无限发起新请求
                        break
                    except Exception as conn_err:
                        err_str = str(conn_err).lower()
                        # 2026-08-22 断点续跑：401/402/余额不足/认证失败 = 账户问题，不重试、
                        # 立即中断并通知 UI 写断点（客户充值后可点「继续上次任务」续跑，不用从头开始）
                        _acct_issue = ('401' in err_str or '402' in err_str
                                       or 'insufficient' in err_str or 'balance' in err_str
                                       or 'quota' in err_str or 'authentication' in err_str
                                       or 'unauthorized' in err_str or 'invalid api key' in err_str
                                       or '余额' in err_str or '欠费' in err_str or '计费' in err_str)
                        if _acct_issue:
                            self.ctx.log('\n\n[系统日志: 账户问题（余额不足/认证失败），任务已暂停。'
                                         '充值/修复后点「🔄 继续上次任务」即可续跑，无需从头开始。] 错误：%s\n'
                                         % str(conn_err)[:300])
                            self.ctx.push_ui_event('llm_interrupted', {'reason': 'account', 'error': str(conn_err)[:300]})
                            raise conn_err
                        is_disconnect = ('incomplete chunked read' in err_str
                                         or 'peer closed' in err_str
                                         or 'connection reset' in err_str)
                        if is_disconnect:
                            if chunk_content:
                                self.ctx.log('\n[系统日志: 服务器中断连接，自动续写...]\n')
                                # 跳出重试循环，保留已收内容继续后续续写逻辑
                                break
                            retry_count += 1
                            if retry_count >= max_retries:
                                raise Exception('服务器连续断开，请稍后再试。')
                            self.ctx.log('\n[系统日志: 强制重试 (%d/%d)...]\n' % (retry_count, max_retries))
                            time.sleep(2)
                        else:
                            retry_count += 1
                            if retry_count >= max_retries:
                                raise conn_err
                            self.ctx.log('\n[系统日志: 网络异常，重试 (%d/%d)...]\n' % (retry_count, max_retries))
                            time.sleep(3)

                if self.ctx.stop_flag:
                    break

                if '[ALL_DONE]' in chunk_content:
                    is_done = True
                    break

                # 2026-08-21 分段生成：检测到阶段停止标记 → 结束本轮（不再自动续写）
                if stop_marker and stop_marker in chunk_content:
                    is_done = True
                    self.ctx.log('\n[系统日志] 检测到阶段标记 %s，本阶段生成完毕。\n' % stop_marker)
                    break

                if stream_closed_normally and '剪映专业剪辑指导方案' in current_chunk + chunk_content:
                    self.ctx.log('\n[系统日志] 检测到已输出完整剪辑方案，生成完毕。\n')
                    is_done = True
                    break

                if not chunk_content:
                    if i == 0:
                        self.ctx.log('\n\n[系统提示：API 未返回任何内容。请检查配置。]')
                    break

                if chunk_content:
                    current_chunk += chunk_content
                    messages.append({'role': 'assistant', 'content': chunk_content})
                    _cont_marker = stop_marker if stop_marker else '[ALL_DONE]'
                    messages.append({'role': 'user',
                                     'content': '请严格接着上次未写完的内容继续输出。如果本阶段已全部完毕，请单独输出 %s' % _cont_marker})
                    self.ctx.log('\n\n[系统日志: 内容较长，正在自动续写...]\n\n')
                    # 下一轮 for i 继续
                else:
                    self.ctx.log('\n\n[系统日志: 模型已停止输出。]')

            if not first_chunk_received and not self.ctx.stop_flag:
                self.ctx.log('\n\n[系统提示：生成结束，但未获取到有效内容。]')
        except Exception as e:
            self.ctx.log('\n\n[生成失败] 错误信息：' + str(e))
            self.ctx.push_ui_event('error', {'msg': str(e)})

        self.ctx.push_ui_event('status',
                               {'text': '生成完毕', 'btn_generate': 'normal',
                                'btn_stop': 'disabled', 'progress': False})

    def execute_review(self, api_config, review_prompt, system_prompt):
        """2026-08-21 监督层评级调用（非流式，一次性返回评级报告）。
        返回字符串评级报告，或 None（失败）。"""
        try:
            api_key = api_config.get('api_key')
            base_url = api_config.get('base_url')
            model_name = api_config.get('model_name')

            timeout_config = httpx.Timeout(60.0, read=120.0)
            http_client = httpx.Client(timeout=timeout_config, trust_env=False)
            client = openai.OpenAI(api_key=api_key, base_url=base_url,
                                   timeout=timeout_config, http_client=http_client)

            messages = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': review_prompt},
            ]
            resp = client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=False,
                temperature=0.3,
            )
            if resp and resp.choices:
                return resp.choices[0].message.content or ''
            return None
        except Exception as e:
            self.ctx.log('\n\n[评级失败] 错误信息：' + str(e))
            return None

    def extract_assets(self, full_text):
        """从生成的剧本中提取资产名称和英文提示词"""
        assets = []
        patterns = [
            (r'===== 角色 \\d+ · (.*?) =====.*?【英文AI提示词】\\s*(.*?)(?=\\n【|\\n=====|\\n-----|\\n[A-G]\\. |\\Z)', 'character'),
            (r'===== 道具资产卡 · (.*?) =====.*?【英文AI提示词】\\s*(.*?)(?=\\n【|\\n=====|\\n-----|\\n[A-G]\\. |\\Z)', 'prop'),
            (r'【场景 \\d+】(.*?)\\n.*?【英文AI提示词】\\s*(.*?)(?=\\n【|\\n=====|\\n-----|\\n[A-G]\\. |\\Z)', 'scene'),
        ]
        for pattern, asset_type in patterns:
            matches = re.findall(pattern, full_text, re.S)
            for match in matches:
                name = match[0].strip()
                prompt_en = match[1].strip().replace('\n', ' ')
                if not name or not prompt_en:
                    continue
                assets.append({'type': asset_type, 'name': name, 'prompt_en': prompt_en})
        return assets
