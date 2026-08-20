# -*- coding: utf-8 -*-
"""skills/doc_reader.py —— 小说 doc/docx 文件解析（纯标准库，无第三方依赖）

- .docx：zip 包，解析 word/document.xml 提取段落文本
- .doc：老二进制格式，优先用 win32com（Word COM）转换，失败则提示
- 章节切分：按「第X章/第X节/Chapter X/卷X」标题自动切分
"""
import os, re, zipfile, sys

def read_docx_text(path):
    """解析 .docx 返回纯文本（按段落拼接，保留换行）"""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read('word/document.xml').decode('utf-8', 'ignore')
    except Exception:
        raise RuntimeError('无法读取 docx（文件损坏或格式不支持）')
    # 提取 <w:p> 段落（含 w:t 文本），保留段落边界
    paras = []
    for pm in re.finditer(r'<w:p[ >].*?</w:p>', xml, re.S):
        p = pm.group(0)
        texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', p, re.S)
        # XML 实体反转义
        line = ''.join(texts)
        line = (line.replace('&amp;', '&').replace('&lt;', '<')
                    .replace('&gt;', '>').replace('&quot;', '"')
                    .replace('&apos;', "'"))
        paras.append(line)
    return '\n'.join(paras)


def read_doc_text(path):
    """解析 .doc（老格式）——用 win32com 调 Word COM 转换（需本机装 Word/WPS）"""
    try:
        import win32com.client as win32
        import pythoncom
        pythoncom.CoInitialize()
        word = win32.DispatchEx('Word.Application')
        word.Visible = False
        try:
            doc = word.Documents.Open(os.path.abspath(path), ReadOnly=True)
            text = doc.Content.Text
            doc.Close(False)
            return text
        finally:
            word.Quit()
    except Exception as e:
        raise RuntimeError('无法解析 .doc（需要本机安装 Word 或 WPS；建议另存为 .docx）: %s' % e)


def read_novel_file(path):
    """读取小说文件，返回纯文本。支持 .docx / .doc / .txt"""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.docx':
        return read_docx_text(path)
    if ext == '.doc':
        return read_doc_text(path)
    if ext == '.txt':
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    # 其他：尝试按文本读
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


# 章节标题匹配：第X章 / 第X节 / 第X回 / Chapter X / CHAPTER X / 卷X / 楔子 / 序章 / 番外
CHAPTER_RE = re.compile(
    r'^\s*(第\s*[0-9一二三四五六七八九十百千零两]+\s*[章回节卷部集]'
    r'|Chapter\s+\d+'
    r'|CHAPTER\s+\d+'
    r'|楔子|序章|序言|引子|尾声|番外|后记|前言)'
    r'\s*[：:、.．\s]*(.*)$'
)
# 标题行不允许出现的正文标点（标题通常无句号/逗号/感叹号等）
_TITLE_BAD_CHARS = '。！？，、；：""''（）《》【】'


def _is_chapter_title(line):
    """判断一行是否为章节标题：匹配章节正则 + 长度限制 + 不含正文标点"""
    stripped = line.strip()
    if not stripped or len(stripped) > 40:
        return False
    if not CHAPTER_RE.match(stripped):
        return False
    # 标题行不应含正文标点（标题如"第一章 风起"干净；正文行"第一章内容。…"被排除）
    for ch in _TITLE_BAD_CHARS:
        if ch in stripped:
            return False
    return True


def split_chapters(text):
    """按章节标题切分小说文本。

    返回 [(章节名, 章节正文), ...]。找不到章节标题时返回 [('全文', text)]。
    识别标题行：独立成行、符合章节正则、长度≤40、不含正文标点。
    标题前的开头正文（引子/序言等无标题段落）并入第一章作为前缀，不丢失剧情。
    """
    lines = text.split('\n')
    chapters = []      # [(title, [lines])]
    cur_title = None
    cur_lines = []
    prefix = []        # 标题出现前的开头正文（引子/序言段）
    for line in lines:
        if _is_chapter_title(line):
            # 保存上一章
            if cur_title is not None:
                chapters.append((cur_title, '\n'.join(cur_lines).strip()))
            cur_title = line.strip()
            # 开头正文并入第一章（作为前缀），避免小说开头的引子/序言剧情丢失
            cur_lines = prefix if prefix else []
            prefix = []
        else:
            if cur_title is not None:
                cur_lines.append(line)
            else:
                prefix.append(line)
    if cur_title is not None:
        chapters.append((cur_title, '\n'.join(cur_lines).strip()))
    if not chapters and text.strip():
        return [('全文', text.strip())]
    return chapters


if __name__ == '__main__':
    # 自测
    sample = """第一章 初见
这是第一章的内容。
他走向她。

第二章 离别
这是第二章的内容。
她转身离开。
"""
    chs = split_chapters(sample)
    for t, body in chs:
        print('章节:', t, '| 长度:', len(body))
