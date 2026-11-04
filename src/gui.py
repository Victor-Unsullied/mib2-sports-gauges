"""Small offline Tk configurator; writes the same XML as the website."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from . import config


class Configurator:
    def __init__(self, window, path=None):
        self.window = window
        self.path = Path(path or config.ROOT / 'config.xml')
        self.current = config.read(self.path) if self.path.exists() else config.blank()
        self.lang = self.current['language']
        self.vars = {}
        self.window.title('MIB2 Sports Gauges v1.0.0')
        self.window.minsize(680, 620)
        self.render()

    def t(self, en, tr):
        return tr if self.lang == 'tr' else en

    def collect(self):
        options = {}
        for key, var in self.vars.items():
            value = var.get()
            if key in config.RANGES:
                value = None if not value.strip() else int(value)
            elif key in config.ENUMS:
                item = next(x for x in config.CATALOG['dropdowns'] if x['id'] == key)
                value = next(x['value'] for x in item['choices'] if self.label(x) == value)
            options[key] = value
        return config.validate({'language': self.lang, 'train': self.train.get(), 'mu': self.mu.get(), 'options': options})

    def label(self, item):
        return item.get('label_tr', item['label']) if self.lang == 'tr' else item['label']

    def switch(self, lang):
        try:
            self.current = self.collect()
        except ValueError as error:
            messagebox.showerror('Configuration', str(error), parent=self.window)
            return
        self.lang = lang
        self.current['language'] = lang
        self.render()

    def render(self):
        for widget in self.window.winfo_children():
            widget.destroy()
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        bar = ttk.Frame(frame)
        bar.grid(row=0, column=0, sticky='ew')
        ttk.Label(bar, text='MIB2 Sports Gauges · v1.0.0', font=('', 16, 'bold')).pack(side='left')
        for lang, name in [('en', 'English'), ('tr', 'Türkçe')]:
            ttk.Button(bar, text=name, command=lambda l=lang: self.switch(l)).pack(side='right')
        ttk.Label(frame, text=self.t('Choose fixes only for gauges that do not work correctly in your car.\nLeave working gauges at their factory settings.', 'Yalnızca aracınızda çalışmayan veya yanlış gösteren göstergeleri düzeltin.\nDüzgün çalışan göstergeler için fabrika ayarlarını koruyun.'), wraplength=650).grid(row=1, column=0, sticky='w', pady=10)
        tk.Label(frame, text=self.t('EXPERIMENTAL — Your engine/head-unit combination is probably untested.\nYou accept all risk. A failed installation may brick the unit.', 'DENEYSEL — Motor/ünite kombinasyonunuz büyük olasılıkla denenmedi.\nTüm risk size aittir. Hatalı kurulum üniteyi kullanılamaz hale getirebilir.'), bg='#8c1d25', fg='white', justify='left', padx=12, pady=10, wraplength=650).grid(row=2, column=0, sticky='ew')
        devices = ttk.LabelFrame(frame, text=self.t('Versions shown by your unit', 'Ünitenizin gösterdiği sürümler'), padding=8)
        devices.grid(row=3, column=0, sticky='ew', pady=8)
        self.train, self.mu = tk.StringVar(value=self.current['train']), tk.StringVar(value=self.current['mu'])
        ttk.Label(devices, text='Train').grid(row=0, column=0)
        ttk.Entry(devices, textvariable=self.train, width=36).grid(row=0, column=1, padx=8)
        ttk.Label(devices, text='MU').grid(row=0, column=2)
        ttk.Entry(devices, textvariable=self.mu, width=8).grid(row=0, column=3)
        boxes = ttk.LabelFrame(frame, text=self.t('Corrections and visible gauges', 'Düzeltmeler ve açık göstergeler'), padding=8)
        boxes.grid(row=4, column=0, sticky='ew')
        self.vars = {}
        for i, item in enumerate(config.CATALOG['checkboxes']):
            var = tk.BooleanVar(value=self.current['options'][item['id']])
            self.vars[item['id']] = var
            ttk.Checkbutton(boxes, text=self.label(item), variable=var).grid(row=i // 2, column=i % 2, sticky='w', padx=6, pady=3)
        choices = ttk.LabelFrame(frame, text=self.t('Gauge settings', 'Gösterge ayarları'), padding=8)
        choices.grid(row=5, column=0, sticky='ew', pady=8)
        for i, item in enumerate(config.CATALOG['dropdowns']):
            choice = next(x for x in item['choices'] if x['value'] == self.current['options'][item['id']])
            var = tk.StringVar(value=self.label(choice))
            self.vars[item['id']] = var
            ttk.Label(choices, text=self.label(item)).grid(row=i, column=0, sticky='w')
            ttk.Combobox(choices, textvariable=var, values=[self.label(x) for x in item['choices']], state='readonly', width=35).grid(row=i, column=1, sticky='ew', padx=10, pady=2)
        ttk.Label(choices, text=self.t('Only the power unit is selected here. Existing gauges keep the unit settings;\nthe added torque gauge uses Nm. Boost-pressure correction is not available.', 'Buradan yalnızca güç birimi seçilir. Mevcut göstergeler ünitenin birim ayarlarını\nkullanır; eklenen tork göstergesi Nm gösterir. Turbo basıncı düzeltmesi henüz yok.'), wraplength=640).grid(row=3, column=0, columnspan=2, sticky='w', pady=6)
        limits = ttk.LabelFrame(frame, text=self.t('Optional scale limits — blank means automatic', 'İsteğe bağlı kadran sınırları — boş bırakırsanız otomatik'), padding=8)
        limits.grid(row=6, column=0, sticky='ew')
        for i, kind in enumerate(('power', 'torque')):
            ttk.Label(limits, text=self.t(kind.title(), 'Güç' if kind == 'power' else 'Tork')).grid(row=i, column=0, padx=5)
            for j, bound in enumerate(('min', 'max')):
                key = kind + '_' + bound
                var = tk.StringVar(value='' if self.current['options'][key] is None else str(self.current['options'][key]))
                self.vars[key] = var
                ttk.Label(limits, text=self.t(bound, 'Alt' if bound == 'min' else 'Üst')).grid(row=i, column=1+j*2)
                ttk.Entry(limits, textvariable=var, width=10).grid(row=i, column=2+j*2, padx=6)
        ttk.Button(frame, text=self.t('Save config.xml', 'config.xml dosyasını kaydet'), command=self.save).grid(row=7, column=0, sticky='e', pady=12)
        ttk.Label(frame, text=self.t('Saving does not connect to or change the car.', 'Kaydetmek araca bağlanmaz, araçta değişiklik yapmaz.')).grid(row=8, column=0, sticky='w')

    def save(self):
        try:
            selected = self.collect()
            config.save(selected, self.path)
            self.current = selected
            messagebox.showinfo(self.t('Saved', 'Kaydedildi'), self.t('config.xml saved. Run install.py when ready.', 'config.xml kaydedildi. Hazır olduğunuzda install.py çalıştırın.'), parent=self.window)
        except (ValueError, OSError) as error:
            messagebox.showerror(self.t('Cannot save', 'Kaydedilemedi'), str(error), parent=self.window)


def main():
    window = tk.Tk()
    try:
        Configurator(window)
    except Exception as error:
        messagebox.showerror('Cannot open configuration', str(error), parent=window)
        window.destroy()
        return
    window.mainloop()
