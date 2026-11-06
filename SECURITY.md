# 安全与隐私说明

## 文档和网络请求

- 点击 **开始识别** 后，程序会读取直接选中的文件，或输入文件夹内受支持的文件。PDF 批次会发送到界面中配置的 OCR 接口。图片和 Office 文件先在本机转换为 PDF，再发送转换后的批次。
- 第三方服务如何存储或使用文档，取决于该服务的条款和隐私政策。上传前请确认你有权把文档交给所选服务处理。自定义接口建议使用 HTTPS。
- 程序会尝试下载识别结果 Markdown 中的图片链接到本机。请使用可信的 OCR 接口。

## 本地数据

- `设置.json` 保存 API 地址、输入输出位置和处理选项。位置字段可能包含个人目录。
- `API凭据.dat` 保存经 Windows DPAPI 保护的凭据，按已保存的 API 地址复用。点击 **清空 Key** 可删除该文件。换设备或 Windows 账户后请重新填写。[Windows DPAPI 说明](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
- 输出目录可能包含 Markdown、图片、来源文件名和分批响应。任务失败或中断时会保留部分缓存供续跑。分享日志或结果前，请移除文档内容、完整路径、API Key 和访问链接中的凭据。
- 如果 Key 可能已经泄露，请在服务商控制台撤销或轮换该 Key。清空本机保存记录只会删除本地副本。

## 报告安全问题

如果仓库已启用 GitHub 私密漏洞报告，请通过仓库的 **Security and quality → Report a vulnerability** 提交。请提供软件版本、影响和可复现的最小示例，并使用虚构文件和测试凭据。[GitHub 私密报告说明](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately)

若私密入口未启用，可开一个公开 Issue 请求私下联系方式。公开 Issue 请只写联系请求，漏洞细节和敏感材料通过私下渠道提供。
