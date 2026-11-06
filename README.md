# 批量 OCR 工作台

Windows 桌面工具。选择文件或输入文件夹后，程序会分批调用 SoMark/OXR 兼容接口，将每份文件整理为 Markdown，并保存识别结果中的图片。

本工具是独立开发的第三方客户端，**仅供个人使用**，开发目的是简化个人调用 OCR API 的操作。默认使用 SoMark 团队提供的 OXR 免费接口。[版权与使用声明](COPYRIGHT.md)

## 功能

- 支持从原位置选择多个文件，也支持批量处理文件夹。
- 自动按页数和文件大小拆分，按原页序合并识别结果。
- 支持指定输出位置、断点续跑和过程文件保留开关。
- 支持自定义 SoMark/OXR 兼容地址和可选 API Key。Key 使用 Windows 凭据保护加密保存。

| 输入 | 处理方式 |
| --- | --- |
| PDF | 分批上传识别。 |
| PNG、JPG、JPEG、WebP、BMP、TIF、TIFF、GIF | 在本机转成 PDF。多页 TIFF 按页处理，动画 GIF 和 WebP 取首帧。 |
| DOC、DOCX、PPT、PPTX、XLS、XLSX、ODT、ODP、ODS | 由本机的 LibreOffice 导出为 PDF。Excel 按导出的打印分页识别。 |

## 使用

1. 打开程序，点击 **选择文件…**，或选择 **使用文件夹**。
2. 指定 **结果文件夹**。每个源文件的 Markdown 和图片会保存到对应子文件夹。
3. 按需设置 API 地址和每批限制。默认地址为 `https://free-oxr.somark.cn/api/v1`，默认每批 20 页、10 MiB。选择服务时以对应服务的限制为准。
4. 点击 **开始识别**，在 **运行记录** 查看进度。

Key 可留空。填写 Key 后，开始识别或正常退出时会加密保存。下次打开时输入框保持空白，软件会对同一 API 地址自动使用已保存的 Key。点击 **清空 Key** 可删除凭据。

勾选 **保留分批 PDF 和 JSON 过程文件** 会保留上传批次和识别响应。取消勾选时，软件在整份文档成功整理后清理本次的分批文件。任务中断时，已完成批次会暂存以供续跑。

## 从源码运行与构建

使用 Windows 10/11 和 64 位 Python 3.13。在 PowerShell 中执行以下命令。

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe app.py
```

构建单文件便携程序。

```powershell
.\build.cmd
```

构建产物位于 `dist/OCR-Workbench.exe`。便携程序可直接在 Windows 10/11 64 位运行。处理 Office 文档的电脑需安装 LibreOffice。

## 安全与发布

识别会将选中的文档批次发送至配置的 OCR 服务。凭据保护、数据流向、文件分享和漏洞报告方式见 [安全与隐私说明](SECURITY.md)。GitHub Release 正文见 [v6 发布说明](RELEASE_NOTES.md)。
