from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from pypdf import PdfReader, PdfWriter


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.gif'}
OFFICE_SUFFIXES = {'.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx', '.odt', '.odp', '.ods'}
SUPPORTED_SUFFIXES = {'.pdf'} | IMAGE_SUFFIXES | OFFICE_SUFFIXES


def list_inputs(directory):
    return sorted(path for path in directory.iterdir()
                  if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
                  and not path.name.startswith('~$'))


def image_pdf(path, check_cancelled):
    from PIL import Image, ImageOps

    writer = PdfWriter()
    with Image.open(path) as image:
        # TIFF frames are document pages. For animated formats use the cover frame.
        page_count = image.n_frames if image.format == 'TIFF' else 1
        for index in range(page_count):
            check_cancelled()
            image.seek(index)
            frame = ImageOps.exif_transpose(image)
            rgba = frame.convert('RGBA')
            page = Image.new('RGB', rgba.size, 'white')
            page.paste(rgba, mask=rgba.getchannel('A'))
            encoded = BytesIO()
            page.save(encoded, 'PDF', resolution=max(144, max(page.size) / 14), quality=95)
            encoded.seek(0)
            writer.add_page(PdfReader(encoded).pages[0])
    converted = BytesIO()
    writer.write(converted)
    converted.seek(0)
    return PdfReader(converted)


def libreoffice_path():
    for variable in ('ProgramW6432', 'ProgramFiles', 'ProgramFiles(x86)'):
        directory = os.environ.get(variable)
        if directory:
            program = Path(directory) / 'LibreOffice' / 'program' / 'soffice.com'
            if program.is_file():
                return str(program)
            if program.with_suffix('.exe').is_file():
                return str(program.with_suffix('.exe'))
    return shutil.which('soffice.com') or shutil.which('soffice') or shutil.which('libreoffice')


def office_pdf(path, workspace):
    program = libreoffice_path()
    if not program:
        raise RuntimeError('Office 文档需要 LibreOffice。请安装后重试，或先导出为 PDF。')
    with TemporaryDirectory(prefix='office-', dir=workspace) as temp:
        work = Path(temp).resolve()
        profile = work / 'profile'
        user_profile = profile / 'user'
        user_profile.mkdir(parents=True)
        (user_profile / 'registrymodifications.xcu').write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item></oor:items>', encoding='utf-8')
        command = [program, '-env:UserInstallation=' + profile.as_uri(),
                   '--headless', '--norestore', '--convert-to', 'pdf',
                   '--outdir', str(work), str(path.resolve())]
        try:
            result = subprocess.run(command, capture_output=True, timeout=180,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('LibreOffice 转换超时，请先手动导出为 PDF。') from error
        output = work / (path.stem + '.pdf')
        if result.returncode != 0 or not output.is_file():
            details = result.stderr.decode(errors='replace').strip()[:300]
            raise RuntimeError(f'LibreOffice 未能导出 PDF。{details}')
        return PdfReader(BytesIO(output.read_bytes()))


def open_pdf(path, workspace, check_cancelled):
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        return PdfReader(path)
    if suffix in IMAGE_SUFFIXES:
        return image_pdf(path, check_cancelled)
    if suffix in OFFICE_SUFFIXES:
        return office_pdf(path, workspace)
    raise ValueError(f'文件格式不受支持：{suffix}')
