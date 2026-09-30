# sopUpdate

通过 Dify Console 自动导出指定应用的完整 DSL。根应用由精确的应用名称和 tag 共同确定；程序还会递归导出它引用的 workflow tool，并生成 `manifest.json`。

认证逻辑来自 `DIFY-DSL-check-2026-09-17`：使用 Playwright 持久化 Edge 登录 Profile。首次运行时在浏览器中完成 SSO/MFA，30 分钟内可以静默复用登录状态，不需要复制或保存 token。

## 环境准备

需要 Python 3.11+ 和 Microsoft Edge。

```powershell
Set-Location C:\code\sopUpdate
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

如果机器上没有 Edge，可安装 Playwright Chromium：

```powershell
python -m playwright install chromium
```

## 导出 DSL

```powershell
python -m sop_update `
	--endpoint "https://dify-devs.maersk-digital.net" `
	--name "BL Enquiry" `
	--tag "cn_bl_enquiry_v1_0" `
	--workspace "CX Emails - China" `
	--output ".\exports\BL-Enquiry"
```

首次运行会打开 Edge：

1. 在打开的窗口中完成公司 SSO/MFA。
2. 不需要复制 Cookie，也不需要返回终端确认。
3. 程序检测到 Console API 可用后会自动继续下载。
4. 登录状态保存在 `.dify-profile/<域名>/`，人工登录成功后 30 分钟内优先静默复用。
5. 超过 30 分钟后程序会删除旧 Profile，重新打开 Edge 登录并建立新的 30 分钟有效期。

导出过程中会逐项显示当前应用、保存文件和新发现的依赖，例如：

```text
[1] Pulling DSL: BL Enquiry
[1] Saved: exports\BL-Enquiry\BL Enquiry.yml (2 new dependencies queued)
[2] Pulling DSL: Child Workflow
[2] Saved: exports\BL-Enquiry\Child Workflow.yml (0 new dependencies queued)
Completed: 2 DSL file(s); manifest: exports\BL-Enquiry\manifest.json
```

安装项目后也可以使用 `sop-update` 运行同样的参数：

```powershell
sop-update --endpoint "https://dify-devs.maersk-digital.net" --name "BL Enquiry endpoint" --tag "cn_bl_enquiry_v1_0" --workspace "CX Emails - China" --output ".\exports\BL-Enquiry"
```
sop-update --endpoint "https://dify-devs.maersk-digital.net" --name "split combine endpoint" --tag "cn_split_combine_v1_0" --workspace "CX Emails - China" --output ".\exports\split combine"


## 参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--endpoint` | 是 | Dify Console 根地址 |
| `--name` | 是 | High-Level Endpoint 应用的精确名称 |
| `--tag` | 是 | 根应用必须具有的精确 tag |
| `--workspace` | 否 | 目标 workspace 名称；省略则使用当前 workspace |
| `--output` | 否 | 输出目录，默认 `dify-dsl-export` |
| `--profile-dir` | 否 | 浏览器 Profile 目录 |
| `--login-timeout` | 否 | 等待人工登录的秒数，默认 600 |

## 输出

输出目录包含：

- 根应用的完整 YAML，导出请求使用 `include_secret=true`。
- 所有可解析的 workflow tool 依赖 YAML，包括递归依赖。
- `manifest.json`，记录应用、依赖关系和无法解析的引用。

输出可能包含密钥，`exports/`、`dify-dsl-export/` 和浏览器 Profile 已加入 `.gitignore`，不要提交到 Git。

## 测试

```powershell
python -m pytest
```
