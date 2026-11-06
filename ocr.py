from pathlib import Path
import hashlib, io, json, re, sys, time, urllib.request, urllib.error, urllib.parse, uuid, base64
import input_formats
try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    print('缺少 pypdf，请安装：python -m pip install pypdf', flush=True)
    sys.exit(1)

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
INPUT = ROOT / '待处理'
OUTPUT = ROOT / '识别结果'
URL = 'https://free-oxr.somark.cn/api/v1/parse/sync'
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
API_KEY = ''
LOG = None
CANCEL_EVENT = None
KEEP_INTERMEDIATE = True

class Cancelled(Exception):
    pass

def log(message):
    if LOG is not None: LOG(message)
    elif sys.stdout is not None: print(message, flush=True)

def check_cancelled():
    if CANCEL_EVENT is not None and CANCEL_EVENT.is_set(): raise Cancelled('已停止；下次运行将继续已完成的批次')

def wait(seconds):
    if CANCEL_EVENT is None: time.sleep(seconds)
    elif CANCEL_EVENT.wait(seconds): check_cancelled()

def endpoint(address):
    address = address.strip().rstrip('/')
    parsed = urllib.parse.urlsplit(address)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('请输入有效的 HTTP/HTTPS API 地址，不含查询参数或用户名')
    return address if parsed.path.endswith('/parse/sync') else address + '/parse/sync'

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def make_pdf(reader, start, count):
    writer = PdfWriter()
    for page in reader.pages[start:start+count]: writer.add_page(page)
    data = io.BytesIO(); writer.write(data)
    return data.getvalue()

def post_pdf(pdf):
    boundary = '----oxr' + uuid.uuid4().hex
    chunks = []
    for name, value in [('api_key', API_KEY.strip() or 'dummy'), ('output_formats','markdown'), ('output_formats','json')]:
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="part.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode() + pdf + b'\r\n')
    chunks.append(f'--{boundary}--\r\n'.encode())
    return request_json(URL,b''.join(chunks),{'Content-Type':'multipart/form-data; boundary='+boundary})

def request_json(url,body,headers,method='POST'):
    request = urllib.request.Request(url, data=body, headers=headers,method=method)
    busy = failures = 0
    while True:
        check_cancelled()
        try:
            with urllib.request.urlopen(request, timeout=1800) as response: return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code != 429: raise RuntimeError(f'HTTP {e.code}：服务拒绝请求，请检查地址、Key 或服务状态') from e
            busy += 1
            if busy > 30: raise RuntimeError('服务持续繁忙，等待 30 次后停止') from e
            log(f'服务繁忙，60 秒后重试（{busy}/30）'); wait(60)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            failures += 1
            if failures >= 4: raise
            log(f'连接失败，稍后重试（{failures}/4）：{e}'); wait(failures*10)

def validate(data, count):
    if data.get('code') != 0: raise RuntimeError(f'接口报错：{data.get("message")}')
    d = data.get('data') or {}
    if d.get('error'): raise RuntimeError(f'识别失败：{d["error"]}')
    outputs = (d.get('result') or {}).get('outputs') or {}
    pages = outputs.get('json', {}).get('pages', [])
    if not isinstance(outputs.get('markdown'), str) or len(pages) != count or [p.get('page_num') for p in pages] != list(range(count)):
        raise RuntimeError('服务返回的页数不完整，未保存结果')
    return outputs['markdown']

def save_images(markdown, assets):
    assets.mkdir(exist_ok=True)
    failed = []
    def replace(match):
        check_cancelled()
        url = match.group(2)
        prefix=hashlib.sha256(url.encode()).hexdigest()[:24]
        existing=next((p for p in assets.glob(prefix+'.*') if p.suffix in ('.png','.jpg','.gif','.webp')),None)
        if existing:target=existing
        else:
            for attempt in range(3):
                try:
                    if url.startswith('data:'):data=base64.b64decode(url.split(',',1)[1],validate=True)
                    else:
                        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'}), timeout=60) as response: data = response.read()
                    if data.startswith(b'\x89PNG\r\n\x1a\n'):ext='.png'
                    elif data.startswith(b'\xff\xd8\xff'):ext='.jpg'
                    elif data.startswith((b'GIF87a',b'GIF89a')):ext='.gif'
                    elif data[:4]==b'RIFF' and data[8:12]==b'WEBP':ext='.webp'
                    else:raise ValueError('图片格式不是 PNG/JPEG/GIF/WebP')
                    target=assets/(prefix+ext)
                    target.write_bytes(data); break
                except Exception as e:
                    if attempt == 2: failed.append(f'{url}: {e}'); return match.group(0)
                    wait(2*(attempt+1))
        return f'![{match.group(1)}](<图片/{target.name}>)'
    return re.sub(r'!\[([^\]]*)\]\(<?(https?://[^)\s>]+|data:image/[^;]+;base64,[A-Za-z0-9+/=]+)>?\)', replace, markdown), failed

