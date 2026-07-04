import base64
import copy
import hashlib
import io
import math
import os
import time

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

from schemas import AuditData

TEMPLATE_PATH = os.path.join("assets", "template.pptx")

# Геометрия слайда кейса (портрет 7559675 x 10691813 EMU):
# таблица top=2444005, блок "Ответ ИТ-руководства" top~8339406, картинка в шаблоне 3111500.
CASE_TABLE_CHARS_PER_LINE = 55   # ~14pt на ширине таблицы 6.26"
CASE_TABLE_LINE_EMU = 220_000    # высота строки текста при 14pt
CASE_TABLE_ROW_PAD_EMU = 100_000
CASE_IMAGE_MARGIN_EMU = 150_000
CASE_IMAGE_MAX_EMU = 3_111_500
CASE_IMAGE_MIN_EMU = 1_100_000


def perfect_replace(shape, new_text):
    if not hasattr(shape, "text_frame"):
        return
    tf = shape.text_frame
    if not tf.paragraphs:
        return

    first_run = None
    first_p_idx = 0
    for i, p in enumerate(tf.paragraphs):
        if p.runs:
            first_run = p.runs[0]
            first_p_idx = i
            break

    if not first_run:
        shape.text = new_text
        return

    first_run.text = new_text

    for i in range(1, len(tf.paragraphs[first_p_idx].runs)):
        tf.paragraphs[first_p_idx].runs[i].text = ""

    for i in range(len(tf.paragraphs)):
        if i == first_p_idx:
            continue
        for r in tf.paragraphs[i].runs:
            r.text = ""


def replace_table_cell(table, r, c, new_text):
    if not table:
        return
    cell = table.cell(r, c)
    perfect_replace(cell, new_text)


def get_table(slide):
    for s in slide.shapes:
        if s.has_table:
            return s.table
    return None


def get_table_shape(slide):
    for s in slide.shapes:
        if s.has_table:
            return s
    return None


def get_title(slide, fallback_idx=1):
    for s in slide.shapes:
        if hasattr(s, 'text') and s.text and 'Кейс' in s.text:
            return s
    if len(slide.shapes) > fallback_idx:
        return slide.shapes[fallback_idx]
    return None


def get_priority(slide):
    for s in slide.shapes:
        if hasattr(s, 'text') and s.text and 'ПРИОРИТЕТ' in s.text:
            return s
    return None


def _delete_shape(shape):
    shape._element.getparent().remove(shape._element)


def _image_md5(shape):
    try:
        return hashlib.md5(shape.image.blob).hexdigest()
    except Exception:
        return None


def remove_personal_marks(prs):
    """Убирает фото аудитора и внутренний номер (вн. 162) из отчета."""
    title_slide = prs.slides[0]

    # Фото на титуле — картинка в нижней трети слайда (лого сидит вверху)
    photo_md5 = None
    for s in list(title_slide.shapes):
        if s.shape_type == MSO_SHAPE_TYPE.PICTURE and s.top and s.top > prs.slide_height * 0.6:
            photo_md5 = _image_md5(s)
            _delete_shape(s)

    # То же фото на других слайдах (в т.ч. picture placeholder на слайде "Ревью")
    if photo_md5:
        for slide in prs.slides:
            for s in list(slide.shapes):
                if s.shape_type in (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.PLACEHOLDER):
                    if _image_md5(s) == photo_md5:
                        _delete_shape(s)

    # Внутренний номер: "+7 ... вн. 162" -> оставляем только основной номер
    for slide in prs.slides:
        for s in slide.shapes:
            if not (hasattr(s, 'text') and s.text and '162' in s.text and 'вн' in s.text):
                continue
            for p in s.text_frame.paragraphs:
                for r in p.runs:
                    if 'вн' in r.text or '162' in r.text:
                        r.text = ''


