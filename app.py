"""Portable Windows GUI for the batch OCR engine."""
from pathlib import Path
import json, os, queue, sys, threading, math
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import ocr
import key_store
from input_formats import SUPPORTED_SUFFIXES, list_inputs

DEFAULT_ADDRESS = 'https://free-oxr.somark.cn/api/v1'
APP_DIR = ocr.ROOT

def enable_high_dpi():
    if sys.platform != 'win32': return
    import ctypes
    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)): return
        # The manifest may already have set PerMonitorV2 awareness.
        if ctypes.get_last_error() == 5: return
    except (AttributeError, OSError): pass
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try: ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError): pass

def parse_limits(pages, size):
    try:
        count = int(pages)
        mib = float(size)
        if count < 1 or not math.isfinite(mib) or mib <= 0 or mib * 1048576 < 1:
            raise ValueError()
        return count, int(mib * 1048576)
    except (ValueError, OverflowError):
        raise ValueError('每批页数必须是正整数，大小必须是大于 0 的有效数值（MiB）。') from None

class App:
    def __init__(self,root):
        self.root=root;  self.running=False; self.cancel=threading.Event();self.events=queue.Queue();self.widgets=[]
        root.title('批量 OCR · 文档工作台')
        self.scale=root.winfo_fpixels('1i')/96
        sw=max(720,root.winfo_screenwidth()-round(50*self.scale));sh=max(540,root.winfo_screenheight()-round(75*self.scale))
        root.geometry(f'{min(round(980*self.scale),sw)}x{min(round(800*self.scale),sh)}');root.minsize(min(round(820*self.scale),sw),min(round(660*self.scale),sh))
        self.colors={'bg':'#f3f6fa','ink':'#162b3a','muted':'#64788b','accent':'#087f8c','border':'#dde6ee'}
        root.configure(bg=self.colors['bg'])
        from tkinter import font
        for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont'):font.nametofont(name).configure(family='Microsoft YaHei UI',size=10)
        style=ttk.Style(root);style.theme_use('clam')
        style.configure('.',font=('Microsoft YaHei UI',10),background=self.colors['bg'],foreground=self.colors['ink'])
        style.configure('TFrame',background=self.colors['bg']);style.configure('Card.TFrame',background='white')
        style.configure('Card.TLabel',background='white');style.configure('Muted.TLabel',foreground=self.colors['muted'])
        style.configure('MutedCard.TLabel',background='white',foreground=self.colors['muted'])
        style.configure('Title.TLabel',font=('Microsoft YaHei UI',23,'bold'))
        style.configure('Section.TLabel',background='white',font=('Microsoft YaHei UI',12,'bold'))
        style.configure('TEntry',fieldbackground='white',bordercolor=self.colors['border'],padding=(7,6))
        style.configure('TCombobox',fieldbackground='white',padding=(7,6))
        style.configure('TButton',background='white',bordercolor=self.colors['border'],padding=(14,8))
        style.map('TButton',background=[('active','#e4edf3'),('disabled','#edf1f5')])
        style.configure('Accent.TButton',background=self.colors['accent'],foreground='white',bordercolor=self.colors['accent'])
        style.map('Accent.TButton',background=[('active','#066975'),('disabled','#b3cbd0')],foreground=[('disabled','#f8fafc')])
        style.configure('TNotebook',background=self.colors['bg'],borderwidth=0)
        style.configure('TNotebook.Tab',padding=(20,10),background='#e8eef5',borderwidth=0)
        style.map('TNotebook.Tab',background=[('selected','white')],foreground=[('selected',self.colors['accent'])])
        style.configure('Horizontal.TProgressbar',background=self.colors['accent'],troughcolor='#e3ebf2',borderwidth=0)
        style.configure('Card.TCheckbutton',background='white',padding=4)
        settings={}
        try: settings=json.loads((APP_DIR/'设置.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        self.address=tk.StringVar(value=settings.get('address',DEFAULT_ADDRESS));self.key=tk.StringVar()
        self.key_path = APP_DIR / 'API凭据.dat'
        self.saved_key = None
        self.key_read_error = False
        try:
            self.saved_key = key_store.load_key(self.key_path)
        except (OSError, ValueError):
            self.key_read_error = True
        self.key_status = tk.StringVar()
        self.address.trace_add('write', self.update_key_status)
        self.update_key_status()
        self.source=tk.StringVar(value=settings.get('input',str(APP_DIR/'待处理')));self.dest=tk.StringVar(value=settings.get('output',str(APP_DIR/'识别结果')))
        self.selected_files = ()
        self.selection = tk.StringVar(value='按输入文件夹处理')
        self.max_pages=tk.StringVar(value=str(settings.get('max_pages',20)));self.max_mib=tk.StringVar(value=str(settings.get('max_mib',10)))
        self.keep=tk.BooleanVar(value=settings.get('keep_intermediate',True));self.status=tk.StringVar(value='准备就绪 · 选择文件和结果文件夹后开始')
        outer=ttk.Frame(root,padding=20);outer.pack(fill='both',expand=True)
        header=ttk.Frame(outer);header.pack(fill='x',pady=(0,16))
        badge=tk.Label(header,text=' OCR ',font=('Segoe UI',17,'bold'),background=self.colors['accent'],foreground='white',padx=8,pady=8);badge.pack(side='left',padx=(0,16))
        title=ttk.Frame(header);title.pack(side='left');ttk.Label(title,text='文档识别工作台',style='Title.TLabel').pack(anchor='w')
        ttk.Label(title,text='PDF、图片与 Office 文档 → Markdown',style='Muted.TLabel').pack(anchor='w',pady=(3,0))
        self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True)
        self.task_host=ttk.Frame(self.tabs)
        canvas=tk.Canvas(self.task_host,bg=self.colors['bg'],highlightthickness=0)
        scrollbar=ttk.Scrollbar(self.task_host,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set);scrollbar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        self.task_tab=ttk.Frame(canvas,padding=(0,14));inner=canvas.create_window((0,0),window=self.task_tab,anchor='nw')
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(inner,width=e.width))
        self.task_tab.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        def wheel(event):
            if self.tabs.select()==str(self.task_host) and canvas.bbox('all') and canvas.bbox('all')[3]>canvas.winfo_height():
                canvas.yview_scroll(-int(event.delta/120),'units')
        root.bind('<MouseWheel>',wheel,add='+')
        self.log_tab=ttk.Frame(self.tabs,padding=(0,14))
        self.tabs.add(self.task_host,text='识别任务');self.tabs.add(self.log_tab,text='运行记录')
        card=self.card(self.task_tab,'文件与输出','可直接多选 PDF、图片和 Office 文档。Office 转换需要 LibreOffice。')
        ttk.Label(card, text='识别来源', style='Card.TLabel').grid(row=0, column=0, sticky='w', padx=(0,12))
        summary = ttk.Entry(card, textvariable=self.selection, state='readonly')
        summary.grid(row=0, column=1, sticky='ew', pady=4)
        actions = ttk.Frame(card, style='Card.TFrame')
        actions.grid(row=0, column=2, padx=(8,0))
        select = ttk.Button(actions, text='选择文件…', command=self.choose_files)
        select.pack(side='left')
        folder = ttk.Button(actions, text='使用文件夹', command=self.use_input_folder)
        folder.pack(side='left', padx=(6,0))
        self.widgets.extend([select, folder])
        self.field(card,1,'输入文件夹',self.source,browse=True);self.field(card,2,'结果文件夹',self.dest,browse=True)
        card=self.card(self.task_tab,'识别服务','支持 SoMark / OXR 兼容 API。当前免费服务可留空。')
        self.field(card,1,'API 地址',self.address);self.field(card,2,'API Key',self.key,password=True)
        clear = ttk.Button(card, text='清空 Key', command=self.clear_key)
        clear.grid(row=2, column=2, sticky='w', padx=(8,0))
        self.widgets.append(clear)
        ttk.Label(card,textvariable=self.key_status,style='MutedCard.TLabel',wraplength=round(750*self.scale)).grid(row=3,column=0,columnspan=3,sticky='w',pady=(7,0))
        card=self.card(self.task_tab,'拆分与过程文件','页数和大小限制同时生效，设置不能突破服务商上限。')
        limits=ttk.Frame(card,style='Card.TFrame');limits.grid(row=0,column=0,columnspan=3,sticky='ew')
        for label,var in [('每批最多',self.max_pages),('页  /  最大',self.max_mib)]:
            ttk.Label(limits,text=label,style='Card.TLabel').pack(side='left',padx=(0,8));entry=ttk.Entry(limits,textvariable=var,width=8);entry.pack(side='left',padx=(0,12));self.widgets.append(entry)
        ttk.Label(limits,text='MiB',style='Card.TLabel').pack(side='left')
        check=ttk.Checkbutton(card,text='保留分批 PDF 和 JSON 过程文件',variable=self.keep,style='Card.TCheckbutton');check.grid(row=1,column=0,columnspan=3,sticky='w',pady=(12,0));self.widgets.append(check)
        ttk.Label(card,text='关闭后，整份文档成功合并再清理；失败或中断时保留缓存用于续跑。',style='MutedCard.TLabel').grid(row=2,column=0,columnspan=3,sticky='w',pady=(2,0))
        self.log=ScrolledText(self.log_tab,font=('Microsoft YaHei UI',10),state='disabled',bg='#102b3b',fg='#d7e8f3',insertbackground='white',relief='flat',padx=14,pady=12)
        self.log.pack(fill='both',expand=True)
        footer=ttk.Frame(outer);footer.pack(fill='x',pady=(12,0))
        self.start_button=ttk.Button(footer,text='开始识别  →',style='Accent.TButton',command=self.start);self.start_button.pack(side='left')
        self.stop_button=ttk.Button(footer,text='停止',command=self.stop,state='disabled');self.stop_button.pack(side='left',padx=8)
        ttk.Button(footer,text='打开结果文件夹',command=self.open_output).pack(side='right')
        ttk.Label(outer,textvariable=self.status,style='Muted.TLabel',wraplength=round(900*self.scale)).pack(anchor='w',pady=(10,4))
        self.progress=ttk.Progressbar(outer,mode='indeterminate');self.progress.pack(fill='x')
        self.root.after(100,self.poll);root.protocol('WM_DELETE_WINDOW',self.close)

    def card(self,parent,title,subtitle):
        shell=tk.Frame(parent,bg='white',highlightbackground=self.colors['border'],highlightthickness=1);shell.pack(fill='x',pady=(0,10))
        content=ttk.Frame(shell,style='Card.TFrame',padding=(16,12));content.pack(fill='x')
        ttk.Label(content,text=title,style='Section.TLabel').pack(anchor='w')
        ttk.Label(content,text=subtitle,style='MutedCard.TLabel').pack(anchor='w',pady=(3,8))
        fields=ttk.Frame(content,style='Card.TFrame');fields.pack(fill='x');fields.columnconfigure(1,weight=1)
        return fields

    def field(self,parent,row,label,var,browse=False,password=False):
        ttk.Label(parent,text=label,style='Card.TLabel').grid(row=row,column=0,sticky='w',padx=(0,12),pady=4)
        entry=ttk.Entry(parent,textvariable=var,show='●' if password else '');entry.grid(row=row,column=1,sticky='ew',pady=4);self.widgets.append(entry)
        if browse:
            button=ttk.Button(parent,text='浏览…',command=lambda:self.browse(var));button.grid(row=row,column=2,padx=(8,0));self.widgets.append(button)

    def browse(self,var):
        directory=filedialog.askdirectory(parent=self.root, initialdir=var.get() if Path(var.get()).is_dir() else str(APP_DIR))
        if directory:
            var.set(directory)
            if var is self.source:
                self.use_input_folder()

    def choose_files(self):
        patterns = tuple('*' + suffix for suffix in sorted(SUPPORTED_SUFFIXES))
        initial = self.selected_files[0].parent if self.selected_files else Path(self.source.get()).expanduser()
        selected = filedialog.askopenfilenames(
            parent=self.root, title='选择要识别的文件',
            initialdir=str(initial if initial.is_dir() else APP_DIR),
            filetypes=[('可识别的文件', patterns), ('所有文件', '*.*')],
        )
        if not selected:
            return
        files = tuple(dict.fromkeys(Path(name).resolve() for name in selected))
        unsupported = [path.name for path in files if path.suffix.lower() not in SUPPORTED_SUFFIXES]
        if unsupported:
            messagebox.showerror('格式不受支持', '请重新选择。' + '\n' + '\n'.join(unsupported), parent=self.root)
            return
        self.selected_files = files
        names = '、'.join(path.name for path in files[:2])
        self.selection.set(f'已选 {len(files)} 个文件 · {names}' + ('…' if len(files) > 2 else ''))

    def use_input_folder(self):
        self.selected_files = ()
        self.selection.set('按输入文件夹处理')

    def task_files(self):
        if self.selected_files:
            missing = next((path for path in self.selected_files if not path.is_file()), None)
            if missing:
                raise ValueError(f'选中的文件已找不到，请重新选择：{missing.name}')
            return self.selected_files
        if not self.source.get().strip():
            raise ValueError('请选择文件或输入文件夹。')
        source = Path(self.source.get()).expanduser().resolve()
        source.mkdir(parents=True, exist_ok=True)
        return list_inputs(source)

    def open_output(self):
        try:
            folder=Path(self.dest.get()).expanduser();folder.mkdir(parents=True,exist_ok=True);os.startfile(folder)
        except Exception as e:messagebox.showerror('打开失败',str(e))

    def update_key_status(self, *_):
        if self.key_read_error:
            status = '凭据无法读取。请重新填写 Key，或点击清空 Key。'
        elif self.saved_key is None:
            status = '未保存 Key。填写后，开始识别或关闭软件时会加密保存。'
        else:
            try:
                matches = ocr.endpoint(self.address.get()) == self.saved_key[0]
            except ValueError:
                matches = False
            status = ('已保存 Key，识别时自动使用。' if matches else
                      '已保存其他 API 地址的 Key。当前地址可填写新的 Key。')
        self.key_status.set(status)

    def save_pending_key(self, endpoint):
        entered = self.key.get().strip()
        if entered:
            key_store.save_key(self.key_path, endpoint, entered)
            self.saved_key = (endpoint, entered)
            self.key_read_error = False
            self.key.set('')
            self.update_key_status()

    def clear_key(self):
        try:
            self.key_path.unlink(missing_ok=True)
        except OSError:
            messagebox.showerror('清空失败', '无法删除保存的 Key，请检查程序目录的写入权限。', parent=self.root)
            return
        self.saved_key = None
        self.key_read_error = False
        self.key.set('')
        self.update_key_status()

    def save_settings(self):
        settings={'address':self.address.get().strip(),'input':self.source.get(),'output':self.dest.get(),'max_pages':self.max_pages.get(),'max_mib':self.max_mib.get(),'keep_intermediate':self.keep.get()}
        (APP_DIR/'设置.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')

    def start(self):
        if self.running:return
        try:
            endpoint=ocr.endpoint(self.address.get())
            max_pages,max_bytes=parse_limits(self.max_pages.get(),self.max_mib.get())
            if not self.dest.get().strip():raise ValueError('请选择结果文件夹。')
            files = self.task_files()
            if not files:raise ValueError('请选择文件，或在输入文件夹中放入受支持的文件。')
            dest=Path(self.dest.get()).expanduser().resolve();dest.mkdir(parents=True,exist_ok=True)
            probe=dest/('.write-test-'+str(os.getpid()));probe.write_text('');probe.unlink()
            self.save_pending_key(endpoint)
            if self.key_read_error:
                raise ValueError('请重新填写 Key，或清空无法读取的已保存凭据。')
            api_key = self.saved_key[1] if self.saved_key and self.saved_key[0] == endpoint else ''
        except Exception as e:messagebox.showerror('无法开始',str(e));return
        try:self.save_settings()
        except OSError:self.events.put(('log','无法保存设置，下次启动将恢复默认值。'))
        self.running=True;self.cancel.clear();ocr.URL=endpoint;ocr.API_KEY=api_key;ocr.OUTPUT=dest;ocr.KEEP_INTERMEDIATE=self.keep.get();ocr.CANCEL_EVENT=self.cancel
        ocr.MAX_PAGES=max_pages;ocr.MAX_BYTES=max_bytes;ocr.LOG=lambda message:self.events.put(('log',message))
        self.start_button.config(state='disabled');self.stop_button.config(state='normal')
        for widget in self.widgets:widget.config(state='disabled')
        self.progress.start();self.status.set(f'正在处理 {len(files)} 个文件 · SoMark / OXR')
        self.events.put(('log',f'开始任务：{len(files)} 个文件，每批最多 {max_pages} 页 / {max_bytes/1048576:g} MiB。'))
        threading.Thread(target=self.worker,args=(files,),daemon=True).start()

    def worker(self,files):
        failed=[]
        try:
            for i,path in enumerate(files,1):
                ocr.check_cancelled();self.events.put(('log',f'[{i}/{len(files)}] {path.name}'))
                try:ocr.process(path)
                except ocr.Cancelled:raise
                except Exception as e:failed.append(path.name);self.events.put(('log',f'失败：{path.name}：{e}'))
            self.events.put(('done',f'处理完成 · 成功 {len(files)-len(failed)} / {len(files)}'+('，失败文件可重新运行。' if failed else '')))
        except ocr.Cancelled as e:self.events.put(('done',str(e)))
        except Exception as e:self.events.put(('done','处理停止：'+str(e)))
        finally:ocr.API_KEY=''

    def stop(self):
        self.cancel.set();self.stop_button.config(state='disabled');self.status.set('等待当前网络请求返回后停止；已保存批次可继续。')

    def poll(self):
        try:
            while True:
                kind,message=self.events.get_nowait();self.log.config(state='normal');self.log.insert('end',message+'\n');self.log.see('end');self.log.config(state='disabled')
                if kind=='done':
                    self.running=False;self.progress.stop();self.status.set(message);self.start_button.config(state='normal');self.stop_button.config(state='disabled')
                    for widget in self.widgets:widget.config(state='readonly' if isinstance(widget,ttk.Combobox) else 'normal')
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def close(self):
        if self.running:self.stop();messagebox.showinfo('正在停止','请等待当前请求结束后再关闭窗口。');return
        if self.key.get().strip():
            try:
                self.save_pending_key(ocr.endpoint(self.address.get()))
            except (OSError, ValueError) as error:
                messagebox.showerror('Key 保存失败', str(error), parent=self.root)
                return
        try:self.save_settings()
        except OSError:pass
        self.root.destroy()

