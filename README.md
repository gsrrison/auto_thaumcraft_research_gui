# Auto Thaumcraft Research GUI

适用于神秘时代4研究界面的自动连线工具，提供可拖动控制面板、研究扫描、方案预览、自动拖动、急停和多屏支持。
在GTNH 2.9.0 beta1环境下测试通过。

> 本项目基于原作者 Silvia 的 [2824799/auto_thaumcraft_research](https://github.com/2824799/auto_thaumcraft_research) 开发。感谢原作者提供要素识别数据、合成关系、材质包和初始自动研究实现。

## 使用方法

1. 启用材质包：将 `auto_thaumcraft_research.zip` 放入 Minecraft 的 `resourcepacks` 文件夹并启用。
2. 启动程序：双击 `AutoThaumcraftResearch.exe`。
3. 多屏环境点击“选择屏幕”，选择 Minecraft 所在屏幕。
4. 打开神秘时代研究界面，点击“扫描研究”或按 `Ctrl + 8`。
5. 确认黄色连接方案后，点击“开始连线”或按 `Ctrl + 5`。
6. 自动拖动期间随时按 `Esc` 紧急停止。急停后需要重新扫描。

## 坐标设置

仓库中的默认 `gc.txt` 适用于原环境：

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

## 许可与致谢

本项目沿用仓库中的 MIT License。原始实现与数据来自 [2824799/auto_thaumcraft_research](https://github.com/2824799/auto_thaumcraft_research)。
