import os
import shutil
import string
import sys
import ctypes
from ctypes import wintypes
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# --- Windows 底层 API 定义 ---
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = -1
FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_DISMOUNT_VOLUME = 0x00090020
IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808

def is_drive_ready(drive_path):
    """检测盘符是否真正可用（过滤已弹出但未拔出的死盘符）"""
    try:
        # 获取卷信息，若已弹出此调用会直接失败
        kernel32 = ctypes.windll.kernel32
        vol_name = ctypes.create_unicode_buffer(260)
        fs_name = ctypes.create_unicode_buffer(260)
        serial = wintypes.DWORD()
        max_len = wintypes.DWORD()
        flags = wintypes.DWORD()
        
        res = kernel32.GetVolumeInformationW(
            drive_path, vol_name, 260,
            ctypes.byref(serial),
            ctypes.byref(max_len),
            ctypes.byref(flags),
            fs_name, 260
        )
        return bool(res)
    except Exception:
        return False

def get_removable_drives():
    """获取系统所有真正可读写的 U 盘（可移动磁盘）"""
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in string.ascii_uppercase:
        if bitmask & 1:
            drive_path = f"{letter}:\\"
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
            # DRIVE_REMOVABLE = 2
            if drive_type == 2 and is_drive_ready(drive_path):
                drives.append(drive_path)
        bitmask >>= 1
    return drives

def eject_drive_fast(drive_path):
    """纯 API 毫秒级安全卸载与弹出 U 盘（绝不阻塞挂死）"""
    letter = drive_path.rstrip(":\\/").upper()
    device_path = f"\\\\.\\{letter}:"
    
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateFileW(
        device_path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None
    )
    
    if handle == INVALID_HANDLE_VALUE:
        return False, "无法获取设备句柄（可能正被资源管理器或其他程序占用）"

    bytes_returned = wintypes.DWORD()
    try:
        # 1. 尝试锁定卷
        kernel32.DeviceIoControl(
            handle, FSCTL_LOCK_VOLUME, None, 0, None, 0, ctypes.byref(bytes_returned), None
        )
        # 2. 强制卸载卷（断开所有读写连接）
        kernel32.DeviceIoControl(
            handle, FSCTL_DISMOUNT_VOLUME, None, 0, None, 0, ctypes.byref(bytes_returned), None
        )
        # 3. 弹出介质
        res = kernel32.DeviceIoControl(
            handle, IOCTL_STORAGE_EJECT_MEDIA, None, 0, None, 0, ctypes.byref(bytes_returned), None
        )
        if res:
            return True, "已安全卸载并弹出"
        else:
            return False, "弹出指令被系统拒绝"
    finally:
        kernel32.CloseHandle(handle)

# 规则表：前缀 -> (目标子目录, 备份前缀)
PREFIX_RULES = {
    "TJ01": ("TJ01\\PRO", "TJ"),
    "TJ03": ("TJ03\\PRO", "TJ"),
    "SGC1": ("SG01\\PRO", "SG01"),
    "SGC2": ("SG01\\PRO", "SG02"),
    "RHCB": ("RHCB\\PRO", "RHCB"),
    "PWMB": ("PWMB\\PRO", "PWMB"),
    "EB25": ("MS25\\PRO", "EB25"),
    "MS25": ("MS25\\PRO", "MS25"),
    "ROWB": ("MS19\\PRO", "ROWB"),
    "KN10": ("KN10\\PRO", "KN10"),
    "IBMP": ("IBMP\\PRO", "IBMP"),
    "H1DS1": ("HAC01DS1\\PRO", "H1DS1"),
    "H2DP1": ("H2DP1\\PRO", "H2DP1"),
    "CROW": ("GSUPDATE\\PRO", "CROW"),
    "OU20": ("FATH\\PRO", "OU20"),
    "FAEB": ("FA36\\PRO", "FAEB"),
    "HJ06": ("HJ06\\PRO", "HJ06"),
}

def backup_files_by_prefix(target_dir, backup_prefix, log_func):
    """若存在 backup_prefix 开头的文件，重命名加上 'XXX' 前缀"""
    if not os.path.exists(target_dir):
        return

    for item in os.listdir(target_dir):
        if item.startswith(backup_prefix) and not item.startswith("XXX"):
            old_file_path = os.path.join(target_dir, item)
            if os.path.isfile(old_file_path):
                new_filename = f"XXX{item}"
                new_file_path = os.path.join(target_dir, new_filename)
                
                if os.path.exists(new_file_path):
                    os.remove(new_file_path)
                
                os.rename(old_file_path, new_file_path)
                log_func(f"  [备份] 已重命名旧文件: {item} -> {new_filename}")

