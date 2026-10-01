"""Lossless source content, kept independently from the LLM's short audit cases.

Only local parts of DOCX packages are read. Files never become instructions,
are never executed, and are not inserted into the shared RAG/image library.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from PIL import Image, UnidentifiedImageError
from lxml.etree import XMLSyntaxError

STORE = Path(os.environ.get("PROTOTYPE_DIR", "db/prototypes"))
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 45 * 1024 * 1024
MAX_FILES = 5
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_CONTEXT_CHARS = 180_000


class PrototypeError(ValueError):
    pass


class Numbering:
    def __init__(self, document):
        self.document, self.values = document, {}

    def prefix(self, paragraph):
        properties = paragraph._p.pPr
        numbering = properties.numPr if properties is not None else None
        style = paragraph.style
        while numbering is None and style is not None:
            properties = style.element.pPr
            numbering = properties.numPr if properties is not None else None
            style = style.base_style
        if numbering is None or numbering.numId is None or numbering.numId.val == 0:
            return ""
        num_id = numbering.numId.val
        level = numbering.ilvl.val if numbering.ilvl is not None else 0
        root = self.document.part.numbering_part.element
        definitions = root.xpath(f'./w:num[@w:numId="{num_id}"]')
        if not definitions:
            raise PrototypeError("Не удалось прочитать нумерацию Word. Сохраните файл заново.")
        definition = definitions[0]
        abstract_id = definition.find(qn("w:abstractNumId")).get(qn("w:val"))
        abstract = root.xpath(f'./w:abstractNum[@w:abstractNumId="{abstract_id}"]')[0]

        def spec(index):
            override = [node for node in definition.findall(qn("w:lvlOverride")) if node.get(qn("w:ilvl")) == str(index)]
            levels = override[0].findall(qn("w:lvl")) if override else []
            if not levels:
                levels = [node for node in abstract.findall(qn("w:lvl")) if node.get(qn("w:ilvl")) == str(index)]
            if not levels:
                raise PrototypeError("Не удалось прочитать уровень списка Word")
            element = levels[0]
            def value(tag, default):
                node = element.find(qn("w:" + tag))
                return node.get(qn("w:val")) if node is not None else default
            start = value("start", "1")
            if override:
                node = override[0].find(qn("w:startOverride"))
                if node is not None:
                    start = node.get(qn("w:val"))
            return value("numFmt", "decimal"), value("lvlText", "%1."), int(start)

        fmt, pattern, start = spec(level)
        self.values[(num_id, level)] = self.values.get((num_id, level), start - 1) + 1
        for key in list(self.values):
            if key[0] == num_id and key[1] > level:
                del self.values[key]
        if fmt == "bullet":
            return "• "

        def formatted(match):
            index = int(match.group(1)) - 1
            form, _, first = spec(index)
            number = self.values.get((num_id, index), first)
            if form in {"lowerLetter", "upperLetter"}:
                value, remaining = "", number
                while remaining:
                    remaining, letter = divmod(remaining - 1, 26)
                    value = chr(65 + letter) + value
                return value.lower() if form == "lowerLetter" else value
            if form in {"lowerRoman", "upperRoman"}:
                value, remaining = "", number
                for amount, letters in [(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),(50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]:
                    count, remaining = divmod(remaining, amount)
                    value += letters * count
                return value.lower() if form == "lowerRoman" else value
            return str(number)
        return re.sub(r"%([1-9])", formatted, pattern) + " "


def _directory(source_id):
    if not re.fullmatch(r"[a-f0-9]{32}", source_id):
        raise PrototypeError("Некорректный идентификатор исходного файла")
    return STORE / source_id


def load(source_id):
    try:
        return json.loads((_directory(source_id) / "manifest.json").read_text("utf-8"))
    except FileNotFoundError:
        raise PrototypeError("Исходный файл недоступен. Загрузите его повторно.") from None


def summary(document):
    return {k: document[k] for k in ("id", "filename", "sha256", "paragraphs", "tables", "images", "warnings")}


def image_bytes(document, block):
    # Manifest paths are application-generated, never supplied in API payloads.
    name = block["asset"]
    if not re.fullmatch(r"[a-f0-9]{64}\.[a-z]+", name):
        raise PrototypeError("Повреждены материалы исходного файла")
    return (_directory(document["id"]) / name).read_bytes()


def discard(source_id):
    shutil.rmtree(_directory(source_id), ignore_errors=True)


def ingest(filename, raw):
    filename = Path(filename.replace("\\", "/")).name
    if Path(filename).suffix.lower() != ".docx":
        raise PrototypeError("Поддерживаются прототипы Word (.docx)")
    if len(raw) > MAX_FILE_BYTES:
        raise PrototypeError("Файл больше 20 МБ")
    try:
        with ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > 4000 or sum(i.file_size for i in infos) > MAX_EXPANDED_BYTES:
                raise PrototypeError("Слишком большой распакованный документ")
            if any(i.flag_bits & 1 for i in infos):
                raise PrototypeError("Снимите пароль с документа перед загрузкой")
            if "word/document.xml" not in archive.namelist():
                raise PrototypeError("Файл не является документом DOCX")
        doc = Document(io.BytesIO(raw))
    except (BadZipFile, KeyError, OSError, ValueError, XMLSyntaxError) as exc:
        if isinstance(exc, PrototypeError):
            raise
        raise PrototypeError("Не удалось прочитать DOCX. Проверьте файл и сохраните его заново в Word.") from exc

    # Embedded Office objects/charts/SmartArt cannot silently disappear.
    if doc.element.xpath(".//w:object | .//w:altChunk") or doc.element.xpath(".//w:drawing[not(.//a:blip)]"):
        raise PrototypeError("В документе есть встроенные объекты, диаграммы или SmartArt. Сохраните их в Word как изображения и загрузите файл повторно.")

    blocks, assets, warnings = [], {}, []
    numbering = Numbering(doc)
    section = "Исходные материалы"
    counts = {"paragraphs": 0, "tables": 0, "images": 0}
    cell_text = {}

    def read_cell(cell):
        if cell._tc not in cell_text:
            paragraphs = [Paragraph(p, doc) for p in cell._tc.xpath(".//w:p")]
            cell_text[cell._tc] = "\n".join(numbering.prefix(p) + p.text for p in paragraphs)
        return cell_text[cell._tc]

    def pictures(element, caption="", part=None):
        nonlocal section
        part = part or doc.part
        nodes = [node for node in element.iter() if node.tag.rsplit("}", 1)[-1] in ("blip", "imagedata")]
        if nodes and not caption and blocks and blocks[-1]["kind"] == "paragraph" and len(blocks[-1]["text"]) <= 180:
            caption = blocks.pop()["text"]
        for node in nodes:
            rid = node.get(qn("r:embed")) or node.get(qn("r:id"))
            if not rid or rid not in part.rels or part.rels[rid].is_external:
                raise PrototypeError("В документе есть внешнее изображение. Вставьте его в DOCX, а не ссылкой.")
            raw_image = part.rels[rid].target_part.blob
            try:
                with Image.open(io.BytesIO(raw_image)) as image:
                    fmt = image.format
                    width, height = image.size
                    image.verify()
                if fmt not in {"PNG", "JPEG", "GIF", "BMP", "TIFF"} or width * height > 40_000_000:
                    raise ValueError("unsupported image")
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
                raise PrototypeError("Изображение повреждено или имеет неподдерживаемый формат. Сохраните его в DOCX как PNG или JPEG.") from exc
            digest = hashlib.sha256(raw_image).hexdigest()
            asset = digest + "." + fmt.lower()
            assets[asset] = raw_image
            blocks.append({"kind": "image", "section": section, "caption": caption,
                           "asset": asset, "width": width, "height": height})
            counts["images"] += 1

    def process_element(element, part):
        nonlocal section
        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, doc)
            text = numbering.prefix(paragraph) + paragraph.text
            # Textboxes are outside Paragraph.text; keep their text as well.
            extra = element.xpath(".//w:txbxContent//w:p")
            if extra:
                text += "\n" + "\n".join(Paragraph(p, doc).text for p in extra)
            heading = bool(paragraph.style and (
                paragraph.style.name.lower().startswith(("heading", "заголовок"))))
            if text.strip():
                if heading:
                    section = text
                blocks.append({"kind": "heading" if heading else "paragraph", "text": text, "section": section})
                counts["paragraphs"] += 1
            # A caption in a separate paragraph is still preserved directly before/after the image.
            pictures(element, part=part)
        elif element.tag == qn("w:tbl"):
            table = Table(element, doc)
            rows = []
            for row in table.rows:
                rows.append([read_cell(cell) for cell in row.cells])
            if rows:
                counts["tables"] += 1
                blocks.append({"kind": "table", "rows": rows, "section": section})
                pictures(element, f"Изображение из таблицы {counts['tables']}", part=part)

    for element in doc.element.body:
        process_element(element, doc.part)
    seen_parts = set()
    for rel in doc.part.rels.values():
        if rel.is_external or rel.reltype.rsplit("/", 1)[-1] not in {"header", "footer"}:
            continue
        part = rel.target_part
        if part.partname in seen_parts:
            continue
        seen_parts.add(part.partname)
        root = part.element
        if not any(node.tag in {qn("w:t"), qn("a:blip")} for node in root.iter()):
            continue
        section = "Колонтитулы исходного документа"
        blocks.append({"kind": "heading", "section": section, "text": section})
        for element in root:
            process_element(element, part)

    if not blocks:
        raise PrototypeError("В документе нет текста, таблиц или изображений")
    if len(blocks) > 3000 or sum(len(json.dumps(b, ensure_ascii=False)) for b in blocks) > 1_000_000:
        raise PrototypeError("Документ слишком большой. Разделите его на части.")
    source_id = uuid.uuid4().hex
    document = {"id": source_id, "filename": filename, "sha256": hashlib.sha256(raw).hexdigest(),
                **counts, "warnings": warnings, "blocks": blocks}
    directory = _directory(source_id)
    directory.mkdir(parents=True, mode=0o700)
    try:
        (directory / "source.docx").write_bytes(raw)
        for name, blob in assets.items():
            (directory / name).write_bytes(blob)
        (directory / "manifest.json").write_text(json.dumps(document, ensure_ascii=False), "utf-8")
    except Exception:
        discard(source_id)
        raise
    return document


def context(source_ids):
    documents = [load(source_id) for source_id in dict.fromkeys(source_ids)]
    # JSON encodes document boundaries; its contents are untrusted evidence.
    payload = [{"filename": d["filename"], "blocks": [
        {k: v for k, v in b.items() if k not in {"asset", "width", "height"}}
        for b in d["blocks"]]} for d in documents]
    result = json.dumps(payload, ensure_ascii=False)
    if len(result) > MAX_CONTEXT_CHARS:
        raise PrototypeError("Для одного аудита слишком много текста. Разделите материалы на несколько аудитов; данные не были обрезаны.")
    return result if documents else ""
