﻿# 文件路径: ui/tabs/enrichment_tab.py

import os
import re
import tkinter as tk
from tkinter import ttk, filedialog
from typing import TYPE_CHECKING, Callable, Optional, List

import ttkbootstrap as ttkb

from cotton_toolkit.pipelines import run_enrichment_pipeline
from .base_tab import BaseTab

if TYPE_CHECKING:
    from ..gui_app import CottonToolkitApp

try:
    from builtins import _
except ImportError:
    _ = lambda s: str(s)


class EnrichmentTab(BaseTab):
    """
    负责GO和KEGG富集分析及可视化的UI界面。
    """

    def __init__(self, parent, app: "CottonToolkitApp", translator: Callable[[str], str]):
        self.app = app
        self.assembly_id_var = tk.StringVar()
        self.has_header_var = tk.BooleanVar(value=False)
        self.has_log2fc_var = tk.BooleanVar(value=False)
        self.analysis_type_var = tk.StringVar(value="go")
        self.collapse_transcripts_var = tk.BooleanVar(value=False)
        self.bubble_plot_var = tk.BooleanVar(value=True)
        self.bar_plot_var = tk.BooleanVar(value=True)
        self.upset_plot_var = tk.BooleanVar(value=False)
        self.cnet_plot_var = tk.BooleanVar(value=False)
        self.top_n_var = tk.IntVar(value=20)
        self.sort_by_var = tk.StringVar(value="FDR")
        self.show_title_var = tk.BooleanVar(value=True)
        self.width_var = tk.DoubleVar(value=10.0)
        self.height_var = tk.DoubleVar(value=8.0)
        self.file_format_var = tk.StringVar(value="png")

        # 将 translator 传递给父类
        super().__init__(parent, app, translator=translator)

        if self.action_button:
            # self._ 属性在 super().__init__ 后才可用
            self.action_button.configure(text=self._("开始富集分析"), command=self.start_enrichment_task)
        self.update_from_config()

    def _create_widgets(self):
        parent_frame = self.scrollable_frame
        parent_frame.grid_columnconfigure(0, weight=1)

        self.title_label = ttkb.Label(parent_frame, text=_("富集分析与绘图"), font=self.app.app_title_font,
                                      bootstyle="primary")
        self.title_label.grid(row=0, column=0, padx=10, pady=(10, 15), sticky="n")

        self.input_card = ttkb.LabelFrame(parent_frame, text=_("输入数据"), bootstyle="secondary")
        self.input_card.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        self.input_card.grid_columnconfigure(1, weight=1)

        self.assembly_id_label = ttk.Label(self.input_card, text=_("基因组版本:"), font=self.app.app_font_bold)
        self.assembly_id_label.grid(row=0, column=0, sticky="w", padx=(10, 5), pady=10)
        self.assembly_dropdown = ttkb.OptionMenu(self.input_card, self.assembly_id_var, _("加载中..."),
                                                 bootstyle="info")
        self.assembly_dropdown.grid(row=0, column=1, sticky="ew", padx=10, pady=10)

        self.gene_list_label = ttk.Label(self.input_card, text=_("基因ID列表 (或基因ID,Log2FC):"),
                                         font=self.app.app_font_bold)
        self.gene_list_label.grid(row=1, column=0, sticky="nw", padx=(10, 5), pady=10)

        text_bg = self.app.style.lookup('TFrame', 'background')
        text_fg = self.app.style.lookup('TLabel', 'foreground')
        self.gene_input_text = tk.Text(self.input_card, height=10, font=self.app.app_font_mono, wrap="word",
                                       relief="flat", background=text_bg, foreground=text_fg, insertbackground=text_fg)
        self.gene_input_text.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10))
        self.app.ui_manager.add_placeholder(self.gene_input_text,
                                            self.app.placeholders.get("enrichment_genes_input", "..."))
        self.gene_input_text.bind("<FocusIn>", lambda e: self.app.ui_manager._handle_focus_in(e, self.gene_input_text,
                                                                                              "enrichment_genes_input"))
        self.gene_input_text.bind("<FocusOut>", lambda e: self.app.ui_manager._handle_focus_out(e, self.gene_input_text,
                                                                                                "enrichment_genes_input"))

        self.format_card = ttkb.LabelFrame(parent_frame, text=_("输入格式与分析类型"), bootstyle="secondary")
        self.format_card.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        self.format_card.grid_columnconfigure(1, weight=1)

        self.input_format_label = ttk.Label(self.format_card, text=_("输入格式:"), font=self.app.app_font_bold)
        self.input_format_label.grid(row=0, column=0, padx=15, pady=5, sticky="w")
        input_format_frame = ttk.Frame(self.format_card)
        input_format_frame.grid(row=0, column=1, sticky="ew", padx=10, pady=5)
        self.has_header_check = ttkb.Checkbutton(input_format_frame, text=_("包含表头"), variable=self.has_header_var,
                                                 bootstyle="round-toggle")
        self.has_header_check.pack(side="left", padx=(0, 15))
        self.has_log2fc_check = ttkb.Checkbutton(input_format_frame, text=_("包含Log2FC"), variable=self.has_log2fc_var,
                                                 bootstyle="round-toggle")
        self.has_log2fc_check.pack(side="left")

        self.analysis_type_label = ttk.Label(self.format_card, text=_("分析类型:"), font=self.app.app_font_bold)
        self.analysis_type_label.grid(row=1, column=0, padx=15, pady=5, sticky="w")
        radio_frame = ttk.Frame(self.format_card)
        radio_frame.grid(row=1, column=1, sticky="ew", padx=10, pady=5)
        self.go_radio = ttkb.Radiobutton(radio_frame, text="GO", variable=self.analysis_type_var, value="go",
                                         bootstyle="toolbutton-success")
        self.go_radio.pack(side="left", padx=5)
        self.kegg_radio = ttkb.Radiobutton(radio_frame, text="KEGG", variable=self.analysis_type_var, value="kegg",
                                           bootstyle="toolbutton-success")
        self.kegg_radio.pack(side="left", padx=5)

        self.collapse_check = ttkb.Checkbutton(self.format_card, text=_("合并转录本到基因"),
                                               variable=self.collapse_transcripts_var, bootstyle="round-toggle")
        self.collapse_check.grid(row=2, column=0, columnspan=2, sticky="w", padx=15, pady=5)
        self.collapse_note_label = ttkb.Label(self.format_card, text=_(
            "开启后，将忽略基因ID后的mRNA编号 (如 .1, .2)，统一视为基因ID。\n例如: Ghir_D02G021470.1 / Ghir_D02G021470.2 将统一视为 Ghir_D02G021470。"),
                                              font=self.app.app_comment_font, bootstyle="info")
        self.collapse_note_label.grid(row=3, column=0, columnspan=2, sticky="w", padx=15, pady=(0, 5))

        self.plot_config_card = ttkb.LabelFrame(parent_frame, text=_("绘图设置"), bootstyle="secondary")
        self.plot_config_card.grid(row=4, column=0, sticky="ew", padx=10, pady=5)
        self.plot_config_card.grid_columnconfigure(1, weight=1)

        self.plot_type_label = ttk.Label(self.plot_config_card, text=_("绘图类型:"), font=self.app.app_font_bold)
        self.plot_type_label.grid(row=0, column=0, padx=15, pady=5, sticky="w")
        plot_type_frame = ttk.Frame(self.plot_config_card)
        plot_type_frame.grid(row=0, column=1, sticky="ew", padx=10, pady=5)
        self.bubble_check = ttkb.Checkbutton(plot_type_frame, text=_("气泡图"), variable=self.bubble_plot_var,
                                             bootstyle="round-toggle")
        self.bubble_check.pack(side="left", padx=(0, 15))
        self.bar_check = ttkb.Checkbutton(plot_type_frame, text=_("条形图"), variable=self.bar_plot_var,
                                          bootstyle="round-toggle")
        self.bar_check.pack(side="left", padx=(0, 15))
        self.upset_check = ttkb.Checkbutton(plot_type_frame, text=_("Upset图"), variable=self.upset_plot_var,
                                            bootstyle="round-toggle")
        self.upset_check.pack(side="left", padx=(0, 15))
        self.cnet_check = ttkb.Checkbutton(plot_type_frame, text=_("网络图(Cnet)"), variable=self.cnet_plot_var,
                                           bootstyle="round-toggle")
        self.cnet_check.pack(side="left")

        self.top_n_label = ttk.Label(self.plot_config_card, text=_("显示前N项:"), font=self.app.app_font_bold)
        self.top_n_label.grid(row=1, column=0, padx=15, pady=5, sticky="w")
        self.top_n_entry = ttk.Entry(self.plot_config_card, textvariable=self.top_n_var, width=10)
        self.top_n_entry.grid(row=1, column=1, sticky="w", padx=10, pady=5)

        self.sort_by_label = ttk.Label(self.plot_config_card, text=_("排序依据:"), font=self.app.app_font_bold)
        self.sort_by_label.grid(row=2, column=0, padx=15, pady=5, sticky="w")
        self.sort_by_dropdown = ttkb.OptionMenu(self.plot_config_card, self.sort_by_var, "FDR", "FDR", "PValue",
                                                "FoldEnrichment", bootstyle="info")
        self.sort_by_dropdown.grid(row=2, column=1, sticky="ew", padx=10, pady=5)

        self.show_title_check = ttkb.Checkbutton(self.plot_config_card, text=_("显示图表标题"),
                                                 variable=self.show_title_var, bootstyle="round-toggle")
        self.show_title_check.grid(row=3, column=0, columnspan=2, sticky="w", padx=15, pady=5)

        self.width_label = ttk.Label(self.plot_config_card, text=_("图表宽度 (英寸):"), font=self.app.app_font_bold)
        self.width_label.grid(row=4, column=0, padx=15, pady=5, sticky="w")
        self.width_entry = ttk.Entry(self.plot_config_card, textvariable=self.width_var, width=10)
        self.width_entry.grid(row=4, column=1, sticky="w", padx=10, pady=5)

        self.height_label = ttk.Label(self.plot_config_card, text=_("图表高度 (英寸):"), font=self.app.app_font_bold)
        self.height_label.grid(row=5, column=0, padx=15, pady=5, sticky="w")
        self.height_entry = ttk.Entry(self.plot_config_card, textvariable=self.height_var, width=10)
        self.height_entry.grid(row=5, column=1, sticky="w", padx=10, pady=5)

        self.file_format_label = ttk.Label(self.plot_config_card, text=_("文件格式:"), font=self.app.app_font_bold)
        self.file_format_label.grid(row=6, column=0, padx=15, pady=5, sticky="w")
        self.file_format_dropdown = ttkb.OptionMenu(self.plot_config_card, self.file_format_var, "png", "png", "svg",
                                                    "pdf", "jpeg", bootstyle="info")
        self.file_format_dropdown.grid(row=6, column=1, sticky="ew", padx=10, pady=5)

        self.output_dir_card = ttkb.LabelFrame(parent_frame, text=_("输出设置"), bootstyle="secondary")
        self.output_dir_card.grid(row=5, column=0, sticky="ew", padx=10, pady=5)
        self.output_dir_card.grid_columnconfigure(1, weight=1)

        self.output_dir_label = ttk.Label(self.output_dir_card, text=_("输出目录:"), font=self.app.app_font_bold)
        self.output_dir_label.grid(row=0, column=0, padx=15, pady=5, sticky="w")
        self.enrichment_output_dir_entry = ttk.Entry(self.output_dir_card)
        self.enrichment_output_dir_entry.grid(row=0, column=1, sticky="ew", padx=(10, 5), pady=5)
        self.browse_button = ttkb.Button(self.output_dir_card, text=_("浏览..."), width=12,
                                         command=lambda: self.app.event_handler._browse_directory(
                                             self.enrichment_output_dir_entry), bootstyle="info-outline")
        self.browse_button.grid(row=0, column=2, padx=(0, 10), pady=5)

    def retranslate_ui(self, translator: Callable[[str], str]):
        # --- 更新所有静态文本 ---
        self.title_label.config(text=translator("富集分析与绘图"))
        self.input_card.config(text=translator("输入数据"))
        self.assembly_id_label.config(text=translator("基因组版本:"))
        self.gene_list_label.config(text=translator("基因ID列表 (或基因ID,Log2FC):"))
        self.format_card.config(text=translator("输入格式与分析类型"))
        self.input_format_label.config(text=translator("输入格式:"))
        self.has_header_check.config(text=translator("包含表头"))
        self.has_log2fc_check.config(text=translator("包含Log2FC"))
        self.analysis_type_label.config(text=translator("分析类型:"))
        self.collapse_check.config(text=translator("合并转录本到基因"))
        self.collapse_note_label.config(text=translator(
            "开启后，将忽略基因ID后的mRNA编号 (如 .1, .2)，统一视为基因ID。\n例如: Ghir_D02G021470.1 / Ghir_D02G021470.2 将统一视为 Ghir_D02G021470。"))
        self.plot_config_card.configure(text=translator("绘图设置"))
        self.plot_type_label.configure(text=translator("绘图类型:"))
        self.bubble_check.configure(text=translator("气泡图"))
        self.bar_check.configure(text=translator("条形图"))
        self.upset_check.configure(text=translator("Upset图"))
        self.cnet_check.configure(text=translator("网络图(Cnet)"))
        self.top_n_label.configure(text=translator("显示前N项:"))
        self.sort_by_label.configure(text=translator("排序依据:"))
        self.show_title_check.configure(text=translator("显示图表标题"))
        self.width_label.configure(text=translator("图表宽度 (英寸):"))
        self.height_label.configure(text=translator("图表高度 (英寸):"))
        self.file_format_label.configure(text=translator("文件格式:"))
        self.output_dir_card.configure(text=translator("输出设置"))
        self.output_dir_label.configure(text=translator("输出目录:"))
        self.browse_button.configure(text=translator("浏览..."))

        if self.action_button:
            self.action_button.configure(text=translator("开始富集分析"))

            # 【最终修正】直接调用 UIManager 的方法来设置占位符
            # UIManager 的 _update_placeholders 已经更新了 self.app.placeholders 字典
        new_placeholder_text = self.app.placeholders.get("enrichment_genes_input", "")
        self.app.ui_manager.add_placeholder(self.gene_input_text, new_placeholder_text)

        self.app.ui_manager.refresh_single_placeholder(self.gene_input_text, "enrichment_genes_input")

    def refresh_placeholders(self):
        """【新增】此方法现在由UIManager统一调用，以确保占位符被刷新。"""
        if hasattr(self, 'gene_input_text') and self.gene_input_text:
            new_placeholder_text = self.app.placeholders.get("enrichment_genes_input", "")
            self.app.ui_manager.add_placeholder(self.gene_input_text, new_placeholder_text)


    def update_assembly_dropdowns(self, assembly_ids: List[str]):
        self.app.ui_manager.update_option_menu(self.assembly_dropdown, self.assembly_id_var, assembly_ids,
                                               _("无可用基因组"))

    def update_from_config(self):
        self.update_assembly_dropdowns(
            list(self.app.genome_sources_data.keys()) if self.app.genome_sources_data else [])
        default_dir = os.path.join(os.getcwd(), "enrichment_results")
        self.enrichment_output_dir_entry.delete(0, tk.END)
        self.enrichment_output_dir_entry.insert(0, default_dir)
        self.update_button_state(self.app.active_task_name is not None, self.app.current_config is not None)

    def start_enrichment_task(self):
        # ... [此方法的逻辑与上一版相同] ...
        if not self.app.current_config:
            self.app.ui_manager.show_error_message(_("错误"), _("请先加载配置文件。"));
            return

        gene_ids_text = self.gene_input_text.get("1.0", tk.END).strip()
        is_placeholder = (gene_ids_text == self.app.placeholders.get("enrichment_genes_input", ""))
        lines = [] if is_placeholder else gene_ids_text.splitlines()

        if not lines:
            self.app.ui_manager.show_error_message(_("输入缺失"), _("请输入要分析的基因ID。"));
            return

        assembly_id = self.assembly_id_var.get()
        if not assembly_id or assembly_id in [_("加载中..."), _("无可用基因组")]:
            self.app.ui_manager.show_error_message(_("输入缺失"), _("请选择一个基因组版本。"));
            return

        output_dir = self.enrichment_output_dir_entry.get().strip()
        if not output_dir:
            self.app.ui_manager.show_error_message(_("输入缺失"), _("请选择图表的输出目录。"));
            return

        plot_types = [name for var, name in
                      [(self.bubble_plot_var, 'bubble'), (self.bar_plot_var, 'bar'), (self.upset_plot_var, 'upset'),
                       (self.cnet_plot_var, 'cnet')] if var.get()]
        if not plot_types:
            self.app.ui_manager.show_error_message(_("输入缺失"), _("请至少选择一种图表类型。"));
            return

        study_gene_ids = []
        gene_log2fc_map = {} if self.has_log2fc_var.get() else None

        try:
            effective_lines = lines[1:] if self.has_header_var.get() and len(lines) > 1 else lines
            if self.has_log2fc_var.get():
                for i, line in enumerate(effective_lines):
                    if not line.strip(): continue
                    parts = re.split(r'[\s\t,;]+', line.strip())
                    if len(parts) >= 2:
                        gene_id, log2fc_str = parts[0], parts[1]
                        try:
                            gene_log2fc_map[gene_id] = float(log2fc_str)
                            study_gene_ids.append(gene_id)
                        except ValueError:
                            raise ValueError(_("第 {i + 1} 行Log2FC值无效:").format(i=i) + f" '{log2fc_str}'")
                    else:
                        raise ValueError(_("第 {i + 1} 行格式错误，需要两列 (基因, Log2FC):").format(i=i) + f" '{line}'")
            else:
                for line in effective_lines:
                    if not line.strip(): continue
                    parts = re.split(r'[\s\t,;]+', line.strip())
                    study_gene_ids.extend([p for p in parts if p])
        except ValueError as e:
            self.app.ui_manager.show_error_message(_("输入格式错误"), str(e));
            return

        study_gene_ids = sorted(list(set(study_gene_ids)))
        if not study_gene_ids:
            self.app.ui_manager.show_error_message(_("输入缺失"), _("解析后未发现有效基因ID。"));
            return

        task_kwargs = {
            'config': self.app.current_config, 'assembly_id': assembly_id,
            'study_gene_ids': study_gene_ids, 'analysis_type': self.analysis_type_var.get(),
            'plot_types': plot_types, 'output_dir': output_dir,
            'gene_log2fc_map': gene_log2fc_map, 'top_n': self.top_n_var.get(),
            'sort_by': self.sort_by_var.get(), 'show_title': self.show_title_var.get(),
            'width': self.width_var.get(), 'height': self.height_var.get(),
            'file_format': self.file_format_var.get(), 'collapse_transcripts': self.collapse_transcripts_var.get()
        }

        self.app.event_handler._start_task(
            task_name=_("{} 富集分析").format(self.analysis_type_var.get().upper()),
            target_func=run_enrichment_pipeline, kwargs=task_kwargs
        )