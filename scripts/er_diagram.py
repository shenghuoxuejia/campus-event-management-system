"""用 Pillow 生成 docs/images/er-diagram.png（不依赖 Graphviz，离线可用）。

用法：
    python scripts/er_diagram.py

表结构改动后重新运行即可，保证 ER 图与 database/schema.sql 一致。
"""

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs' / 'images' / 'er-diagram.png'

CANVAS = (1500, 740)
BOX_W = 320
HEADER_H = 28
ROW_H = 21
PAD_BOTTOM = 10

C_HEADER = (31, 78, 121)
C_BORDER = (128, 128, 128)
C_TEXT = (33, 33, 33)
C_TYPE = (110, 110, 110)
C_LINE = (150, 150, 150)
C_KEY = (191, 110, 24)

# (表名, x, y, [(列名, 类型, 标记, 外键指向)])
TABLES = [
    ('users', 40, 40, [
        ('user_id', 'int', 'PK', ''),
        ('name', 'varchar(100)', '', ''),
        ('email', 'varchar(100)', 'UQ', ''),
        ('password_hash', 'varchar(255)', '', ''),
        ('role', 'enum', '', ''),
        ('token_version', 'int', '', ''),
        ('created_at', 'datetime', '', ''),
    ]),
    ('venues', 40, 300, [
        ('venue_id', 'int', 'PK', ''),
        ('venue_name', 'varchar(100)', 'UQ', ''),
        ('location', 'varchar(255)', '', ''),
        ('capacity', 'int', 'CK', ''),
        ('available_status', 'tinyint(1)', 'CK', ''),
    ]),
    ('events', 560, 140, [
        ('event_id', 'int', 'PK', ''),
        ('title', 'varchar(200)', '', ''),
        ('description', 'text', '', ''),
        ('organizer_id', 'int', 'FK', 'users'),
        ('venue_id', 'int', 'FK', 'venues'),
        ('start_time', 'datetime', '', ''),
        ('end_time', 'datetime', '', ''),
        ('capacity', 'int', 'CK', ''),
        ('status', 'enum', '', ''),
        ('updated_at', 'datetime', '', ''),
    ]),
    ('registrations', 1100, 40, [
        ('registration_id', 'int', 'PK', ''),
        ('student_id', 'int', 'FK', 'users'),
        ('event_id', 'int', 'FK', 'events'),
        ('status', 'enum', '', ''),
        ('registered_at', 'datetime', '', ''),
        ('check_in_time', 'datetime', '', ''),
        ('cancelled_at', 'datetime', '', ''),
        ('cancelled_by', 'int', 'FK', 'users'),
        ('updated_at', 'datetime', '', ''),
    ]),
    ('event_categories', 1100, 320, [
        ('event_id', 'int', 'PK,FK', 'events'),
        ('category_id', 'int', 'PK,FK', 'categories'),
    ]),
    ('categories', 1100, 460, [
        ('category_id', 'int', 'PK', ''),
        ('category_name', 'varchar(100)', 'UQ', ''),
        ('description', 'text', '', ''),
    ]),
    ('comments', 560, 440, [
        ('comment_id', 'int', 'PK', ''),
        ('event_id', 'int', 'FK', 'events'),
        ('user_id', 'int', 'FK', 'users'),
        ('content', 'text', '', ''),
        ('created_at', 'datetime', '', ''),
    ]),
]

# (父表, 父列, 子表, 子列, 路径点列表)  首点=父表锚点，末点=子表锚点
RELATIONS = [
    ('users', 'user_id', 'events', 'organizer_id',
     [(360, 78), (560, 238)]),
    ('venues', 'venue_id', 'events', 'venue_id',
     [(360, 338), (560, 258)]),
    ('events', 'event_id', 'registrations', 'event_id',
     [(880, 178), (1100, 108)]),
    ('users', 'user_id', 'registrations', 'student_id',
     [(360, 98), (950, 98), (950, 68), (1100, 68)]),
    ('events', 'event_id', 'event_categories', 'event_id',
     [(880, 198), (1100, 348)]),
    ('categories', 'category_id', 'event_categories', 'category_id',
     [(1100, 498), (1020, 498), (1020, 368), (1100, 368)]),
    ('events', 'event_id', 'comments', 'event_id',
     [(710, 378), (710, 440)]),
    ('users', 'user_id', 'comments', 'user_id',
     [(360, 208), (450, 208), (450, 498), (560, 498)]),
]

