# Auto Thaumcraft Research GUI

适用于神秘时代研究界面的 Windows 自动连线工具，提供可拖动控制面板、研究扫描、方案预览、自动拖动、`Esc` 急停和多屏支持。

> 本项目基于原作者 Silvia 的 [2824799/auto_thaumcraft_research](https://github.com/2824799/auto_thaumcraft_research) 开发。感谢原作者提供要素识别数据、合成关系、材质包和初始自动研究实现。

## 下载

前往 [Releases](https://github.com/gsrrison/auto_thaumcraft_research_gui/releases/latest) 下载：

- `AutoThaumcraftResearch.exe`：无需安装 Python，双击运行。
- `auto_thaumcraft_research.zip`：配套 Minecraft 材质包。

当前 EXE 未进行商业代码签名，Windows SmartScreen 首次运行时可能显示未知发布者提示。

EXE 内也包含默认材质包和坐标配置。首次运行时，会在 EXE 所在目录释放：

- `gc.txt`
- `auto_thaumcraft_research.zip`

## 使用方法

1. 将 `auto_thaumcraft_research.zip` 放入 Minecraft 的 `resourcepacks` 文件夹并启用。
2. 双击 `AutoThaumcraftResearch.exe`。
3. 多屏环境点击“选择屏幕”，选择 Minecraft 所在屏幕。
4. 打开神秘时代研究界面，点击“扫描研究”或按 `Ctrl + 8`。
5. 确认黄色连接方案后，点击“开始连线”或按 `Ctrl + 5`。
6. 自动拖动期间随时按 `Esc` 紧急停止。急停后需要重新扫描。

控制面板不会抢占 Minecraft 焦点，并会在截图和拖动期间自动隐藏。控制面板标题区域可用于拖动窗口。

## 功能

- 可拖动、置顶且不抢焦点的 GUI 控制面板
- 扫描研究盘并显示黄色连接方案
- 自动选择低消耗要素路径
- `Esc` 立即释放鼠标并终止后续拖动
- 屏幕选择、负坐标副屏和多屏鼠标换算
- 坐标编辑与绿框实时预览
- 扫描、连线快捷键自定义
- 识别失败、缺少要素、屏幕越界和焦点丢失提示

## 坐标设置

仓库中的默认 `gc.txt` 适用于原作者环境：

- 分辨率：2560×1440
- Windows 缩放：150%
- GTNH 2.8.0 beta4

其他环境请打开“坐标设置”，修改数值并点击“预览绿框”。坐标以当前所选屏幕左上角为 `(0, 0)`。

每行格式：

```text
起始X,起始Y,横向间距,横向数量,纵向间距,纵向数量,方框大小
```

四行依次表示：

1. 中间研究点阵第一层
2. 中间研究点阵第二层
3. 左侧要素列表
4. 右侧要素列表

## 从源码运行

需要 Windows 和 Python 3.14：

```powershell
py -3.14 -m pip install -r requirements.txt
py -3.14 main.py
```

也可以双击 `start.bat`。

## 构建 EXE

```powershell
py -3.14 -m pip install -r requirements-build.txt
.\build_exe.bat
```

生成文件位于 `dist\AutoThaumcraftResearch.exe`。

## 项目文件

- `main.py`：GUI、快捷键、屏幕选择和自动拖动
- `research_core.py`：坐标配置、截图识别和连接规划
- `hcb.py`：要素数据、合成关系和颜色识别
- `gc.txt`：屏幕坐标配置
- `class.txt` / `ys.txt`：要素分类与颜色数据
- `auto_thaumcraft_research.zip`：配套材质包

## 许可与致谢

本项目沿用仓库中的 MIT License。原始实现与数据来自 [2824799/auto_thaumcraft_research](https://github.com/2824799/auto_thaumcraft_research)。