def self_test(report):
    global APP_DIR
    import io, tempfile
    from unittest.mock import patch
    from pypdf import PdfReader, PdfWriter
    calls=[]
    class Response:
        def __init__(self,data): self.data=data
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return json.dumps(self.data).encode()
    def fake_open(request,timeout):
        body=request.data; assert b'name="api_key"\r\n\r\ntest-key' in body
        assert request.full_url=='https://example.test/api/v1/parse/sync'
        pos=body.index(b'%PDF-'); end=body.rindex(b'\r\n------oxr')
        n=len(PdfReader(io.BytesIO(body[pos:end])).pages); calls.append(n)
        return Response({'code':0,'data':{'error':None,'result':{'outputs':{'markdown':f'content-{n}','json':{'pages':[{'page_num':i} for i in range(n)]}}}}})
    with tempfile.TemporaryDirectory(dir=Path(report).resolve().parent) as t:
        folder=Path(t); APP_DIR=folder; ocr.OUTPUT=folder/'out'; ocr.OUTPUT.mkdir(); ocr.URL=ocr.endpoint('https://example.test/api/v1/'); ocr.API_KEY='test-key'
        for name,count in [('a',23),('b',7)]:
            writer=PdfWriter()
            for _ in range(count): writer.add_blank_page(width=100,height=100)
            path=folder/(name+'.pdf'); writer.write(path)
            with patch('urllib.request.urlopen',side_effect=fake_open): ocr.process(path); ocr.process(path)
            assert (ocr.OUTPUT/name/(name+'.md')).exists()
        assert calls==[20,3,7],calls
        assert 'content-20' in (ocr.OUTPUT/'a/a.md').read_text(encoding='utf-8')
        for value in [('0','10'),('1','nan'),('2.5','10'),('20','0')]:
            try: parse_limits(*value)
            except ValueError: pass
            else: raise AssertionError(value)
        assert parse_limits('50','1.5') == (50,1572864)
        path=folder/'c.pdf'; writer=PdfWriter()
        for _ in range(23): writer.add_blank_page(width=100,height=100)
        writer.write(path); ocr.MAX_PAGES=50
        with patch('urllib.request.urlopen',side_effect=fake_open): ocr.process(path)
        assert calls[-1]==23
        reader=PdfReader(path); ocr.MAX_BYTES=len(ocr.make_pdf(reader,0,2))
        before=len(calls)
        with patch('urllib.request.urlopen',side_effect=fake_open): ocr.process(path)
        assert sum(calls[before:])==23 and max(calls[before:])<=2
        # Custom limits persist without persisting credentials.
        (folder/'设置.json').write_text(json.dumps({'max_pages':55,'max_mib':1.5}),encoding='utf-8')
        window=tk.Tk(); window.withdraw(); app=App(window); window.update()
        assert app.address.get()==DEFAULT_ADDRESS and app.key.get()==''
        assert parse_limits(app.max_pages.get(),app.max_mib.get())==(55,1572864)
        dpi=window.winfo_fpixels('1i')
        app.address.set('https://example.test/api/v1')
        app.key.set('test-key')
        source = folder / 'another-folder'
        source.mkdir()
        second = source / 'b.pdf'
        (folder / 'b.pdf').rename(second)
        destination = folder / 'chosen-output'
        unused = folder / 'unused-input-folder'
        app.source.set(str(unused))
        with patch.object(filedialog, 'askopenfilenames', return_value=(str(folder / 'a.pdf'), str(second))):
            app.choose_files()
        with patch.object(filedialog, 'askdirectory', return_value=str(destination)):
            app.browse(app.dest)
        with patch('threading.Thread') as thread, patch('urllib.request.urlopen', side_effect=fake_open), \
             patch.object(messagebox, 'showerror', side_effect=AssertionError('Could not start selected files')):
            app.start()
            worker = thread.call_args.kwargs
            worker['target'](*worker['args'])
        assert not unused.exists()
        assert (destination / 'a/a.md').exists() and (destination / 'b/b.md').exists()
        assert calls[-2:] == [23,7]
        assert app.key.get() == '' and b'test-key' not in app.key_path.read_bytes()
        assert 'test-key' not in (folder / '设置.json').read_text(encoding='utf-8')
        app.use_input_folder()
        app.source.set(str(source))
        assert app.task_files() == [second]
        ocr.LOG = None
        ocr.CANCEL_EVENT = None
        window.destroy()

        window = tk.Tk()
        window.withdraw()
        reopened = App(window)
        assert reopened.key.get() == ''
        assert reopened.saved_key == ('https://example.test/api/v1/parse/sync', 'test-key')
        assert reopened.key_status.get().startswith('已保存 Key')
        reopened.address.set('https://another.test/api/v1')
        assert reopened.key_status.get().startswith('已保存其他 API 地址')
        reopened.address.set('https://example.test/api/v1')
        reopened.source.set(str(source))
        reopened.dest.set(str(folder / 'reopened-output'))
        with patch('threading.Thread') as thread, patch('urllib.request.urlopen', side_effect=fake_open), \
             patch.object(messagebox, 'showerror', side_effect=AssertionError('Could not use saved Key')):
            reopened.start()
            worker = thread.call_args.kwargs
            worker['target'](*worker['args'])
        assert (folder / 'reopened-output/b/b.md').exists()
        reopened.running = False
        reopened.clear_key()
        assert key_store.load_key(reopened.key_path) is None
        reopened.key.set('replacement-key')
        reopened.close()
        assert key_store.load_key(reopened.key_path) == ('https://example.test/api/v1/parse/sync', 'replacement-key')
        ocr.LOG = None
        ocr.CANCEL_EVENT = None
    awareness=None
    if sys.platform=='win32':
        import ctypes
        user32=ctypes.WinDLL('user32'); user32.GetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        user32.GetAwarenessFromDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        awareness=user32.GetAwarenessFromDpiAwarenessContext(user32.GetThreadDpiAwarenessContext())
        assert awareness==2,awareness
    from verification import run
    extra=run(Path(report).resolve().parent)
    Path(report).write_text(json.dumps({'extended_checks':extra,'ok':True,'batch_sizes':calls,'dpi':dpi,'dpi_awareness':awareness,'checks':['custom API','optional key','multi PDF','split','merge','resume','custom limits','size splitting','invalid limits','saved limits','DPI-aware Tk window','direct selection across folders','chosen output folder','folder input fallback','encrypted Key storage and reuse','clear and replace Key']}),encoding='utf-8')

if __name__=='__main__':
    enable_high_dpi()
    if len(sys.argv)==3 and sys.argv[1]=='--self-test': self_test(sys.argv[2])
    else:
        root=tk.Tk(); App(root); root.mainloop()
