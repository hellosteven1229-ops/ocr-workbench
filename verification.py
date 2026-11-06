"""Offline integration checks used by source and bundled exe."""
import base64, io, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
import input_formats
import ocr
from pypdf import PdfReader,PdfWriter

def run(parent):
    results=[]
    saved={k:getattr(ocr,k) for k in ('OUTPUT','URL','MAX_PAGES','MAX_BYTES','KEEP_INTERMEDIATE','API_KEY','CANCEL_EVENT')}
    try:
        with tempfile.TemporaryDirectory(dir=parent) as t:
            root=Path(t);ocr.OUTPUT=root/'out';ocr.OUTPUT.mkdir();ocr.URL='https://test.invalid/parse';ocr.MAX_PAGES=2;ocr.MAX_BYTES=10*1048576;ocr.API_KEY='';ocr.CANCEL_EVENT=None
            writer=PdfWriter()
            for _ in range(5):writer.add_blank_page(width=100,height=100)
            path=root/'file.pdf';writer.write(path);calls=[]
            def post(pdf):
                n=len(PdfReader(io.BytesIO(pdf)).pages);calls.append(n)
                return {'code':0,'data':{'result':{'outputs':{'markdown':f'{n} pages','json':{'pages':[{'page_num':i} for i in range(n)]}}}}}
            ocr.KEEP_INTERMEDIATE=True
            with patch.object(ocr,'post_pdf',side_effect=post):ocr.process(path)
            assert calls==[2,2,1]
            batchdir=ocr.OUTPUT/'file/分批结果';assert len(list(batchdir.rglob('*.pdf')))==3 and len(list(batchdir.rglob('*.json')))==3
            ocr.KEEP_INTERMEDIATE=False
            with patch.object(ocr,'post_pdf',side_effect=AssertionError('reuploaded')):ocr.process(path)
            assert not batchdir.exists() and (ocr.OUTPUT/'file/file.md').exists()
            results.append('retain split PDF/JSON, clean after success, skip completed files')
            path2=root/'interrupted.pdf';writer.write(path2);counter=[0]
            def fail_second(pdf):
                counter[0]+=1
                if counter[0]==2:raise RuntimeError('simulated interruption')
                return post(pdf)
            try:
                with patch.object(ocr,'post_pdf',side_effect=fail_second):ocr.process(path2)
            except RuntimeError:pass
            else:raise AssertionError('Failure not propagated')
            partial=ocr.OUTPUT/'interrupted/分批结果';assert len(list(partial.rglob('*.json')))==1
            calls.clear()
            with patch.object(ocr,'post_pdf',side_effect=post):ocr.process(path2)
            assert calls==[2,1] and not partial.exists()
            results.append('retain cache on interruption, resume and clean')
            png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZxkAAAAASUVORK5CYII=')
            text,failed=ocr.save_images('![one](data:image/png;base64,'+base64.b64encode(png).decode()+')',root/'images')
            assert not failed and '图片/' in text and len(list((root/'images').glob('*.png')))==1
            results.append('local inline-image preservation')
            results.extend(check_mixed_inputs(root, post, calls))
    finally:
        for k,v in saved.items():setattr(ocr,k,v)
    return results


def check_mixed_inputs(root, post, calls):
    source = root / 'mixed'
    source.mkdir()
    first = Image.new('RGB', (60, 90), 'white')
    other = Image.new('RGB', (90, 60), 'black')
    for suffix in ('PNG', 'jpg', 'jpeg', 'bmp', 'webp', 'gif', 'tif'):
        first.save(source / f'scan-{suffix.lower()}.{suffix}')
    first.save(source / 'scan-pages.tiff', save_all=True, append_images=[other, first])
    doc = source / 'slides.pptx'
    doc.write_bytes(b'fixture for mocked converter')
    (source / '~$slides.pptx').touch()
    (source / 'ignored.txt').touch()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(source / 'original.pdf')
    files = input_formats.list_inputs(source)
    assert len(files) == 10 and doc in files

    def convert(command, **kwargs):
        assert '--headless' in command and command[-1] == str(doc.resolve())
        writer.write(Path(command[command.index('--outdir') + 1]) / 'slides.pdf')
        return SimpleNamespace(returncode=0, stderr=b'')

    calls.clear()
    with patch.object(input_formats, 'libreoffice_path', return_value='soffice.com'), \
         patch.object(input_formats.subprocess, 'run', side_effect=convert), \
         patch.object(ocr, 'post_pdf', side_effect=post):
        for path in files:
            ocr.process(path)
    assert calls.count(2) == 1 and sum(calls) == 12
    assert (ocr.OUTPUT / 'scan-pages' / 'scan-pages.md').exists()
    assert (ocr.OUTPUT / 'slides' / 'slides.md').exists()
    return ['mixed PDF and eight image inputs, multipage TIFF, mocked Office conversion']