def fix_title_colors(prs):
    """Титульный лист: текст без явного цвета рендерится черным — делаем белым."""
    for s in prs.slides[0].shapes:
        if not (hasattr(s, 'text_frame') and s.has_text_frame):
            continue
        for p in s.text_frame.paragraphs:
            for r in p.runs:
                if r.text.strip() and r.font.color.type is None:
                    r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)


def _delete_table_row(table, row_idx):
    tr = table.rows[row_idx]._tr
    tr.getparent().remove(tr)


def _clone_table_row(table, src_idx):
    """Клонирует строку таблицы (с форматированием) и добавляет в конец."""
    src_tr = table.rows[src_idx]._tr
    new_tr = copy.deepcopy(src_tr)
    src_tr.getparent().append(new_tr)
    return len(table.rows) - 1


def _estimate_text_lines(text: str) -> int:
    lines = 0
    for chunk in text.split('\n'):
        lines += max(1, math.ceil(len(chunk) / CASE_TABLE_CHARS_PER_LINE))
    return lines


def layout_case_image(slide, img_path):
    """Ставит картинку кейса под таблицей, ужимая так, чтобы не налезать
    на текст сверху и блок 'Ответ ИТ-руководства' снизу."""
    table_shape = get_table_shape(slide)

    # Нижняя граница зоны: группа "Ответ ИТ-руководства"
    bottom_limit = None
    for s in slide.shapes:
        if s.shape_type == MSO_SHAPE_TYPE.GROUP:
            bottom_limit = s.top
            break
    if bottom_limit is None:
        bottom_limit = int(prs_height_fallback := 8_300_000)

    # Верхняя граница: оценка фактической высоты таблицы с текстом
    top_limit = 4_350_883  # позиция картинки в шаблоне как fallback
    old_center_x = None
    for s in list(slide.shapes):
        if s.shape_type == MSO_SHAPE_TYPE.PICTURE:
            old_center_x = s.left + s.width // 2
            _delete_shape(s)

    if table_shape is not None:
        t = table_shape.table
        est = 0
        for r in range(len(t.rows)):
            est += _estimate_text_lines(t.cell(r, 0).text) * CASE_TABLE_LINE_EMU
            est += CASE_TABLE_ROW_PAD_EMU
        top_limit = table_shape.top + est

    available = bottom_limit - CASE_IMAGE_MARGIN_EMU - (top_limit + CASE_IMAGE_MARGIN_EMU)
    size = max(CASE_IMAGE_MIN_EMU, min(CASE_IMAGE_MAX_EMU, available))

    slide_width = 7_559_675
    center_x = old_center_x if old_center_x else slide_width // 2
    left = int(center_x - size // 2)
    top = int(top_limit + CASE_IMAGE_MARGIN_EMU)
    slide.shapes.add_picture(img_path, Emu(left), Emu(top), Emu(size), Emu(size))


def build_pptx(data: AuditData, audit_type: str = "full") -> io.BytesIO:
    prs = Presentation(TEMPLATE_PATH)
    include_recommendations = audit_type == "full"

    temp_images = []
    for i, case in enumerate(data.cases):
        if case.image_b64 and case.image_b64.startswith("data:image"):
            img_data = base64.b64decode(case.image_b64.split(",")[1])
            img_path = f"/tmp/case_img_{i}_{int(time.time())}.jpg"
            with open(img_path, "wb") as f:
                f.write(img_data)
            temp_images.append((i, img_path))

    try:
        remove_personal_marks(prs)
        fix_title_colors(prs)

        for s in prs.slides[0].shapes:
            if hasattr(s, 'text') and s.text:
                if 'Клиент' in s.text or 'Курылыс' in s.text:
                    perfect_replace(s, f"Клиент: {data.client_name}")

        for s in prs.slides[2].shapes:
            if hasattr(s, 'text') and s.text and 'аудита' in s.text:
                perfect_replace(s, data.review)

        prio_counts = {"ПЕРВЫЙ ПРИОРИТЕТ": 0, "ВТОРОЙ ПРИОРИТЕТ": 0, "ТРЕТИЙ ПРИОРИТЕТ": 0}
        cat_counts = {
            "I. Серверная инфраструктура": {"ПЕРВЫЙ ПРИОРИТЕТ": 0, "ВТОРОЙ ПРИОРИТЕТ": 0, "ТРЕТИЙ ПРИОРИТЕТ": 0},
            "II. Сеть и ИТ-поддержка": {"ПЕРВЫЙ ПРИОРИТЕТ": 0, "ВТОРОЙ ПРИОРИТЕТ": 0, "ТРЕТИЙ ПРИОРИТЕТ": 0}
        }

        for case in data.cases:
            prio_counts[case.priority] += 1
            if case.category in cat_counts:
                cat_counts[case.category][case.priority] += 1

        t3 = get_table(prs.slides[3])
        if t3:
            replace_table_cell(t3, 0, 0, str(prio_counts["ПЕРВЫЙ ПРИОРИТЕТ"]))
            replace_table_cell(t3, 0, 1, str(prio_counts["ВТОРОЙ ПРИОРИТЕТ"]))
            replace_table_cell(t3, 0, 2, str(prio_counts["ТРЕТИЙ ПРИОРИТЕТ"]))

        t4 = get_table(prs.slides[4])
        if t4:
            cats = list(cat_counts.keys())
            for r, cat in enumerate(cats):
                replace_table_cell(t4, r, 0, cat)
                replace_table_cell(t4, r, 1, str(cat_counts[cat]["ПЕРВЫЙ ПРИОРИТЕТ"]))
                replace_table_cell(t4, r, 2, str(cat_counts[cat]["ВТОРОЙ ПРИОРИТЕТ"]))
                replace_table_cell(t4, r, 3, str(cat_counts[cat]["ТРЕТИЙ ПРИОРИТЕТ"]))

            # Лишние строки удаляем целиком, чтобы таблица не "плыла"
            for r in range(len(t4.rows) - 1, len(cats) - 1, -1):
                _delete_table_row(t4, r)

        for s in prs.slides[5].shapes:
            if hasattr(s, 'text') and s.text and 'I.' in s.text:
                perfect_replace(s, "I. Серверная инфраструктура")

        for s in prs.slides[9].shapes:
            if hasattr(s, 'text') and s.text and 'II.' in s.text:
                perfect_replace(s, "II. Сеть и ИТ-поддержка")

        case_slides = [6, 7, 8, 10, 11]
        for i, case in enumerate(data.cases):
            if i >= len(case_slides):
                break
            slide = prs.slides[case_slides[i]]
            perfect_replace(get_title(slide), f"Кейс {i+1}: {case.title}")

            if get_priority(slide):
                perfect_replace(get_priority(slide), case.priority)

            t = get_table(slide)
            if t:
                replace_table_cell(t, 0, 0, f"Уязвимость: {case.vulnerability}")
                replace_table_cell(t, 1, 0, f"Риски: {case.risk}")
                if include_recommendations and case.recommendation:
                    rec_row = _clone_table_row(t, 1)
                    replace_table_cell(t, rec_row, 0, f"Рекомендации: {case.recommendation}")

            img_path_tuple = next((x for x in temp_images if x[0] == i), None)
            if img_path_tuple:
                layout_case_image(slide, img_path_tuple[1])

        conc_text = "\n".join([f"• {c}" for c in data.conclusions])
        for s in prs.slides[16].shapes:
            if hasattr(s, 'text') and s.text and 'Вариант 1' in s.text:
                perfect_replace(s, conc_text)

        for i in sorted([15, 14, 13, 12], reverse=True):
            rId = prs.slides._sldIdLst[i].rId
            prs.part.drop_rel(rId)
            del prs.slides._sldIdLst[i]

        output_io = io.BytesIO()
        prs.save(output_io)
        output_io.seek(0)
        return output_io
    finally:
        for _, img_path in temp_images:
            if os.path.exists(img_path):
                os.remove(img_path)
