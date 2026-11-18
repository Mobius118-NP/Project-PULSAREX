"""Native Windows-friendly launcher. Tk runs only on the GUI thread."""
import multiprocessing as mp
import os
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk

from . import __version__
from .config import Config
from .launcher_service import ServerController, launch_config, read_settings, save_settings
from .security import generate_pin


def default_data_dir():
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PULSAREX'
    return Path(__file__).resolve().parents[2] / 'data'


class Launcher:
    def __init__(self, root):
        self.root = root
        self.controller = ServerController()
        self.closing = False
        self.opened = False
        self.settings_path = default_data_dir()/'launcher-settings.json'
        settings = read_settings(self.settings_path)
        base_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]
        default_config = base_dir/'config.toml'
        self.mode = tk.StringVar(value='LAN (same Wi-Fi)' if settings.get('mode') == 'lan' else 'Local only')
        self.port = tk.StringVar(value=str(settings.get('port', 8765)))
        self.source = tk.StringVar(value='Live microphone' if settings.get('source') == 'microphone' else 'Synthetic demonstration')
        self.token = tk.StringVar(value=generate_pin())
        self.visible = tk.BooleanVar(value=False)
        self.auto_open = tk.BooleanVar(value=bool(settings.get('open_browser', True)))
        self.config_path = tk.StringVar(value=settings.get('config_path', str(default_config) if default_config.exists() else ''))
        self.status = tk.StringVar(value=self.controller.message)
        self.local_url = tk.StringVar(value='Start the server to activate the dashboard')
        self.lan_url = tk.StringVar(value='Select LAN mode, then Start')
        root.title(f'PULSAREX Launcher {__version__}')
        root.geometry('720x720')
        root.minsize(660, 640)
        root.configure(bg='#0c1410')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self._build()
        self._mode_changed()
        root.after(150, self.tick)

    def _build(self):
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', background='#101b14', foreground='#d9e7cb', font=('Segoe UI', 10))
        style.configure('TFrame', background='#0c1410')
        style.configure('TLabel', background='#0c1410')
        style.configure('Title.TLabel', font=('Consolas', 24, 'bold'), foreground='#c1d98d')
        style.configure('Muted.TLabel', foreground='#a6b69c')
        style.configure('TButton', padding=(13, 8), background='#253421')
        style.map('TButton', background=[('active', '#43543a')], foreground=[('disabled', '#758270')])
        style.configure('Start.TButton', background='#b6cf88', foreground='#12200d', font=('Segoe UI', 11, 'bold'))
        style.map('Start.TButton', background=[('active', '#d2e8ab')])
        style.configure('TEntry', fieldbackground='#17241b', foreground='#eff6e7', padding=7)
        style.configure('TCombobox', fieldbackground='#17241b', foreground='#eff6e7', padding=6)
        style.map('TCombobox', fieldbackground=[('readonly', '#17241b')], selectbackground=[('readonly', '#253b29')],
                  selectforeground=[('readonly', '#eff6e7')])
        style.configure('TCheckbutton', background='#0c1410', foreground='#c9d9ba')
        shell = ttk.Frame(self.root)
        shell.pack(fill='both', expand=True)
        canvas = tk.Canvas(shell, background='#0c1410', highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        frame = ttk.Frame(canvas, padding=24)
        content = canvas.create_window((0, 0), window=frame, anchor='nw')
        frame.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(content, width=event.width))
        def wheel(event):
            if not isinstance(event.widget, (ttk.Entry, ttk.Combobox)):
                canvas.yview_scroll(-int(event.delta/120), 'units')
        self.root.bind_all('<MouseWheel>', wheel)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text='PULSAREX / MK. II', style='Title.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(frame, text='Acoustic observatory  /  Local server launcher', style='Muted.TLabel').grid(row=1, column=0, sticky='w', pady=(3, 20))
        options = ttk.Frame(frame)
        options.grid(row=2, column=0, sticky='ew')
        options.columnconfigure(0, weight=2)
        options.columnconfigure(1, weight=1)
        options.columnconfigure(2, weight=2)
        for i, label in enumerate(('Connection mode', 'Port', 'Audio source')):
            ttk.Label(options, text=label).grid(row=0, column=i, sticky='w', padx=(0, 12))
        self.mode_box = ttk.Combobox(options, textvariable=self.mode, values=['Local only', 'LAN (same Wi-Fi)'], state='readonly', width=22)
        self.mode_box.grid(row=1, column=0, sticky='ew', padx=(0, 12), pady=(6, 0))
        self.mode_box.bind('<<ComboboxSelected>>', self._mode_changed)
        self.port_entry = ttk.Entry(options, textvariable=self.port, width=8)
        self.port_entry.grid(row=1, column=1, sticky='ew', padx=(0, 12), pady=(6, 0))
        self.source_box = ttk.Combobox(options, textvariable=self.source, values=['Synthetic demonstration', 'Live microphone'], state='readonly', width=24)
        self.source_box.grid(row=1, column=2, sticky='ew', pady=(6, 0))
        ttk.Label(frame, text='LAN access PIN (6 digits)', style='Muted.TLabel').grid(row=3, column=0, sticky='w', pady=(18, 6))
        tokens = ttk.Frame(frame)
        tokens.grid(row=4, column=0, sticky='ew')
        tokens.columnconfigure(0, weight=1)
        pin_input = self.root.register(lambda value: value == '' or (len(value) <= 6 and value.isascii() and value.isdigit()))
        self.token_entry = ttk.Entry(tokens, textvariable=self.token, show='\u2022', validate='key',
                                     validatecommand=(pin_input, '%P'))
        self.token_entry.grid(row=0, column=0, sticky='ew', padx=(0, 8))
        self.generate = ttk.Button(tokens, text='Generate PIN', command=lambda: self.token.set(generate_pin()))
        self.generate.grid(row=0, column=1, padx=(0, 8))
        self.copy_token_button = ttk.Button(tokens, text='Copy PIN', command=lambda: self.copy(self.token.get(), 'Access PIN copied. Paste it into the dashboard login.'))
        self.copy_token_button.grid(row=0, column=2)
        self.show_token = ttk.Checkbutton(frame, text='Show PIN', variable=self.visible,
                                          command=lambda: self.token_entry.configure(show='' if self.visible.get() else '\u2022'))
        self.show_token.grid(row=5, column=0, sticky='w', pady=(7, 0))
        self.security_note = ttk.Label(frame, text='Six-digit LAN PIN. Kept in memory; never saved to disk.', style='Muted.TLabel')
        self.security_note.grid(row=6, column=0, sticky='w', pady=(5, 15))
        cfg = ttk.Frame(frame)
        cfg.grid(row=7, column=0, sticky='ew')
        cfg.columnconfigure(0, weight=1)
        ttk.Label(cfg, text='Configuration file (optional)').grid(row=0, column=0, sticky='w')
        self.config_entry = ttk.Entry(cfg, textvariable=self.config_path)
        self.config_entry.grid(row=1, column=0, sticky='ew', pady=(6, 0), padx=(0, 8))
        self.browse = ttk.Button(cfg, text='Browse...', command=self.pick_config)
        self.browse.grid(row=1, column=1, pady=(6, 0))
        self.open_check = ttk.Checkbutton(frame, text='Open dashboard when ready', variable=self.auto_open)
        self.open_check.grid(row=8, column=0, sticky='w', pady=(15, 14))
        actions = ttk.Frame(frame)
        actions.grid(row=9, column=0, sticky='ew')
        self.start_button = ttk.Button(actions, text='Start server', command=self.start, style='Start.TButton')
        self.start_button.pack(side='left', padx=(0, 10))
        self.stop_button = ttk.Button(actions, text='Stop server', command=self.controller.stop, state='disabled')
        self.stop_button.pack(side='left', padx=(0, 10))
        self.open_button = ttk.Button(actions, text='Open dashboard', command=lambda: webbrowser.open(self.controller.local_url), state='disabled')
        self.open_button.pack(side='left')
        self.status_label = ttk.Label(frame, textvariable=self.status, wraplength=650, foreground='#d5b879')
        self.status_label.grid(row=10, column=0, sticky='ew', pady=(16, 14))
        links = ttk.Frame(frame)
        links.grid(row=11, column=0, sticky='ew')
        links.columnconfigure(0, weight=1)
        ttk.Label(links, text='This computer').grid(row=0, column=0, sticky='w')
        ttk.Entry(links, textvariable=self.local_url, state='readonly').grid(row=1, column=0, sticky='ew', pady=(5, 10), padx=(0, 8))
        self.copy_local = ttk.Button(links, text='Copy link', command=lambda: self.copy(self.local_url.get(), 'Local dashboard link copied.'), state='disabled')
        self.copy_local.grid(row=1, column=1, pady=(5, 10))
        ttk.Label(links, text='Other devices on the same Wi-Fi / LAN').grid(row=2, column=0, sticky='w')
        self.lan_links = ttk.Combobox(links, textvariable=self.lan_url, state='readonly')
        self.lan_links.grid(row=3, column=0, sticky='ew', pady=(5, 0), padx=(0, 8))
        self.copy_lan = ttk.Button(links, text='Copy LAN link', command=lambda: self.copy(self.lan_url.get(), 'LAN link copied. Open it on the other device, then enter the PIN.'), state='disabled')
        self.copy_lan.grid(row=3, column=1, pady=(5, 0))
        ttk.Label(frame, text='Use a trusted private network. Closing this launcher stops capture and the server.\nMicrophone selection and two-mic geometry are available in the dashboard.',
                  style='Muted.TLabel', wraplength=650).grid(row=12, column=0, sticky='w', pady=(18, 0))
        self.last_state = None

    def _mode_changed(self, event=None):
        lan = self.mode.get().startswith('LAN')
        self.token_entry.configure(state=('readonly' if self.controller.busy else 'normal') if lan else 'disabled')
        self.generate.configure(state='normal' if lan and not self.controller.busy else 'disabled')
        self.show_token.configure(state='normal' if lan else 'disabled')
        self.copy_token_button.configure(state='normal' if lan else 'disabled')
        self.security_note.configure(text='Six-digit LAN PIN. Kept in memory; never saved to disk.' if lan else 'Local only: other devices cannot connect. No PIN is needed.')

    def pick_config(self):
        selected = filedialog.askopenfilename(title='Choose PULSAREX configuration', filetypes=[('TOML configuration', '*.toml')])
        if selected:
            self.config_path.set(selected)

    def copy(self, text, message):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.set(message)

    def start(self):
        try:
            path = self.config_path.get().strip()
            base = Config.load(path or None)
            base.data_dir = str((Path(path).resolve().parent/base.data_dir).resolve()) if path else str(default_data_dir())
            mode = 'lan' if self.mode.get().startswith('LAN') else 'local'
            source = 'microphone' if self.source.get() == 'Live microphone' else 'simulation'
            config = launch_config(base, mode, self.port.get(), source, self.token.get())
            self.controller.start(config, self.token.get() if mode == 'lan' else None)
            self.opened = False
            self.local_url.set(self.controller.local_url)
            self.lan_links.configure(values=self.controller.lan_urls)
            self.lan_url.set(self.controller.lan_urls[0] if self.controller.lan_urls else
                             'Local only' if mode == 'local' else 'No LAN IPv4 found. Check the network adapter.')
            try:
                save_settings(self.settings_path, {'mode': mode, 'source': source, 'port': config.port,
                                                  'config_path': path, 'open_browser': self.auto_open.get()})
            except OSError:
                pass  # Server remains usable if preference persistence is unavailable.
            self.last_state = None
            self.tick_controls()
        except (OSError, ValueError, TypeError) as exc:
            self.status.set(str(exc))

    def tick_controls(self):
        busy = self.controller.busy
        running = self.controller.state == 'running' and busy
        for box in (self.mode_box, self.source_box):
            box.configure(state='disabled' if busy else 'readonly')
        for widget in (self.port_entry, self.config_entry, self.browse):
            widget.configure(state='disabled' if busy else 'normal')
        self.start_button.configure(state='disabled' if busy else 'normal')
        self.stop_button.configure(state='normal' if busy and self.controller.state != 'stopping' else 'disabled')
        self.open_button.configure(state='normal' if running else 'disabled')
        self.copy_local.configure(state='normal' if running else 'disabled')
        self.copy_lan.configure(state='normal' if running and self.controller.lan_urls else 'disabled')
        self._mode_changed()

    def tick(self):
        state, message = self.controller.poll()
        current = (state, message, self.controller.busy)
        if current != self.last_state:
            self.status.set(message)
            self.last_state = current
            self.tick_controls()
        if state == 'running' and not self.opened:
            self.opened = True
            if self.auto_open.get() and not self.closing:
                webbrowser.open(self.controller.local_url)
        if self.closing and not self.controller.busy:
            self.root.destroy()
            return
        self.root.after(150, self.tick)

    def close(self):
        self.closing = True
        self.controller.stop()
        if not self.controller.busy:
            self.root.destroy()


def main():
    mp.freeze_support()
    root = tk.Tk()
    application = Launcher(root)
    try:
        root.mainloop()
    finally:
        application.controller.close()


if __name__ == '__main__':
    main()