LEGEND = [
    'PK 主键 / FK 外键 / UQ 唯一索引 / CK CHECK 约束',
    '枚举取值：users.role = student|organizer|admin；'
    'registrations.status = registered|cancelled|checked_in；events.status = open|closed',
    'registrations.cancelled_by -> users.user_id（ON DELETE SET NULL）；'
    '其余外键：registrations 均为 ON DELETE CASCADE',
    '所有时间列均为 DATETIME；events(venue_id, start_time, end_time) 建复合索引用于场地冲突检测',
    '报名状态决定余量统计：count(status <> cancelled)；唯一约束 uk_student_event 防重复报名',
]


def _font(size, bold=False):
    # 英文数字用 Arial / Segoe UI，找不到时退回雅黑、宋体或默认位图字体
    candidates = ['arialbd.ttf', 'segoeuib.ttf'] if bold else ['arial.ttf', 'segoeui.ttf']
    candidates += ['msyhbd.ttc'] if bold else []
    candidates += ['msyh.ttc', 'simsun.ttc']
    for name in candidates:
        path = Path('C:/Windows/Fonts') / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _font_cjk(size, bold=False):
    """含中文的文本必须用带中文字形的字体（Arial 不含汉字，会画成方块）。"""
    candidates = ['msyhbd.ttc', 'msyh.ttc', 'simhei.ttf', 'simsun.ttc']
    for name in candidates:
        path = Path('C:/Windows/Fonts') / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def box_height(rows):
    return HEADER_H + ROW_H * len(rows) + PAD_BOTTOM


def draw_table(draw, name, x, y, rows, f_head, f_cell, f_key, f_type):
    h = box_height(rows)
    draw.rectangle([x, y, x + BOX_W, y + h], fill=(255, 255, 255), outline=C_BORDER)
    draw.rectangle([x, y, x + BOX_W, y + HEADER_H], fill=C_HEADER, outline=C_BORDER)
    draw.text((x + 10, y + 4), name, font=f_head, fill=(255, 255, 255))
    for i, (col, typ, mark, ref) in enumerate(rows):
        ry = y + HEADER_H + i * ROW_H
        if i:
            draw.line([x, ry, x + BOX_W, ry], fill=(236, 236, 236))
        if mark:
            draw.text((x + 8, ry + 5), mark, font=f_key, fill=C_KEY)
        draw.text((x + 56, ry + 3), col, font=f_cell, fill=C_TEXT)
        right = typ + (f' -> {ref}' if ref else '')
        tw = draw.textlength(right, font=f_type)
        draw.text((x + BOX_W - 10 - tw, ry + 4), right, font=f_type, fill=C_TYPE)
    return (x, y, x + BOX_W, y + h)


def arrow(draw, pts, f_cell):
    draw.line(pts, fill=C_LINE, width=2)
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    if x1 == x2:                       # 竖线
        d = 1 if y2 > y1 else -1
        draw.polygon([(x2, y2), (x2 - 5, y2 - 8 * d), (x2 + 5, y2 - 8 * d)], fill=C_LINE)
        draw.text((x2 + 8, y2 - 18 * (1 if d > 0 else -1)), 'N', font=f_cell, fill=C_KEY)
    else:                              # 横线
        d = 1 if x2 > x1 else -1
        draw.polygon([(x2, y2), (x2 - 8 * d, y2 - 5), (x2 - 8 * d, y2 + 5)], fill=C_LINE)
        draw.text((x2 - 12 * d, y2 - 20), 'N', font=f_cell, fill=C_KEY)

    sx, sy = pts[0]
    nx, ny = pts[1]
    if sx == nx:                       # 起点是竖线
        draw.text((sx + 8, sy + 2), '1', font=f_cell, fill=C_KEY)
    else:
        draw.text((sx + 8, sy - 18), '1', font=f_cell, fill=C_KEY)


def main():
    img = Image.new('RGB', CANVAS, (255, 255, 255))
    draw = ImageDraw.Draw(img)
    f_head = _font(15, bold=True)
    f_cell = _font(12)
    f_key = _font(10, bold=True)
    f_type = _font(11)
    f_title = _font(19, bold=True)
    f_note = _font_cjk(12)

    draw.text((40, 8), 'Campus Events - Database ER Diagram (7 tables)',
              font=f_title, fill=C_HEADER)

    for name, x, y, rows in TABLES:
        draw_table(draw, name, x, y, rows, f_head, f_cell, f_key, f_type)

    for _p, _pc, _c, _cc, pts in RELATIONS:
        arrow(draw, pts, f_cell)

    y = 636
    for i, text in enumerate(LEGEND):
        draw.text((40, y + i * 20), text, font=f_note, fill=(90, 90, 90))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    print('written', OUT, os.path.getsize(OUT), 'bytes')


if __name__ == '__main__':
    main()