def process(path):
    check_cancelled()
    suffix = path.suffix.lower()
    if suffix not in input_formats.SUPPORTED_SUFFIXES:
        raise ValueError(f'文件格式不受支持：{suffix}')
    digest = sha256(path)
    name = path.stem.rstrip(' .') or 'document'
    directory = OUTPUT / name
    if directory.exists() and (directory/'来源.json').exists():
        info = json.loads((directory/'来源.json').read_text(encoding='utf-8'))
        if info.get('sha256') != digest: directory = OUTPUT / (name + '_' + digest[:10])
    directory.mkdir(parents=True, exist_ok=True)
    info = directory/'来源.json'
    if info.exists() and json.loads(info.read_text(encoding='utf-8')).get('sha256') != digest:
        raise RuntimeError('结果目录与来源文件不匹配')
    signature={'url':URL,'max_pages':MAX_PAGES,'max_bytes':MAX_BYTES}
    if suffix != '.pdf':
        signature['input_format'] = suffix
    fingerprint=hashlib.sha256(json.dumps(signature,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
    complete=directory/'完成.json'
    dest=directory/(name+'.md')
    parts_dir=directory/'分批结果'/fingerprint
    def clean_parts():
        if not parts_dir.is_dir():return
        for f in parts_dir.iterdir():
            if f.is_file() and re.fullmatch(r'\d+-\d+\.(json|pdf)',f.name):f.unlink()
        try: parts_dir.rmdir();parts_dir.parent.rmdir()
        except OSError:pass
    if complete.exists() and dest.exists():
        done=json.loads(complete.read_text(encoding='utf-8'))
        if done.get('sha256')==digest and done.get('profile')==fingerprint and done.get('markdown_sha256')==sha256(dest):
            if not KEEP_INTERMEDIATE:clean_parts()
            log(f'跳过已完成文件：{path.name}')
            return
    if suffix != '.pdf':
        log(f'正在准备 PDF：{path.name}')
    reader = input_formats.open_pdf(path, directory, check_cancelled)
    if reader.is_encrypted: raise RuntimeError('PDF 已加密，请先解除密码保护')
    total = len(reader.pages)
    if not total: raise RuntimeError('文件没有可识别的页面')
    info.write_text(json.dumps({'file':path.name,'sha256':digest,'pages':total}, ensure_ascii=False,indent=2), encoding='utf-8')
    parts_dir.mkdir(parents=True,exist_ok=True)
    sections = [f'# {name}']; start=0; errors=[]
    while start < total:
        check_cancelled()
        count=min(MAX_PAGES,total-start); pdf=make_pdf(reader,start,count)
        while len(pdf)>MAX_BYTES and count>1:
            count=max(1,count//2); pdf=make_pdf(reader,start,count)
        if len(pdf)>MAX_BYTES: raise RuntimeError(f'第 {start+1} 页单独拆出后仍超过 {MAX_BYTES/1048576:g} MiB，无法上传')
        stem=f'{start+1:04d}-{start+count:04d}'; result=parts_dir/(stem+'.json')
        if KEEP_INTERMEDIATE:(parts_dir/(stem+'.pdf')).write_bytes(pdf)
        log(f'{path.name}: {start+1}-{start+count}/{total}')
        if result.exists():
            data=json.loads(result.read_text(encoding='utf-8')); markdown=validate(data,count)
        else:
            data=post_pdf(pdf); markdown=validate(data,count)
            temp=result.with_suffix('.tmp'); temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(result)
        markdown, failed=save_images(markdown,directory/'图片'); errors.extend(failed)
        page_source = '原 PDF' if suffix == '.pdf' else '转换后 PDF'
        sections.extend([f'<!-- {page_source} 第 {start+1}–{start+count} 页 -->',markdown.strip()]); start+=count
    temp=dest.with_suffix('.tmp'); temp.write_text('\n\n'.join(sections)+'\n',encoding='utf-8'); temp.replace(dest)
    image_log=directory/'图片下载失败.txt'
    if errors: image_log.write_text('\n'.join(errors)+'\n',encoding='utf-8')
    else: image_log.unlink(missing_ok=True)
    if not errors:
        complete.write_text(json.dumps({'sha256':digest,'profile':fingerprint,'pages':total,'markdown_sha256':sha256(dest)},indent=2),encoding='utf-8')
        if not KEEP_INTERMEDIATE:clean_parts()
    else:log('图片下载未全部成功，保留临时批次以便下次重试。')
    log(f'完成：{dest}；图片下载失败 {len(errors)} 张')

def main():
    INPUT.mkdir(exist_ok=True); OUTPUT.mkdir(exist_ok=True)
    files=input_formats.list_inputs(INPUT)
    if not files: print(f'请先将 PDF、图片或 Office 文档放入：{INPUT}',flush=True); return 1
    failed=[]
    for path in files:
        try: process(path)
        except Exception as e: failed.append((path.name,str(e))); print(f'处理失败：{path.name}：{e}',flush=True)
    if failed:
        print(f'完成，但 {len(failed)} 个文件失败；重新运行会继续已保存的批次。',flush=True); return 1
    print('全部处理完成。',flush=True); return 0
if __name__ == '__main__': sys.exit(main())
