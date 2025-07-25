﻿# 文件路径: ui/tabs/genome_identifier_tab.py

import tkinter as tk
from typing import TYPE_CHECKING, Callable, Optional

import ttkbootstrap as ttkb

from .base_tab import BaseTab
from ..utils.gui_helpers import identify_genome_from_gene_ids

if TYPE_CHECKING:
    from ..gui_app import CottonToolkitApp

try:
    from builtins import _
except ImportError:
    _ = lambda s: str(s)


class GenomeIdentifierTab(BaseTab):
    def __init__(self, parent, app: "CottonToolkitApp", translator: Callable[[str], str]):
        # 将 translator 传递给父类
        super().__init__(parent, app, translator=translator)

        if self.action_button:
            # self._ 属性在 super().__init__ 后才可用
            self.action_button.configure(text=self._("开始鉴定"), command=self.start_identification_task)

            # 获取按钮所在的父容器
            action_frame = self.action_button.master
            action_frame.grid_columnconfigure(0, weight=1)
            action_frame.grid_columnconfigure(1, weight=0)

            # --- 初始化并储存结果标签 ---
            self.result_var = tk.StringVar(value=self._("鉴定结果将显示在这里。"))
            self.result_label = ttkb.Label(action_frame, textvariable=self.result_var, anchor="w",
                                           font=self.app.app_font)
            self.result_label.grid(row=0, column=0, sticky="ew", padx=(10, 10))
            self.action_button.grid(row=0, column=1, sticky="e")

        self.update_from_config()

    def _create_widgets(self):
        """
        创建此选项卡内的所有 UI 元件。
        【修改】将所有需要翻译的元件都储存为 self 的属性。
        """
        parent_frame = self.scrollable_frame
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(1, weight=1)

        # --- 储存 UI 元件 ---
        self.title_label = ttkb.Label(parent_frame, text=_("基因组类别鉴定工具"), font=self.app.app_title_font,
                                      bootstyle="primary")
        self.title_label.grid(row=0, column=0, padx=10, pady=(10, 15), sticky="n")

        self.input_card = ttkb.LabelFrame(parent_frame, text=_("输入基因列表"), bootstyle="secondary")
        self.input_card.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        self.input_card.grid_columnconfigure(0, weight=1)
        self.input_card.grid_rowconfigure(1, weight=1)

        self.description_label = ttkb.Label(self.input_card,
                                            text=_("在此处粘贴一个基因列表，工具将尝试识别它们属于哪个基因组版本。"),
                                            wraplength=650, justify='left')
        self.description_label.grid(row=0, column=0, sticky='w', padx=10, pady=(10, 5))

        text_bg = self.app.style.lookup('TFrame', 'background')
        text_fg = self.app.style.lookup('TLabel', 'foreground')
        self.gene_list_textbox = tk.Text(self.input_card, height=15, wrap="word", relief="flat", background=text_bg,
                                         foreground=text_fg, insertbackground=text_fg, font=self.app.app_font_mono)
        self.gene_list_textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 10))

    def retranslate_ui(self, translator: Callable[[str], str]):
        """
        当语言切换时，此方法被 UIManager 调用以更新 UI 文本。
        """
        self.title_label.configure(text=translator("基因组类别鉴定工具"))
        self.input_card.configure(text=translator("输入基因列表"))
        self.description_label.configure(
            text=translator("在此处粘贴一个基因列表，工具将尝试识别它们属于哪个基因组版本。"))

        # 重设结果标签的初始文字
        if hasattr(self, 'result_var'):
            self.result_var.set(translator("鉴定结果将显示在这里。"))
            self.result_label.configure(bootstyle="default", font=self.app.app_font)

        if self.action_button:
            self.action_button.configure(text=translator("开始鉴定"))

    def update_from_config(self):
        self.update_button_state(self.app.active_task_name is not None, self.app.current_config is not None)

    def start_identification_task(self):
        """
        【已修改】启动基因组鉴定后台任务。
        将耗时的 identify_genome_from_gene_ids 函数放入后台线程。
        """
        # --- 前置检查 (这部分逻辑不变) ---
        if not self.app.current_config:
            self.app.ui_manager.show_error_message(self._("错误"), self._("请先加载配置文件。"))
            return
        if not self.app.genome_sources_data:
            self.app.ui_manager.show_error_message(self._("错误"), self._("基因组源数据未加载，无法进行鉴定。"))
            return

        gene_ids_text = self.gene_list_textbox.get("1.0", tk.END).strip()
        if not gene_ids_text:
            self.app.ui_manager.show_error_message(self._("输入缺失"), self._("请输入至少一个基因ID进行鉴定。"))
            return

        gene_ids = [g.strip() for g in gene_ids_text.replace(",", "\n").splitlines() if g.strip()]

        # --- UI准备 (更新UI提示用户任务已开始) ---
        self.result_var.set(self._("正在鉴定中..."))
        self.result_label.configure(bootstyle="info", font=self.app.app_font_italic)
        self.app.update_idletasks()  # 强制UI刷新，立即显示“正在鉴定中”

        # --- 启动后台任务 ---
        # 使用您项目已有的 event_handler._start_task 框架
        self.app.event_handler._start_task(
            task_name=self._("基因组鉴定"),
            target_func=identify_genome_from_gene_ids,  # 将要执行的耗时函数
            kwargs={
                'gene_ids': gene_ids,
                'genome_sources': self.app.genome_sources_data
                # 'status_callback' 和 'cancel_event' 会由 _start_task 自动注入
            }
        )

    def handle_identification_result(self, identified_assembly: Optional[str]):
        """
        此方法将由 event_handler 在任务结束后调用，用于安全地更新UI。
        """
        if identified_assembly:
            result_text = f"{self._('鉴定结果')}: {identified_assembly}"
            self.result_var.set(result_text)
            self.result_label.configure(bootstyle="success", font=self.app.app_font_bold)
            # Log successful identification to the main log viewer
            self.app._log_to_viewer(f"{self._('基因组鉴定成功')}: {identified_assembly}", "INFO")
        else:
            self.result_var.set(self._("未能识别到匹配的基因组。"))
            self.result_label.configure(bootstyle="warning", font=self.app.app_font)
            # Log failed identification to the main log viewer
            self.app._log_to_viewer(self._("基因组鉴定失败：未能识别到匹配的基因组。"), "WARNING")
