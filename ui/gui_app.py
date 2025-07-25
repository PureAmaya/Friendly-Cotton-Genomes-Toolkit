﻿# 文件路径: ui/gui_app.py
# 最终完整、修正、无功能遗漏版

import logging
import os
import queue
import sys
import threading
import traceback
from queue import Queue
from tkinter import font as tkfont
from typing import Optional, Dict, Any, Callable
import tkinter as tk
import ttkbootstrap as ttkb

try:
    from ctypes import windll, byref, sizeof, c_int
except ImportError:
    windll = None

from cotton_toolkit.config.loader import save_config, load_config
from cotton_toolkit.config.models import MainConfig
from cotton_toolkit.utils.localization import setup_localization
from cotton_toolkit.utils.logger import setup_global_logger
from ui.event_handler import EventHandler
from ui.ui_manager import UIManager

try:
    from builtins import _
except ImportError:
    _ = lambda s: str(s)


class CottonToolkitApp(ttkb.Window):
    LANG_CODE_TO_NAME = {"zh-hans": "简体中文", "zh-hant": "繁體中文", "en": "English", "ja": "日本語"}
    LANG_NAME_TO_CODE = {v: k for k, v in LANG_CODE_TO_NAME.items()}
    DARK_THEMES = ["darkly", "cyborg", "solar", "superhero", "vapor"]

    @property
    def AI_PROVIDERS(self):
        return {"google": {"name": "Google Gemini"}, "openai": {"name": "OpenAI"},
                "deepseek": {"name": "DeepSeek (深度求索)"}, "qwen": {"name": "Qwen (通义千问)"},
                "siliconflow": {"name": "SiliconFlow (硅基流动)"}, "grok": {"name": "Grok (xAI)"},
                "openai_compatible": {"name": self._("通用OpenAI兼容接口")}}

    TOOL_TAB_ORDER = [
        "download", "annotation", "enrichment", "xlsx_to_csv", "genome_identifier",
        "homology", "locus_conversion", "gff_query", "ai_assistant"
    ]

    @property
    def TAB_TITLE_KEYS(self):
        return {
            "download": _("数据下载"), "annotation": _("功能注释"), "enrichment": _("富集分析与绘图"),
            "xlsx_to_csv": _("XLSX转CSV"), "genome_identifier": _("基因组鉴定"), "homology": _("同源转换"),
            "locus_conversion": _("位点转换"), "gff_query": _("GFF查询"), "ai_assistant": _("AI助手"),
        }



    def __init__(self, translator: Callable[[str], str]):
        super().__init__(themename='flatly')

        self._ = translator
        self.logger = logging.getLogger(__name__)

        # --- 使用新的 resource_path 函数定义所有资源路径 ---
        self.app_icon_path: Optional[str] = self.resource_path("logo.ico")
        self.logo_image_path: Optional[str] = self.resource_path("logo.png")
        self.home_icon_path: Optional[str] = self.resource_path("home.png")
        self.tools_icon_path: Optional[str] = self.resource_path("tools.png")
        self.settings_icon_path: Optional[str] = self.resource_path("settings.png")

        self._patch_all_toplevels()

        self.title_text_key = "Friendly Cotton Genomes Toolkit - FCGT"
        self.title(self._(self.title_text_key))
        self.geometry("1500x900")
        self.minsize(1400, 800)

        # --- 直接在这里设置主窗口图标 ---
        try:
            if self.app_icon_path and os.path.exists(self.app_icon_path):
                self.iconbitmap(self.app_icon_path)
                self.logger.info(f"成功加载并设置应用图标: {self.app_icon_path}")
            else:
                self.logger.warning(f"应用图标文件未找到，请检查路径: {self.app_icon_path}")
        except Exception as e:
            self.logger.warning(f"加载主窗口图标失败: {e}")

        # --- 原有的 __init__ 其他代码 ---
        self.bind("<FocusIn>", self._on_first_focus, add='+')
        self._setup_fonts()

        self.placeholder_color = (self.style.colors.secondary, self.style.colors.secondary)
        self.default_text_color = self.style.lookup('TLabel', 'foreground')
        self.secondary_text_color = self.style.lookup('TLabel', 'foreground')
        self.placeholders = {
            "homology_genes": self._("粘贴基因ID，每行一个..."),
            "gff_genes":  self._("粘贴基因ID，每行一个..."),
            "gff_region":  self._("例如: A01:1-100000"),
            "genes_input":  self._("在此处粘贴要注释的基因ID，每行一个"),
            "enrichment_genes_input": self._("在此处粘贴用于富集分析的基因ID，每行一个。\n如果包含Log2FC，格式为：基因ID\tLog2FC\n（注意：使用制表符分隔，从Excel直接复制的列即为制表符分隔）"),
            "custom_prompt": self._("在此处输入您的自定义提示词模板，必须包含 {text} 占位符..."),
            "default_prompt_empty": self._("Default prompt is empty, please set it in the configuration editor.")
        }

        self.home_widgets: Dict[str, Any] = {}
        self.editor_widgets: Dict[str, Any] = {}
        self.translatable_widgets = {}
        self.current_config: Optional[MainConfig] = None
        self.config_path: Optional[str] = None
        self.genome_sources_data = {}
        self.log_queue = Queue()
        self.message_queue = Queue()
        self.active_task_name: Optional[str] = None
        self.cancel_current_task_event = threading.Event()
        self.ui_settings = {}
        self.tool_tab_instances = {}
        self.tool_buttons = {}
        self.latest_log_message_var = tk.StringVar(value="")
        self.editor_canvas: Optional[tk.Canvas] = None
        self.editor_ui_built = False
        self.log_viewer_visible = False
        self.config_path_display_var = tk.StringVar()
        self.selected_language_var = tk.StringVar()
        self.selected_appearance_var = tk.StringVar()

        self.ui_manager = UIManager(self, translator=self._)
        self.event_handler = EventHandler(self)

        # 注意：这里不再调用 _create_image_assets()
        setup_global_logger(log_level_str="INFO", log_queue=self.log_queue)

        self.ui_manager.load_settings()
        self.ui_manager.setup_initial_ui()

        self.event_handler.start_app_async_startup()
        self.check_queue_periodic()
        self.protocol("WM_DELETE_WINDOW", self.event_handler.on_closing)


    def resource_path(self,relative_path:str):
        """
        获取资源的绝对路径。
        兼容开发模式、Nuitka --standalone 模式和 --onefile 模式。
        """
        try:
            # Nuitka --onefile 模式下，sys._MEIPASS 是解压后的临时路径
            base_path = sys._MEIPASS
        except Exception:
            # 开发模式或 Nuitka --standalone 模式
            # os.path.abspath(".") 返回的是 main.py 所在的目录
            base_path = os.path.abspath(".")

        # 路径拼接，请确保您的资源都放在 ui/assets/ 目录下
        return os.path.join(base_path, "ui", "assets", relative_path)

    def _patch_all_toplevels(self):
        app_instance = self

        def apply_customizations(toplevel_self):
            # 1. 设置窗口图标 (这部分是安全的，保持不变)
            if app_instance.app_icon_path:
                try:
                    toplevel_self.iconbitmap(app_instance.app_icon_path)
                except tk.TclError:
                    pass  # 如果窗口不支持图标，则静默失败

            # 2. 【核心修改】使用更安全的方式刷新标题栏
            # 我们不再使用 withdraw/deiconify，而是让Tkinter在下一个空闲周期自行处理更新
            def _safer_refresh_task():
                # 直接应用颜色配置
                app_instance.configure_title_bar_color(toplevel_self)
                # 调用 update_idletasks() 来处理所有待办的UI更新，这比 withdraw() 安全得多
                toplevel_self.update_idletasks()

            # 同样使用 after，但执行的任务是安全的
            toplevel_self.after(10, _safer_refresh_task)

        # 保持原有的补丁逻辑不变
        original_ttkb_init = ttkb.Toplevel.__init__

        def new_ttkb_init(toplevel_self, *args, **kwargs):
            original_ttkb_init(toplevel_self, *args, **kwargs)
            apply_customizations(toplevel_self)

        ttkb.Toplevel.__init__ = new_ttkb_init

        original_tk_init = tk.Toplevel.__init__

        def new_tk_init(toplevel_self, *args, **kwargs):
            original_tk_init(toplevel_self, *args, **kwargs)
            apply_customizations(toplevel_self)

        tk.Toplevel.__init__ = new_tk_init

    def configure_title_bar_color(self, window_obj):
        if sys.platform != "win32" or windll is None: return
        try:
            is_dark = self.style.theme.type == 'dark'
            hwnd = windll.user32.GetParent(window_obj.winfo_id())
            if not hwnd: return
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            value = c_int(1 if is_dark else 0)
            windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, byref(value), sizeof(value))
        except Exception as e:
            self.logger.warning(f"为窗口 {window_obj} 配置标题栏颜色时出错: {e}")

    def _on_first_focus(self, event):
        self.unbind("<FocusIn>")
        self.logger.info("Window has gained focus for the first time. Applying initial theme.")
        self.ui_manager.apply_initial_theme()

    def apply_theme_and_update_dependencies(self, theme_name: str):
        try:
            self.style.theme_use(theme_name)
            self._setup_fonts()
            self.default_text_color = self.style.lookup('TLabel', 'foreground')
            if hasattr(self, 'ui_manager'): self.ui_manager.update_sidebar_style()
            if hasattr(self.ui_manager, '_update_log_tag_colors'): self.ui_manager._update_log_tag_colors()
            self.after_idle(self.refresh_window_visuals)
        except Exception as e:
            self.logger.error(f"应用主题并刷新时出错: {e}")

    def refresh_window_visuals(self):
        self.logger.debug("正在强制刷新窗口视觉效果...")
        self.configure_title_bar_color(self)
        self.withdraw()
        self.deiconify()
        self.logger.debug(self._("刷新完成。"))


    def _create_editor_widgets(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        row_counter = 0

        def get_row():
            nonlocal row_counter
            r = row_counter
            row_counter += 1
            return r

        section_1_title = ttkb.Label(parent, text=f"◇ {self._('通用设置')} ◇", font=self.app_subtitle_font, bootstyle="primary")
        section_1_title.grid(row=get_row(), column=0, pady=(25, 10), sticky="w", padx=5)
        self.translatable_widgets[section_1_title] = "通用设置"

        c1 = ttkb.Frame(parent); c1.grid(row=get_row(), column=0, sticky="ew", pady=4, padx=5); c1.grid_columnconfigure(1, weight=1)
        lbl1 = ttkb.Label(c1, text=self._("日志级别")); lbl1.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl1] = "日志级别"
        self.general_log_level_var = tk.StringVar()
        self.general_log_level_menu = ttkb.OptionMenu(c1, self.general_log_level_var, "INFO", *["DEBUG", "INFO", "WARNING", "ERROR"], bootstyle='info-outline')
        self.general_log_level_menu.grid(row=0, column=1, sticky="ew", padx=5)
        tip1 = ttkb.Label(c1, text=self._("设置应用程序的日志详细程度。"), font=self.app_comment_font, bootstyle="secondary"); tip1.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip1] = "设置应用程序的日志详细程度。"

        c2 = ttkb.Frame(parent); c2.grid(row=get_row(), column=0, sticky="ew", pady=2, padx=5); c2.grid_columnconfigure(1, weight=1)
        lbl2 = ttkb.Label(c2, text=self._("HTTP代理")); lbl2.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl2] = "HTTP代理"
        self.proxy_http_entry = ttkb.Entry(c2); self.proxy_http_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        tip2 = ttkb.Label(c2, text=self._("例如: http://127.0.0.1:7890"), font=self.app_comment_font, bootstyle="secondary"); tip2.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip2] = "例如: http://127.0.0.1:7890"

        c3 = ttkb.Frame(parent); c3.grid(row=get_row(), column=0, sticky="ew", pady=2, padx=5); c3.grid_columnconfigure(1, weight=1)
        lbl3 = ttkb.Label(c3, text=self._("HTTPS代理")); lbl3.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl3] = "HTTPS代理"
        self.proxy_https_entry = ttkb.Entry(c3); self.proxy_https_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        tip3 = ttkb.Label(c3, text=self._("例如: https://127.0.0.1:7890"), font=self.app_comment_font, bootstyle="secondary"); tip3.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip3] = "例如: https://127.0.0.1:7890"

        proxy_button_frame = ttkb.Frame(parent); proxy_button_frame.grid(row=get_row(), column=0, sticky="e", padx=5, pady=5)
        self.test_proxy_button = ttkb.Button(proxy_button_frame, text=self._("测试代理连接"), command=self.event_handler.test_proxy_connection, bootstyle="primary-outline"); self.test_proxy_button.pack()
        self.translatable_widgets[self.test_proxy_button] = "测试代理连接"

        section_2_title = ttkb.Label(parent, text=f"◇ {self._('数据下载器配置')} ◇", font=self.app_subtitle_font, bootstyle="primary")
        section_2_title.grid(row=get_row(), column=0, pady=(25, 10), sticky="w", padx=5)
        self.translatable_widgets[section_2_title] = "数据下载器配置"

        c4 = ttkb.Frame(parent); c4.grid(row=get_row(), column=0, sticky="ew", pady=2, padx=5); c4.grid_columnconfigure(1, weight=1)
        lbl4 = ttkb.Label(c4, text=self._("基因组源文件")); lbl4.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl4] = "基因组源文件"
        self.downloader_sources_file_entry = ttkb.Entry(c4); self.downloader_sources_file_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        tip4 = ttkb.Label(c4, text=self._("定义基因组下载链接的YAML文件。"), font=self.app_comment_font, bootstyle="secondary"); tip4.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip4] = "定义基因组下载链接的YAML文件。"

        c5 = ttkb.Frame(parent); c5.grid(row=get_row(), column=0, sticky="ew", pady=2, padx=5); c5.grid_columnconfigure(1, weight=1)
        lbl5 = ttkb.Label(c5, text=self._("下载输出根目录")); lbl5.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl5] = "下载输出根目录"
        self.downloader_output_dir_entry = ttkb.Entry(c5); self.downloader_output_dir_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        tip5 = ttkb.Label(c5, text=self._("所有下载文件存放的基准目录。"), font=self.app_comment_font, bootstyle="secondary"); tip5.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip5] = "所有下载文件存放的基准目录。"

        c6 = ttkb.Frame(parent); c6.grid(row=get_row(), column=0, sticky="ew", pady=4, padx=5); c6.grid_columnconfigure(1, weight=1)
        lbl6 = ttkb.Label(c6, text=self._("强制重新下载")); lbl6.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl6] = "强制重新下载"
        self.downloader_force_download_var = tk.BooleanVar()
        self.downloader_force_download_switch = ttkb.Checkbutton(c6, variable=self.downloader_force_download_var, bootstyle="round-toggle"); self.downloader_force_download_switch.grid(row=0, column=1, sticky="w", padx=5)
        tip6 = ttkb.Label(c6, text=self._("如果文件已存在，是否覆盖。"), font=self.app_comment_font, bootstyle="secondary"); tip6.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip6] = "如果文件已存在，是否覆盖。"

        c7 = ttkb.Frame(parent); c7.grid(row=get_row(), column=0, sticky="ew", pady=2, padx=5); c7.grid_columnconfigure(1, weight=1)
        lbl7 = ttkb.Label(c7, text=self._("最大下载线程数")); lbl7.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl7] = "最大下载线程数"
        self.downloader_max_workers_entry = ttkb.Entry(c7); self.downloader_max_workers_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        tip7 = ttkb.Label(c7, text=self._("多线程下载时使用的最大线程数。"), font=self.app_comment_font, bootstyle="secondary"); tip7.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip7] = "多线程下载时使用的最大线程数。"

        c8 = ttkb.Frame(parent); c8.grid(row=get_row(), column=0, sticky="ew", pady=4, padx=5); c8.grid_columnconfigure(1, weight=1)
        lbl8 = ttkb.Label(c8, text=self._("为下载使用代理")); lbl8.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl8] = "为下载使用代理"
        self.downloader_use_proxy_var = tk.BooleanVar()
        self.downloader_use_proxy_switch = ttkb.Checkbutton(c8, variable=self.downloader_use_proxy_var, bootstyle="round-toggle"); self.downloader_use_proxy_switch.grid(row=0, column=1, sticky="w", padx=5)
        tip8 = ttkb.Label(c8, text=self._("是否为数据下载启用代理。"), font=self.app_comment_font, bootstyle="secondary"); tip8.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip8] = "是否为数据下载启用代理。"

        section_3_title = ttkb.Label(parent, text=f"◇ {self._('AI 服务配置')} ◇", font=self.app_subtitle_font, bootstyle="primary")
        section_3_title.grid(row=get_row(), column=0, pady=(25, 10), sticky="w", padx=5)
        self.translatable_widgets[section_3_title] = "AI 服务配置"

        c9 = ttkb.Frame(parent); c9.grid(row=get_row(), column=0, sticky="ew", pady=4, padx=5); c9.grid_columnconfigure(1, weight=1)
        lbl9 = ttkb.Label(c9, text=self._("默认AI服务商")); lbl9.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl9] = "默认AI服务商"
        self.ai_default_provider_var = tk.StringVar()
        provider_names = [p['name'] for p in self.AI_PROVIDERS.values()]
        self.ai_default_provider_menu = ttkb.OptionMenu(c9, self.ai_default_provider_var, provider_names[0], *provider_names, bootstyle='info-outline')
        self.ai_default_provider_menu.grid(row=0, column=1, sticky="ew", padx=5)
        tip9 = ttkb.Label(c9, text=self._("选择默认使用的AI模型提供商。"), font=self.app_comment_font, bootstyle="secondary"); tip9.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip9] = "选择默认使用的AI模型提供商。"

        c10 = ttkb.Frame(parent); c10.grid(row=get_row(), column=0, sticky="ew", pady=2, padx=5); c10.grid_columnconfigure(1, weight=1)
        lbl10 = ttkb.Label(c10, text=self._("最大并行AI任务数")); lbl10.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl10] = "最大并行AI任务数"
        self.batch_ai_max_workers_entry = ttkb.Entry(c10); self.batch_ai_max_workers_entry.grid(row=0, column=1, sticky="ew", padx=5, pady=2)
        tip10 = ttkb.Label(c10, text=self._("执行AI任务时并行处理的最大数量，建议根据CPU核心数和网络情况设置。"), font=self.app_comment_font, bootstyle="secondary"); tip10.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip10] = "执行AI任务时并行处理的最大数量，建议根据CPU核心数和网络情况设置。"

        c11 = ttkb.Frame(parent); c11.grid(row=get_row(), column=0, sticky="ew", pady=4, padx=5); c11.grid_columnconfigure(1, weight=1)
        lbl11 = ttkb.Label(c11, text=self._("为AI服务使用代理")); lbl11.grid(row=0, column=0, sticky="w", padx=(5, 10), pady=2)
        self.translatable_widgets[lbl11] = "为AI服务使用代理"
        self.ai_use_proxy_var = tk.BooleanVar()
        self.ai_use_proxy_switch = ttkb.Checkbutton(c11, variable=self.ai_use_proxy_var, bootstyle="round-toggle"); self.ai_use_proxy_switch.grid(row=0, column=1, sticky="w", padx=5)
        tip11 = ttkb.Label(c11, text=self._("是否为连接AI模型API启用代理。"), font=self.app_comment_font, bootstyle="secondary"); tip11.grid(row=1, column=1, sticky="w", padx=5)
        self.translatable_widgets[tip11] = "是否为连接AI模型API启用代理。"

        for p_key, p_info in self.AI_PROVIDERS.items():
            card = ttkb.LabelFrame(parent, text=p_info['name'], bootstyle="secondary")
            card.grid(row=get_row(), column=0, sticky="ew", pady=8, padx=5)
            card.grid_columnconfigure(1, weight=1)
            safe_key = p_key.replace('-', '_')
            lbl_apikey = ttkb.Label(card, text="API Key"); lbl_apikey.grid(row=0, column=0, sticky="w", padx=10, pady=5)
            self.translatable_widgets[lbl_apikey] = "API Key"
            apikey_entry = ttkb.Entry(card); apikey_entry.grid(row=0, column=1, sticky="ew", pady=5, padx=5)
            setattr(self, f"ai_{safe_key}_apikey_entry", apikey_entry)
            lbl_model = ttkb.Label(card, text="Model"); lbl_model.grid(row=1, column=0, sticky="w", padx=10, pady=5)
            self.translatable_widgets[lbl_model] = "Model"
            model_frame = ttkb.Frame(card); model_frame.grid(row=1, column=1, sticky="ew", pady=5, padx=5); model_frame.grid_columnconfigure(0, weight=1)
            model_var = tk.StringVar(value=self._("点击刷新获取列表"))
            model_dropdown = ttkb.OptionMenu(model_frame, model_var, self._("点击刷新..."), bootstyle="info"); model_dropdown.configure(state="disabled"); model_dropdown.grid(row=0, column=0, sticky="ew")
            setattr(self, f"ai_{safe_key}_model_selector", (model_dropdown, model_var))
            button_frame = ttkb.Frame(model_frame); button_frame.grid(row=0, column=1, padx=(10, 0))
            btn_refresh = ttkb.Button(button_frame, text=self._("刷新"), width=8, command=lambda pk=p_key: self.event_handler._gui_fetch_ai_models(pk, use_proxy=False), bootstyle='outline'); btn_refresh.pack(side="left")
            self.translatable_widgets[btn_refresh] = "刷新"
            btn_proxy_refresh = ttkb.Button(button_frame, text=self._("代理刷新"), width=10, command=lambda pk=p_key: self.event_handler._gui_fetch_ai_models(pk, use_proxy=True), bootstyle='info-outline'); btn_proxy_refresh.pack(side="left", padx=(5, 0))
            self.translatable_widgets[btn_proxy_refresh] = "代理刷新"
            lbl_baseurl = ttkb.Label(card, text="Base URL"); lbl_baseurl.grid(row=2, column=0, sticky="w", padx=10, pady=5)
            self.translatable_widgets[lbl_baseurl] = "Base URL"
            baseurl_entry = ttkb.Entry(card); baseurl_entry.grid(row=2, column=1, sticky="ew", pady=5, padx=5)
            setattr(self, f"ai_{safe_key}_baseurl_entry", baseurl_entry)

        section_4_title = ttkb.Label(parent, text=f"◇ {self._('AI 提示词模板')} ◇", font=self.app_subtitle_font, bootstyle="primary")
        section_4_title.grid(row=get_row(), column=0, pady=(25, 10), sticky="w", padx=5)
        self.translatable_widgets[section_4_title] = "AI 提示词模板"

        f_trans = ttkb.Frame(parent); f_trans.grid(row=get_row(), column=0, sticky="ew", pady=8, padx=5); f_trans.grid_columnconfigure(1, weight=1)
        lbl_trans = ttkb.Label(f_trans, text=self._("翻译提示词")); lbl_trans.grid(row=0, column=0, sticky="nw", padx=(5, 10))
        self.translatable_widgets[lbl_trans] = "翻译提示词"
        bg_t, fg_t = self.style.lookup('TFrame', 'background'), self.style.lookup('TLabel', 'foreground')
        self.ai_translation_prompt_textbox = tk.Text(f_trans, height=7, font=self.app_font_mono, wrap="word", relief="flat", background=bg_t, foreground=fg_t, insertbackground=fg_t)
        self.ai_translation_prompt_textbox.grid(row=0, column=1, sticky="ew", padx=5)

        f_ana = ttkb.Frame(parent); f_ana.grid(row=get_row(), column=0, sticky="ew", pady=8, padx=5); f_ana.grid_columnconfigure(1, weight=1)
        lbl_ana = ttkb.Label(f_ana, text=self._("分析提示词")); lbl_ana.grid(row=0, column=0, sticky="nw", padx=(5, 10))
        self.translatable_widgets[lbl_ana] = "分析提示词"
        self.ai_analysis_prompt_textbox = tk.Text(f_ana, height=7, font=self.app_font_mono, wrap="word", relief="flat", background=bg_t, foreground=fg_t, insertbackground=fg_t)
        self.ai_analysis_prompt_textbox.grid(row=0, column=1, sticky="ew", padx=5)

    def _apply_config_values_to_editor(self):
        if not self.current_config or not self.editor_ui_built: return
        cfg = self.current_config
        def set_val(widget, value):
            if not widget: return
            if isinstance(widget, tk.Text): widget.delete("1.0", tk.END); widget.insert("1.0", str(value or ""))
            elif isinstance(widget, ttkb.Entry): widget.delete(0, tk.END); widget.insert(0, str(value or ""))
        self.general_log_level_var.set(cfg.log_level)
        set_val(self.proxy_http_entry, cfg.proxies.http)
        set_val(self.proxy_https_entry, cfg.proxies.https)
        set_val(self.downloader_sources_file_entry, cfg.downloader.genome_sources_file)
        set_val(self.downloader_output_dir_entry, cfg.downloader.download_output_base_dir)
        self.downloader_force_download_var.set(cfg.downloader.force_download)
        set_val(self.downloader_max_workers_entry, cfg.downloader.max_workers)
        self.downloader_use_proxy_var.set(cfg.downloader.use_proxy_for_download)
        set_val(self.batch_ai_max_workers_entry, cfg.batch_ai_processor.max_workers)
        self.ai_default_provider_var.set(self.AI_PROVIDERS.get(cfg.ai_services.default_provider, {}).get('name', ''))
        self.ai_use_proxy_var.set(cfg.ai_services.use_proxy_for_ai)
        for p_key, p_cfg in cfg.ai_services.providers.items():
            safe_key = p_key.replace('-', '_')
            if apikey_widget := getattr(self, f"ai_{safe_key}_apikey_entry", None): set_val(apikey_widget, p_cfg.api_key)
            if baseurl_widget := getattr(self, f"ai_{safe_key}_baseurl_entry", None): set_val(baseurl_widget, p_cfg.base_url)
            if model_selector := getattr(self, f"ai_{safe_key}_model_selector", None): _dropdown, var = model_selector; var.set(p_cfg.model or "")
        set_val(self.ai_translation_prompt_textbox, cfg.ai_prompts.translation_prompt)
        set_val(self.ai_analysis_prompt_textbox, cfg.ai_prompts.analysis_prompt)
        self.logger.info(self._("配置已应用到编辑器UI。"))

    def _save_config_from_editor(self):
        if not self.current_config or not self.config_path:
            self.ui_manager.show_error_message(self._("错误"), self._("没有加载配置文件，无法保存。"))
            return
        try:
            cfg = self.current_config
            cfg.log_level = self.general_log_level_var.get()
            cfg.proxies.http = self.proxy_http_entry.get() or None
            cfg.proxies.https = self.proxy_https_entry.get() or None
            cfg.downloader.genome_sources_file = self.downloader_sources_file_entry.get()
            cfg.downloader.download_output_base_dir = self.downloader_output_dir_entry.get()
            cfg.downloader.force_download = self.downloader_force_download_var.get()
            cfg.downloader.max_workers = int(self.downloader_max_workers_entry.get() or 3)
            cfg.downloader.use_proxy_for_download = self.downloader_use_proxy_var.get()
            try:
                max_workers_val = int(self.batch_ai_max_workers_entry.get())
                if max_workers_val <= 0: raise ValueError
                cfg.batch_ai_processor.max_workers = max_workers_val
            except (ValueError, TypeError):
                cfg.batch_ai_processor.max_workers = 4
                self.logger.warning(self._("无效的最大工作线程数值，已重置为默认值 4。"))
            cfg.ai_services.default_provider = next((k for k, v in self.AI_PROVIDERS.items() if v['name'] == self.ai_default_provider_var.get()), 'google')
            cfg.ai_services.use_proxy_for_ai = self.ai_use_proxy_var.get()
            for p_key, p_cfg in cfg.ai_services.providers.items():
                safe_key = p_key.replace('-', '_')
                if apikey_widget := getattr(self, f"ai_{safe_key}_apikey_entry", None): p_cfg.api_key = apikey_widget.get()
                if baseurl_widget := getattr(self, f"ai_{safe_key}_baseurl_entry", None): p_cfg.base_url = baseurl_widget.get() or None
                if model_selector := getattr(self, f"ai_{safe_key}_model_selector", None): dropdown, var = model_selector; p_cfg.model = var.get()
            cfg.ai_prompts.translation_prompt = self.ai_translation_prompt_textbox.get("1.0", tk.END).strip()
            cfg.ai_prompts.analysis_prompt = self.ai_analysis_prompt_textbox.get("1.0", tk.END).strip()
            if save_config(cfg, self.config_path):
                self.ui_manager.show_info_message(self._("保存成功"), self._("配置文件已更新。"))
                self.ui_manager.update_ui_from_config()
            else:
                self.ui_manager.show_error_message(self._("保存失败"), self._("写入文件时发生未知错误。"))
        except Exception as e:
            self.ui_manager.show_error_message(self._("保存错误"), self._("保存配置时发生错误:\n{}").format(traceback.format_exc()))

    def _create_home_frame(self, parent):
        page = ttkb.Frame(parent)
        page.grid_columnconfigure(0, weight=1)
        title_label = ttkb.Label(page, text=self._(self.title_text_key), font=self.app_title_font)
        title_label.pack(pady=(40, 10))
        self.translatable_widgets[title_label] = self.title_text_key
        ttkb.Label(page, textvariable=self.config_path_display_var, font=self.app_font).pack(pady=(10, 20))
        cards_frame = ttkb.Frame(page); cards_frame.pack(pady=20, padx=20, fill="x", expand=False); cards_frame.grid_columnconfigure((0, 1), weight=1)
        card1 = ttkb.LabelFrame(cards_frame, text=self._("配置文件"), bootstyle="primary"); card1.grid(row=0, column=0, padx=10, pady=10, sticky="nsew"); card1.grid_columnconfigure(0, weight=1)
        self.translatable_widgets[card1] = "配置文件"
        btn1 = ttkb.Button(card1, text=self._("加载配置文件..."), command=self.event_handler.load_config_file, bootstyle="primary"); btn1.grid(row=0, column=0, sticky="ew", padx=20, pady=10)
        self.translatable_widgets[btn1] = "加载配置文件..."
        btn2 = ttkb.Button(card1, text=self._("生成默认配置..."), command=self.event_handler._generate_default_configs_gui, bootstyle="info"); btn2.grid(row=1, column=0, sticky="ew", padx=20, pady=10)
        self.translatable_widgets[btn2] = "生成默认配置..."
        card2 = ttkb.LabelFrame(cards_frame, text=self._("帮助与支持"), bootstyle="primary"); card2.grid(row=0, column=1, padx=10, pady=10, sticky="nsew"); card2.grid_columnconfigure(0, weight=1)
        self.translatable_widgets[card2] = "帮助与支持"
        btn3 = ttkb.Button(card2, text=self._("在线帮助文档"), command=self.event_handler._open_online_help, bootstyle="primary"); btn3.grid(row=0, column=0, sticky="ew", padx=20, pady=10)
        self.translatable_widgets[btn3] = "在线帮助文档"
        btn4 = ttkb.Button(card2, text=self._("关于本软件"), command=self.event_handler._show_about_window, bootstyle="info"); btn4.grid(row=1, column=0, sticky="ew", padx=20, pady=10)
        self.translatable_widgets[btn4] = "关于本软件"
        return page

    def _create_tools_frame(self, parent):
        frame = ttkb.Frame(parent)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)
        self.tools_nav_frame = ttkb.Frame(frame, padding=(5, 0))
        self.tools_nav_frame.grid(row=0, column=0, sticky="ns")
        self.tools_content_frame = ttkb.Frame(frame, padding=(10, 0))
        self.tools_content_frame.grid(row=0, column=1, sticky='nsew')
        self.tools_content_frame.grid_rowconfigure(0, weight=1)
        self.tools_content_frame.grid_columnconfigure(0, weight=1)
        self.tool_content_pages = {}
        return frame

    def _populate_tools_ui(self):
        for widget in self.tools_nav_frame.winfo_children(): widget.destroy()
        for widget in self.tools_content_frame.winfo_children(): widget.destroy()
        self.tool_tab_instances.clear()
        self.tool_content_pages.clear()
        self.tool_buttons.clear()
        from ui.tabs import (AIAssistantTab, DataDownloadTab, AnnotationTab, EnrichmentTab, GenomeIdentifierTab, GFFQueryTab, HomologyTab, LocusConversionTab, XlsxConverterTab)
        tab_map = {
            "download": DataDownloadTab, "annotation": AnnotationTab, "enrichment": EnrichmentTab, "xlsx_to_csv": XlsxConverterTab,
            "genome_identifier": GenomeIdentifierTab, "homology": HomologyTab, "locus_conversion": LocusConversionTab, "gff_query": GFFQueryTab,
            "ai_assistant": AIAssistantTab,
        }
        for key in self.TOOL_TAB_ORDER:
            if TabClass := tab_map.get(key):
                content_page = ttkb.Frame(self.tools_content_frame)
                instance = TabClass(parent=content_page, app=self, translator=self._)
                self.tool_tab_instances[key] = instance
                self.tool_content_pages[key] = content_page
                content_page.grid(row=0, column=0, sticky='nsew'); content_page.grid_remove()
                btn = ttkb.Button(master=self.tools_nav_frame, text=self.TAB_TITLE_KEYS[key], bootstyle="outline-info", command=lambda k=key: self.on_tool_button_select(k))
                btn.pack(fill='x', padx=10, pady=4)
                self.tool_buttons[key] = btn
        if self.TOOL_TAB_ORDER:
            self.on_tool_button_select(self.TOOL_TAB_ORDER[0])

    def on_tool_button_select(self, selected_key: str):
        for key, button in self.tool_buttons.items():
            button.config(bootstyle="info" if key == selected_key else "outline-info")
        self._switch_tool_content_page(selected_key)

    def _switch_tool_content_page(self, key_to_show: str):
        """切换在主内容区显示的工具页面。"""
        for key, page in self.tool_content_pages.items():
            if key == key_to_show:
                # 显示被选中的页面
                page.grid()

                # --- 【核心修正】 ---
                # 当一个页面被选中显示时，获取其实例并调用其刷新函数
                if instance := self.tool_tab_instances.get(key):
                    if hasattr(instance, 'update_from_config'):
                        # 调用该Tab自己的update_from_config方法，
                        # 从而根据最新配置刷新其所有UI组件的状态。
                        instance.update_from_config()
                        self.logger.debug(f"Tab '{key}' has been refreshed upon selection.")
                # --- 修正结束 ---

            else:
                # 隐藏其他未被选中的页面
                page.grid_remove()

    def set_app_icon(self):
        """
        设置应用程序主窗口的图标。
        此方法会查找并加载指定的.ico文件作为窗口和任务栏的图标。
        """
        try:
            # 检查程序是否被打包成单文件执行包 (pyinstaller)
            if hasattr(sys, '_MEIPASS'):
                # 如果是，则基准路径是解压后的临时目录
                base_path = sys._MEIPASS
            else:
                # 否则，基准路径是当前脚本文件所在的目录 (即 ui/ 目录)
                base_path = os.path.dirname(os.path.abspath(__file__))

            # 【核心修改】将 "icon.ico" 修改为您自己的图标文件名 "logo.ico"
            icon_path = os.path.join(base_path, "assets", "logo.ico")

            if os.path.exists(icon_path):
                self.app_icon_path = icon_path
                # 调用 ttkbootstrap 的方法来设置图标
                self.iconbitmap(self.app_icon_path)
                self.logger.info(f"成功加载并设置应用图标: {icon_path}")
            else:
                # 如果找不到图标，在日志中打印警告，方便排查问题
                self.logger.warning(f"应用图标文件未找到，请检查路径: {icon_path}")

        except Exception as e:
            # 如果加载过程中出现任何其他错误，也记录下来
            self.logger.warning(f"加载主窗口图标失败: {e}")


    def _update_wraplength(self, event):
        wraplength = event.width - 20
        if hasattr(self, 'config_warning_label'): self.config_warning_label.configure(wraplength=wraplength)

    def _create_editor_frame(self, parent):
        page = ttkb.Frame(parent)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        # --- 顶部框架，包含警告和保存按钮 ---
        top_frame = ttkb.Frame(page)
        top_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        top_frame.grid_columnconfigure(0, weight=1)

        self.config_warning_label = ttkb.Label(top_frame,
                                               text=self._("!! 警告: 配置文件可能包含敏感信息，请勿轻易分享。"),
                                               font=self.app_font_bold, bootstyle="danger")
        self.config_warning_label.grid(row=0, column=0, sticky="w", padx=5)
        top_frame.bind("<Configure>", self._update_wraplength)

        self.save_editor_button = ttkb.Button(top_frame, text=self._("应用并保存"),
                                              command=self._save_config_from_editor,
                                              bootstyle='success')
        self.save_editor_button.grid(row=0, column=1, sticky="e", padx=5)

        # --- 【核心修改】为整个页面绑定快捷键 ---
        # 创建一个包装函数，以便在调用保存方法前可以打印日志或进行检查
        def save_via_shortcut(event=None):
            self.logger.debug(f"快捷键 '{event.keysym}' 触发保存操作。")
            # 确保按钮是可用的状态才执行
            if self.save_editor_button['state'] == 'normal':
                self._save_config_from_editor()
            return "break"  # 阻止事件继续传播

        # 绑定 Ctrl + S
        page.bind_all("<Control-s>", save_via_shortcut)
        # 绑定 Enter (Return) 键
        page.bind_all("<Return>", save_via_shortcut)

        # --- 可滚动的画布区域，用于承载所有配置项 ---
        self.editor_canvas = tk.Canvas(page, highlightthickness=0, bd=0,
                                       background=self.style.lookup('TFrame', 'background'))
        self.editor_canvas.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)

        scrollbar = ttkb.Scrollbar(page, orient="vertical", command=self.editor_canvas.yview, bootstyle="round")
        scrollbar.grid(row=1, column=1, sticky="ns", pady=10)
        self.editor_canvas.configure(yscrollcommand=scrollbar.set)

        self.editor_scroll_frame = ttkb.Frame(self.editor_canvas)
        window_id = self.editor_canvas.create_window((0, 0), window=self.editor_scroll_frame, anchor="nw")

        self._last_editor_canvas_width = 0

        def on_frame_configure(event):
            self.editor_canvas.configure(scrollregion=self.editor_canvas.bbox("all"))

        def on_canvas_resize(event):
            if event.width != self._last_editor_canvas_width:
                self.editor_canvas.itemconfig(window_id, width=event.width)
                self._last_editor_canvas_width = event.width
            self.editor_canvas.configure(scrollregion=self.editor_canvas.bbox("all"))

        self.editor_scroll_frame.bind("<Configure>", on_frame_configure)
        self.editor_canvas.bind("<Configure>", on_canvas_resize)

        # --- 鼠标滚轮事件处理 ---
        def _on_mousewheel(event):
            if not self.editor_canvas or not self.editor_canvas.winfo_exists():
                return
            scroll_units = 0
            if event.num == 5 or event.delta < 0:
                scroll_units = 2
            elif event.num == 4 or event.delta > 0:
                scroll_units = -2

            if scroll_units != 0:
                self.editor_canvas.yview_scroll(scroll_units, "units")

            return "break"

        # 确保滚动事件在所有子组件上都生效
        for widget in [self.editor_canvas, self.editor_scroll_frame]:
            widget.bind_all("<MouseWheel>", _on_mousewheel)  # For Windows/macOS
            widget.bind_all("<Button-4>", _on_mousewheel)  # For Linux (scroll up)
            widget.bind_all("<Button-5>", _on_mousewheel)  # For Linux (scroll down)

        # --- 未加载配置时的提示信息 ---
        self.editor_no_config_label = ttkb.Label(page, text=self._("请先从“主页”加载或生成一个配置文件。"),
                                                 font=self.app_subtitle_font, bootstyle="secondary")
        self.editor_no_config_label.grid(row=1, column=0, sticky="nsew", columnspan=2)

        return page

    def _handle_editor_ui_update(self):
        if not self.editor_ui_built: return
        has_config = bool(self.current_config)
        if hasattr(self, 'editor_canvas') and self.editor_canvas and self.editor_canvas.winfo_exists():
            slaves = self.editor_canvas.master.grid_slaves(row=1, column=1)
            if slaves:
                scrollbar = slaves[0]
                if has_config:
                    self.editor_canvas.grid(); scrollbar.grid(); self.editor_no_config_label.grid_remove()
                    self._apply_config_values_to_editor()
                else:
                    self.editor_canvas.grid_remove(); scrollbar.grid_remove(); self.editor_no_config_label.grid()
        if hasattr(self, 'save_editor_button'): self.save_editor_button.configure(state="normal" if has_config else "disabled")

    def _setup_fonts(self):
        font_stack = ["Microsoft YaHei UI", "Segoe UI", "Calibri", "Helvetica", "sans-serif"]
        mono_stack = ["Consolas", "Courier New", "monospace"]
        self.font_family = next((f for f in font_stack if f in tkfont.families()), "sans-serif")
        self.mono_font_family = next((f for f in mono_stack if f in tkfont.families()), "monospace")
        self.logger.info(self._("UI font set to: {}, Monospace font to: {}").format(self.font_family, self.mono_font_family))
        self.app_font = tkfont.Font(family=self.font_family, size=12)
        self.app_font_italic = tkfont.Font(family=self.font_family, size=12, slant="italic")
        self.app_font_bold = tkfont.Font(family=self.font_family, size=13, weight="bold")
        self.app_subtitle_font = tkfont.Font(family=self.font_family, size=16, weight="bold")
        self.app_title_font = tkfont.Font(family=self.font_family, size=24, weight="bold")
        self.app_comment_font = tkfont.Font(family=self.font_family, size=11)
        self.app_font_mono = tkfont.Font(family=self.mono_font_family, size=12)
        for style_name in ['TButton', 'TCheckbutton', 'TMenubutton', 'TLabel', 'TEntry', 'Toolbutton', 'Labelframe.TLabel']:
            self.style.configure(style_name, font=self.app_font)
        self.style.configure('success.TButton', font=self.app_font_bold)
        self.style.configure('outline.TButton', font=self.app_font)

    def _log_to_viewer(self, message, level="INFO"):
        if logging.getLogger().getEffectiveLevel() <= logging.getLevelName(level.upper()):
            self.log_queue.put((message, level))

    def check_queue_periodic(self):
        try:
            while not self.log_queue.empty():
                log_message, log_level = self.log_queue.get_nowait()
                self.ui_manager.display_log_message_in_ui(log_message, log_level)
            while not self.message_queue.empty():
                msg_type, data = self.message_queue.get_nowait()
                if handler := self.event_handler.message_handlers.get(msg_type):
                    handler(data) if data is not None else handler()
        except queue.Empty: pass
        except Exception as e: self.logger.critical(self._("处理消息队列时出错: {}").format(e), exc_info=True)
        self.after(100, self.check_queue_periodic)

    def reconfigure_logging(self, log_level_str: str):
        try:
            if isinstance(new_level := logging.getLevelName(log_level_str.upper()), int):
                if (root := logging.getLogger()).getEffectiveLevel() != new_level:
                    root.setLevel(new_level)
                    for handler in root.handlers: handler.setLevel(new_level)
                    self.logger.info(self._("全局日志级别已更新为: {}").format(log_level_str))
        except Exception as e:
            self.logger.error(self._("配置日志级别时出错: {}").format(e))

    def restart_app(self):
        self.logger.info("Application restart requested by user.")
        try:
            self.destroy()
        except Exception as e:
            self.logger.error(f"Error during pre-restart cleanup: {e}")
        python = sys.executable
        os.execv(python, [python] + sys.argv)