def backup_file_exact(target_file_path, log_func):
    """同名文件备份（.fpg）：加上 XXX 前缀"""
    if os.path.isfile(target_file_path):
        target_dir = os.path.dirname(target_file_path)
        filename = os.path.basename(target_file_path)
        new_filename = f"XXX{filename}"
        new_file_path = os.path.join(target_dir, new_filename)
        
        if os.path.exists(new_file_path):
            os.remove(new_file_path)
        
        os.rename(target_file_path, new_file_path)
        log_func(f"  [备份] 已重命名同名文件: {filename} -> {new_filename}")

def backup_tpcbackup_dirs(target_root_dir, log_func):
    """若存在 tpcbackup 文件夹，重命名加上 'XXX+时分秒' 前缀"""
    if not os.path.exists(target_root_dir):
        return

    time_str = datetime.now().strftime("%H%M%S")
    for item in os.listdir(target_root_dir):
        if item.lower().startswith("tpcbackup") and not item.startswith("XXX"):
            old_dir_path = os.path.join(target_root_dir, item)
            if os.path.isdir(old_dir_path):
                new_dirname = f"XXX{time_str}_{item}"
                new_dir_path = os.path.join(target_root_dir, new_dirname)
                
                if os.path.exists(new_dir_path):
                    shutil.rmtree(new_dir_path)
                
                os.rename(old_dir_path, new_dir_path)
                log_func(f"  [备份] 已重命名旧文件夹: {item} -> {new_dirname}")

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("U盘程序文件批量分发与安全弹出工具 v2.1")
        self.root.geometry("720x600")
        self.root.minsize(620, 500)

        base_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
        default_source = os.path.join(base_dir, "source_files")

        # 1. 源目录选择区域
        frame_top = ttk.LabelFrame(root, text=" 源文件夹设置 ", padding=10)
        frame_top.pack(fill="x", padx=12, pady=6)

        self.path_var = tk.StringVar(value=default_source)
        ttk.Entry(frame_top, textvariable=self.path_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(frame_top, text="浏览...", command=self.select_dir, width=10).pack(side="right")

        # 2. 控制按钮区域
        frame_btn = ttk.Frame(root, padding=4)
        frame_btn.pack(fill="x", padx=12, pady=4)

        self.run_btn = ttk.Button(frame_btn, text="🚀 一键拷贝至所有U盘", command=lambda: self.start_thread(self.run_copy_task))
        self.run_btn.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))

        self.eject_btn = ttk.Button(frame_btn, text="⏏️ 一键弹出所有U盘", command=lambda: self.start_thread(self.run_eject_task))
        self.eject_btn.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))

        self.refresh_btn = ttk.Button(frame_btn, text="🔄 刷新/检测", command=self.detect_usb, width=12)
        self.refresh_btn.pack(side="right", ipady=5)

        # 3. 日志区域
        frame_log = ttk.LabelFrame(root, text=" 执行日志 ", padding=10)
        frame_log.pack(fill="both", expand=True, padx=12, pady=6)

        self.log_area = scrolledtext.ScrolledText(frame_log, wrap="word", height=15, font=("Consolas", 9))
        self.log_area.pack(fill="both", expand=True)

        self.detect_usb()

    def log(self, text):
        self.root.after(0, self._append_log, text)

    def _append_log(self, text):
        self.log_area.insert("end", text + "\n")
        self.log_area.see("end")

    def select_dir(self):
        selected = filedialog.askdirectory(title="选择源程序文件夹", initialdir=self.path_var.get())
        if selected:
            self.path_var.set(os.path.normpath(selected))

    def detect_usb(self):
        drives = get_removable_drives()
        if drives:
            self.log(f"[U盘检测] 发现可用U盘: {', '.join(drives)}")
        else:
            self.log("[U盘检测] 当前未检测到已连接/可用的U盘设备")

    def set_buttons_state(self, state):
        self.run_btn.config(state=state)
        self.eject_btn.config(state=state)
        self.refresh_btn.config(state=state)

    def start_thread(self, task_func):
        self.set_buttons_state("disabled")
        threading.Thread(target=task_func, daemon=True).start()

    def run_copy_task(self):
        try:
            source_dir = self.path_var.get().strip()
            self.log("\n" + "=" * 50)
            self.log("[开始] 正在执行文件分发...")

            if not os.path.exists(source_dir):
                self.log(f"[错误] 源目录不存在: {source_dir}")
                messagebox.showerror("错误", "指定的源文件夹不存在！")
                return

            usb_drives = get_removable_drives()
            if not usb_drives:
                self.log("[错误] 未找到任何可用U盘，操作终止！")
                messagebox.showwarning("提示", "未检测到可用U盘，请插入U盘后再试！")
                return

            items = os.listdir(source_dir)
            if not items:
                self.log(f"[提示] 源文件夹为空: {source_dir}")
                messagebox.showinfo("提示", "源文件夹为空！")
                return

            count = 0
            sorted_rules = sorted(PREFIX_RULES.items(), key=lambda x: len(x[0]), reverse=True)

            for item_name in items:
                src_path = os.path.join(source_dir, item_name)
                is_dir = os.path.isdir(src_path)
                is_file = os.path.isfile(src_path)

                # 规则 1：tpcbackup 文件夹
                if is_dir and item_name.lower().startswith("tpcbackup"):
                    self.log(f"\n[处理目录] {item_name} -> 目标: [所有U盘根目录]")
                    for drive in usb_drives:
                        backup_tpcbackup_dirs(drive, self.log)
                        dest_path = os.path.join(drive, item_name)
                        if os.path.exists(dest_path):
                            shutil.rmtree(dest_path)
                        shutil.copytree(src_path, dest_path)
                        self.log(f"  [成功] 文件夹 -> {dest_path}")
                        count += 1
                    continue

                if not is_file:
                    continue

                # 规则 2：.fpg 后缀
                if item_name.lower().endswith(".fpg"):
                    self.log(f"\n[处理.fpg] {item_name} -> 目标: [所有U盘根目录]")
                    for drive in usb_drives:
                        dest_path = os.path.join(drive, item_name)
                        backup_file_exact(dest_path, self.log)
                        shutil.copy2(src_path, dest_path)
                        self.log(f"  [成功] -> {dest_path}")
                        count += 1
                    continue

                # 规则 3：前缀映射表
                matched_rule = None
                for prefix, (target_sub, backup_prefix) in sorted_rules:
                    if item_name.startswith(prefix):
                        matched_rule = (target_sub, backup_prefix)
                        break

                if matched_rule:
                    target_sub, backup_prefix = matched_rule
                    self.log(f"\n[处理文件] {item_name} -> 目标: [U盘]:\\{target_sub}")
                    for drive in usb_drives:
                        target_dir = os.path.join(drive, target_sub)
                        os.makedirs(target_dir, exist_ok=True)

                        backup_files_by_prefix(target_dir, backup_prefix, self.log)

                        dest_path = os.path.join(target_dir, item_name)
                        shutil.copy2(src_path, dest_path)
                        self.log(f"  [成功] -> {dest_path}")
                        count += 1
                else:
                    self.log(f"[跳过] 未匹配到任何规则: {item_name}")

            self.log("=" * 50)
            self.log(f"[完成] 所有分发任务结束，共完成 {count} 次拷贝！\n")
            messagebox.showinfo("完成", f"文件分发完成！\n共执行拷贝操作 {count} 次。")

        except Exception as e:
            self.log(f"[异常] 发生错误: {str(e)}")
            messagebox.showerror("异常", f"执行过程中出错: {e}")
        finally:
            self.root.after(0, lambda: self.set_buttons_state("normal"))

    def run_eject_task(self):
        try:
            self.log("\n" + "=" * 50)
            self.log("[开始] 正在快速安全弹出所有U盘...")

            usb_drives = get_removable_drives()
            if not usb_drives:
                self.log("[提示] 当前没有检测到可弹出的U盘。")
                messagebox.showinfo("提示", "当前没有检测到任何U盘设备。")
                return

            success_count = 0
            for drive in usb_drives:
                ok, msg = eject_drive_fast(drive)
                if ok:
                    self.log(f"  [成功] 盘符 {drive} -> {msg}")
                    success_count += 1
                else:
                    self.log(f"  [失败] 盘符 {drive} -> {msg}")

            self.log("=" * 50)
            self.log(f"[完成] 弹出操作结束，成功安全卸载 {success_count}/{len(usb_drives)} 个设备。\n")
            
            # 自动刷新状态（已弹出的设备不会再显示）
            self.detect_usb()

            if success_count == len(usb_drives):
                messagebox.showinfo("弹出完成", f"已安全卸载所有 U 盘（共 {success_count} 个），缓存已写完，现在可以安全拔出！")
            else:
                messagebox.showwarning("提示", f"成功卸载 {success_count} 个设备，部分设备可能被占用未能弹出。")

        except Exception as e:
            self.log(f"[异常] 弹出过程出错: {str(e)}")
            messagebox.showerror("异常", f"弹出失败: {e}")
        finally:
            self.root.after(0, lambda: self.set_buttons_state("normal"))

if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
