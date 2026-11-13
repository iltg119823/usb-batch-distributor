# U盘程序文件批量分发工具

Windows 桌面工具，用于将选定目录中的程序文件批量复制到检测到的 U 盘，并在复制完成后弹出 U 盘。

## 运行

安装带 Tkinter 的 Windows 版 Python 3，然后在项目目录执行：

```powershell
python copy_gui_with_eject.py
```

插入目标 U 盘，点击「刷新/检测」，选择源文件夹并确认目标盘符。点击「一键拷贝至所有U盘」，检查日志确认复制完成，再点击「一键弹出所有U盘」。复制可能覆盖目标盘上的同名文件，请先备份重要数据。

## 打包

```powershell
python -m pip install pyinstaller
python -m PyInstaller copy_gui_with_eject.spec
```

生成文件位于 `dist/copy_gui_with_eject.exe`。
