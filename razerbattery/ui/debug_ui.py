"""形态 C：完整调试界面（--debug）。

提供：全 HID 枚举、Feature Report 转储、Report ID 探测、协议查询命令测试、
十六进制显示、手动标定协议参数、JSON 标定保存/加载与有效性检查。
所有操作只读优先；仅在用户点「协议测试」时才发已知安全的电池查询命令。
"""

import json
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import hid_device as HD
from .. import protocol
from ..hid_enum import enumerate_hid_devices

DEFAULT_CALIBRATION = {
    "report_id": 0,
    "feature_len": 91,
    "transaction_id": 31,
    "command_class": 2,
    "command_id": 7,
    "response_offset": 10,
    "timeout": 3.0,
    "poll": 0.005,
}


def _hex(data, per_line=32):
    if not data:
        return "(空)"
    lines = []
    for i in range(0, len(data), per_line):
        chunk = data[i:i + per_line]
        lines.append("%04X  %s" % (i, " ".join("%02X" % b for b in chunk)))
    return "\n".join(lines)


class DebugWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("调试 — Razer 电量工具")
        self.geometry("980x680")
        self._devices = []
        self._selected = None
        self._calibration = dict(DEFAULT_CALIBRATION)

        self._build()
        self.refresh()

    def _build(self):
        top = tk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        tk.Button(top, text="重新枚举", command=self.refresh).pack(side="left")
        tk.Label(top, text="双击列表项查看详情", font=("Microsoft YaHei UI", 8), fg="#888").pack(side="left", padx=10)

        cols = ("vid", "pid", "product", "usage", "in", "out", "feat", "path")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=10)
        for c, name, w in (
            ("vid", "VID", 70), ("pid", "PID", 70), ("product", "Product", 200),
            ("usage", "Usage", 90), ("in", "In", 50), ("out", "Out", 50),
            ("feat", "Feat", 55), ("path", "Path", 320),
        ):
            self.tree.heading(c, text=name)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="x", padx=8)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.detail = tk.Text(self, height=8, font=("Consolas", 9), wrap="none", state="disabled")
        self.detail.pack(fill="x", padx=8, pady=4)

        btn = tk.Frame(self)
        btn.pack(fill="x", padx=8)
        tk.Button(btn, text="转储 Feature Report", command=self._dump_feature).pack(side="left")
        tk.Button(btn, text="Report ID 探测", command=self._probe_report_ids).pack(side="left", padx=6)
        tk.Button(btn, text="协议测试(读电池)", command=self._test_battery).pack(side="left", padx=6)

        # 标定区
        cal = tk.LabelFrame(self, text="手动标定协议参数")
        cal.pack(fill="x", padx=8, pady=6)
        self._cal_vars = {}
        row1 = tk.Frame(cal)
        row1.pack(fill="x", pady=2)
        row2 = tk.Frame(cal)
        row2.pack(fill="x", pady=2)
        fields = [
            ("transaction_id", "交易ID", 0, row1), ("command_class", "命令类", 1, row1),
            ("command_id", "命令ID", 2, row1), ("response_offset", "响应偏移", 3, row1),
            ("feature_len", "报告长度", 4, row1), ("timeout", "超时(s)", 0, row2),
            ("poll", "轮询(s)", 1, row2),
        ]
        for key, label, idx, parent in fields:
            tk.Label(parent, text=label, font=("Microsoft YaHei UI", 9)).grid(row=0, column=idx * 2, padx=4, sticky="e")
            v = tk.StringVar(value=str(self._calibration.get(key, "")))
            tk.Entry(parent, textvariable=v, width=8).grid(row=0, column=idx * 2 + 1, padx=2)
            self._cal_vars[key] = v
        brow = tk.Frame(cal)
        brow.pack(fill="x", pady=4)
        tk.Button(brow, text="读取标定参数到表单", command=self._apply_cal_to_form).pack(side="left")
        tk.Button(brow, text="保存标定 JSON", command=self._save_cal).pack(side="left", padx=6)
        tk.Button(brow, text="加载标定 JSON", command=self._load_cal).pack(side="left", padx=6)

        self.out = tk.Text(self, font=("Consolas", 9), wrap="none")
        self.out.pack(fill="both", expand=True, padx=8, pady=6)

    def _log(self, text):
        self.out.insert("end", text + "\n")
        self.out.see("end")

    # ---- 枚举 ----
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._devices = enumerate_hid_devices()
        for i, d in enumerate(self._devices):
            usage = "%04X:%04X" % (d.usage_page, d.usage)
            self.tree.insert("", "end", iid=str(i), values=(
                "%04X" % d.vid, "%04X" % d.pid, d.product or d.description, usage,
                d.input_report_len, d.output_report_len, d.feature_report_len, d.path,
            ))
        self._log("枚举完成：%d 个 HID 接口" % len(self._devices))

    def _on_select(self, _evt):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        self._selected = self._devices[idx]
        d = self._selected
        text = (
            "Product: %s\n" % (d.product or d.description)
            + "VID:PID : %04X:%04X  版本 %d\n" % (d.vid, d.pid, d.version)
            + "Usage   : page=0x%04X usage=0x%04X\n" % (d.usage_page, d.usage)
            + "Report  : in=%d out=%d feat=%d\n" % (d.input_report_len, d.output_report_len, d.feature_report_len)
            + "Mfg     : %s\n" % d.manufacturer
            + "Serial  : %s\n" % d.serial
            + "HWIDs   : %s\n" % "; ".join(d.hardware_ids)
            + "Instance: %s\n" % d.instance_id
            + "Path    : %s\n" % d.path
        )
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.config(state="disabled")

    def _open_selected(self):
        if not self._selected:
            messagebox.showinfo("提示", "请先选择一个设备")
            return None
        try:
            return HD.open_battery_device(self._selected.path)
        except HD.HidError as e:
            messagebox.showerror("打开失败", str(e))
            return None

    # ---- 动作 ----
    def _dump_feature(self):
        d = self._selected
        if not d:
            return
        if d.feature_report_len <= 0:
            self._log("该接口无 Feature Report")
            return
        h = self._open_selected()
        if h is None:
            return
        try:
            r = HD.get_feature_report(h, 0x00, d.feature_report_len)
            self._log("Feature Report 转储 (len=%d):\n%s" % (len(r), _hex(r)))
        except HD.HidError as e:
            self._log("转储失败: %s" % e)
        finally:
            HD.close_device(h)

    def _probe_report_ids(self):
        d = self._selected
        if not d:
            return
        if d.feature_report_len <= 0:
            self._log("该接口无 Feature Report，无法探测")
            return
        h = self._open_selected()
        if h is None:
            return
        try:
            self._log("Report ID 探测 (只读 GetFeature, 0x00~0x0F):")
            for rid in range(0x00, 0x10):
                try:
                    r = HD.get_feature_report(h, rid, d.feature_report_len)
                    self._log("  report_id=0x%02X -> %s" % (rid, _hex(r[:8]) + (" ..." if len(r) > 8 else "")))
                except HD.HidError:
                    self._log("  report_id=0x%02X -> 读取失败" % rid)
        finally:
            HD.close_device(h)

    def _read_cal(self):
        cal = {}
        for key, var in self._cal_vars.items():
            val = var.get().strip()
            try:
                if key in ("timeout", "poll"):
                    cal[key] = float(val)
                else:
                    cal[key] = int(val, 0)
            except ValueError:
                messagebox.showerror("参数错误", "字段 %s 的值非法: %s" % (key, val))
                return None
        return cal

    def _test_battery(self):
        d = self._selected
        if not d:
            return
        if d.feature_report_len <= 0:
            self._log("该接口无 Feature Report，无法测试")
            return
        cal = self._read_cal()
        if cal is None:
            return
        h = self._open_selected()
        if h is None:
            return
        try:
            raw, report = protocol.read_battery_with_params(
                h, d.feature_report_len, cal["transaction_id"], cal["command_class"],
                cal["command_id"], cal["response_offset"], timeout=cal["timeout"], poll=cal["poll"],
            )
            if raw is None:
                self._log("协议测试：无响应（可能 txid 被并发交易干扰或设备忙）")
            else:
                pct = protocol.raw_to_percent(raw)
                valid = 0 <= raw <= 255 and 0 <= pct <= 100
                self._log("协议测试：raw=%d percent=%d%%  有效性=%s" % (raw, pct, "有效" if valid else "无效"))
            if report:
                self._log("响应 hex:\n%s" % _hex(report))
        except HD.HidError as e:
            self._log("协议测试失败: %s" % e)
        finally:
            HD.close_device(h)

    # ---- 标定 JSON ----
    def _apply_cal_to_form(self):
        for key, var in self._cal_vars.items():
            var.set(str(self._calibration.get(key, "")))

    def _save_cal(self):
        cal = self._read_cal()
        if cal is None:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")], title="保存标定配置"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cal, f, ensure_ascii=False, indent=2)
            self._calibration = cal
            self._log("标定已保存: %s" % path)
        except OSError as e:
            messagebox.showerror("保存失败", str(e))

    def _load_cal(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")], title="加载标定配置")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cal = json.load(f)
            for k in DEFAULT_CALIBRATION:
                if k not in cal:
                    messagebox.showwarning("配置不完整", "缺少字段: %s" % k)
                    return
            self._calibration = cal
            self._apply_cal_to_form()
            self._log("标定已加载: %s" % path)
        except (OSError, json.JSONDecodeError) as e:
            messagebox.showerror("加载失败", str(e))
