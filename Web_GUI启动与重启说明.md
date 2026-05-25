# Web GUI 启动与重启说明

本文档面向团队成员，说明如何在本机成功启动项目的 Web GUI，以及如何使用新的端口重启服务。以下命令默认在 Windows PowerShell 中执行。

## 1. 克隆并进入项目目录

队友从 GitHub 克隆仓库后，进入仓库根目录即可。示例：

```powershell
git clone <你的 GitHub 仓库地址>
cd data-structure-main
```

如果已经 clone 过，只需要进入自己电脑上的 `data-structure-main` 目录。后续所有命令都默认在仓库根目录执行。

## 2. 创建并启用 Python 虚拟环境

推荐在仓库根目录下创建一个本地虚拟环境：

```powershell
python -m venv .venv
```

然后启用它：

```powershell
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 提示脚本执行策略不允许，可以临时使用：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

激活成功后，终端前面通常会出现 `(.venv)`。

## 3. 安装依赖

如果是第一次运行，先安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

然后安装 Web 前端依赖：

```powershell
cd web_client
npm install
cd ..
```

如果已经安装过依赖，这一步可以跳过。

## 4. 构建 Web GUI

Web GUI 使用 React/Vite/TypeScript 编写，Flask 会托管构建后的静态页面。每次修改前端代码后，都需要重新构建：

```powershell
cmd /c npm --prefix web_client run build
```

构建成功后，产物会自动输出到 `web_ui/`，之后由 `python web_server.py` 提供访问。

## 5. 使用默认新端口启动

当前 Web 服务默认端口已经改为 `5681`。启动命令：

```powershell
python web_server.py
```

启动后浏览器会自动打开：

```text
http://localhost:5681
```

如果浏览器没有自动打开，可以手动访问：

```text
http://127.0.0.1:5681
```

## 6. 使用指定端口重启

如果 `5681` 被占用，或者需要同时保留其它版本，可以通过环境变量指定新端口。例如使用 `5682`：

```powershell
$env:NAV_WEB_PORT="5682"
python web_server.py
```

访问地址变为：

```text
http://localhost:5682
```

如果想恢复默认端口 `5681`，关闭当前终端后重新打开即可；或者执行：

```powershell
Remove-Item Env:NAV_WEB_PORT
python web_server.py
```

## 7. 如何停止旧服务

如果服务是在当前终端前台运行，按：

```text
Ctrl + C
```

即可停止。

如果服务是后台运行，或者端口被占用，可以先查看端口对应的进程：

```powershell
Get-NetTCPConnection -LocalPort 5681 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,State,OwningProcess
```

然后停止对应进程。假设查到的 `OwningProcess` 是 `40632`：

```powershell
Stop-Process -Id 40632
```

也可以把端口号换成你实际使用的端口，例如 `5682`。

## 8. 推荐验收命令

启动前建议运行以下检查，确认 Web GUI 与 API 都正常：

```powershell
cmd /c npm --prefix web_client run typecheck
cmd /c npm --prefix web_client run build
python -X utf8 test_web_api.py
```

三条命令都通过后，再运行：

```powershell
python web_server.py
```

## 9. 常见问题

### 页面还是旧版本

前端改动后需要重新构建：

```powershell
cmd /c npm --prefix web_client run build
```

然后刷新浏览器。必要时使用强制刷新：

```text
Ctrl + F5
```

### 端口被占用

使用新的端口启动：

```powershell
$env:NAV_WEB_PORT="5682"
python web_server.py
```

或者停止占用旧端口的 Python 进程。

### localhost 访问异常

可以尝试使用：

```text
http://127.0.0.1:5681
```

如果仍异常，检查服务是否真的在监听：

```powershell
Get-NetTCPConnection -LocalPort 5681 -ErrorAction SilentlyContinue
```

## 10. 最短启动流程

如果依赖已经安装好，日常演示只需要：

```powershell
cd data-structure-main
.\.venv\Scripts\Activate.ps1
cmd /c npm --prefix web_client run build
python web_server.py
```

然后打开：

```text
http://localhost:5681
```
