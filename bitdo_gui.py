#!/usr/bin/env python3
"""Janela para configurar o 8BitDo Ultimate 2.4G (usa o protocolo do bitdo.py)."""
import os
import struct
import sys
import time

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

import bitdo  # noqa: E402

BACKUP_DIR = os.path.expanduser('~/.local/share/8bitdo-ultimate')
DEFAULT = bitdo.export(b'\xff' * bitdo.SIZE)['perfis'][0]  # flash apagada = padrão de fábrica

# Como os botões aparecem impressos no controle.
BUTTON_LABELS = {'LS': 'LSB', 'RS': 'RSB', 'SELECT': '−', 'START': '+', 'STAR': 'Estrela ★', 'HOME': 'Home',
                 'UP': '↑', 'DOWN': '↓', 'LEFT': '←', 'RIGHT': '→'}
FUNCTION_LABELS = {**BUTTON_LABELS, 'NONE': 'Desativado', 'TURBO': 'Turbo', 'TURBO_SINGLE': 'Turbo (um toque)',
                   'TURBO_AUTO': 'Turbo automático', 'SCREENSHOT': 'Captura de tela', 'SWAP': 'Swap'}
# Funções na ordem dos botões do controle, depois as especiais.
FUNCTIONS = [b for b in bitdo.BUTTONS if b in bitdo.TARGETS] + \
    ['TURBO', 'TURBO_SINGLE', 'TURBO_AUTO', 'SCREENSHOT', 'SWAP', 'NONE']
OPTION_LABELS = {
    'inverter_x_esquerdo': 'Inverter eixo X do analógico esquerdo',
    'inverter_y_esquerdo': 'Inverter eixo Y do analógico esquerdo',
    'inverter_x_direito': 'Inverter eixo X do analógico direito',
    'inverter_y_direito': 'Inverter eixo Y do analógico direito',
    'trocar_analogicos': 'Trocar analógico esquerdo e direito',
    'trocar_gatilhos': 'Trocar gatilho esquerdo e direito',
    'trocar_dpad_e_analogico_esquerdo': 'Trocar D-pad e analógico esquerdo',
    'gatilhos_digitais': 'Gatilhos digitais (sem pressão gradual)',
    'trocar_analogico_direito_e_gatilhos': 'Trocar analógico direito e gatilhos',
    'sensibilidade_de_movimento': 'Sensibilidade de movimento',
    'desativar_zona_morta': 'Desativar zona morta',
    'dpad_so_4_direcoes': 'D-pad só em 4 direções',
    'switch_dormir_na_base': 'Switch: dormir ao colocar na base',
    'switch_acordar_ao_tirar_da_base': 'Switch: acordar ao tirar da base',
}
SIDES = ('esquerdo', 'direito')


def group(page, title, description=None):
    g = Adw.PreferencesGroup(title=title, description=description)
    page.add(g)
    return g


def spin(g, title, hi):
    row = Adw.SpinRow.new_with_range(0, hi, 1)
    row.set_title(title)
    g.add(row)
    return row


class ProfilePage(Adw.PreferencesPage):
    """Os campos de um perfil: fill() mostra um perfil do bitdo.export, collect() devolve o editado."""

    def __init__(self):
        super().__init__()
        g = group(self, 'Perfil')
        self.name = Adw.EntryRow(title='Nome (até 16 letras)')
        self.on = Adw.SwitchRow(title='Usar este perfil personalizado',
                                subtitle='Desligado, este perfil fica no padrão de fábrica')
        g.add(self.name)
        g.add(self.on)

        g = group(self, 'Botões', 'Escolha o que cada botão físico faz')
        self.buttons = {}
        for b in bitdo.BUTTONS:
            row = Adw.ComboRow(title=BUTTON_LABELS.get(b, b))
            g.add(row)
            self.buttons[b] = row

        g = group(self, 'Vibração', 'De 0 (desligada) a 5 (máxima)')
        self.vib = {k: spin(g, f'Motor {"esquerdo" if k == "esquerda" else "direito"}', 5)
                    for k in ('esquerda', 'direita')}

        g = group(self, 'Analógicos', 'Zona morta e alcance de 0 a 128 (padrão 0 e 128)')
        self.sticks = {s: (spin(g, f'Analógico {s}: zona morta', 128), spin(g, f'Analógico {s}: alcance', 128))
                       for s in SIDES}

        g = group(self, 'Gatilhos', 'Início e fim do curso de 0 a 255 (padrão 0 e 255)')
        self.trigs = {s: (spin(g, f'Gatilho {s}: início', 255), spin(g, f'Gatilho {s}: fim', 255))
                      for s in SIDES}

        g = group(self, 'Opções')
        self.opts = {}
        for k in bitdo.OPTIONS:
            self.opts[k] = Adw.SwitchRow(title=OPTION_LABELS[k])
            g.add(self.opts[k])

        reset = Gtk.Button(label='Voltar este perfil ao padrão de fábrica', halign=Gtk.Align.CENTER,
                           css_classes=['pill'], margin_top=12)
        reset.connect('clicked', lambda *_: self.fill(DEFAULT))
        g = Adw.PreferencesGroup()
        g.add(reset)
        self.add(g)

    def fill(self, p):
        self.name.set_text(p['nome'])
        self.on.set_active(p['ativo'])
        for b, row in self.buttons.items():
            # funções desconhecidas lidas do controle (ex. '0xff') entram na lista para não se perderem
            values = FUNCTIONS + ([p['botoes'][b]] if p['botoes'][b] not in FUNCTIONS else [])
            row.values = values
            row.set_model(Gtk.StringList.new([FUNCTION_LABELS.get(v, v) for v in values]))
            row.set_selected(values.index(p['botoes'][b]))
        for k, row in self.vib.items():
            row.set_value(p['vibracao'][k])
        for s, (start, end) in self.sticks.items():
            start.set_value(p['analogicos'][s]['inicio'])
            end.set_value(p['analogicos'][s]['fim'])
        for s, (start, end) in self.trigs.items():
            start.set_value(p['gatilhos'][s]['inicio'])
            end.set_value(p['gatilhos'][s]['fim'])
        for k, row in self.opts.items():
            row.set_active(p['opcoes'][k])

    def collect(self):
        def pair(rows):
            return {s: {'inicio': int(a.get_value()), 'fim': int(b.get_value())} for s, (a, b) in rows.items()}
        return {
            'nome': self.name.get_text(),
            'ativo': self.on.get_active(),
            'botoes': {b: row.values[row.get_selected()] for b, row in self.buttons.items()},
            'vibracao': {k: int(row.get_value()) for k, row in self.vib.items()},
            'analogicos': pair(self.sticks),
            'gatilhos': pair(self.trigs),
            'opcoes': {k: row.get_active() for k, row in self.opts.items()},
        }


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='8BitDo Ultimate 2.4G', default_width=720, default_height=820)
        self.raw = None
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.pages = [ProfilePage() for _ in range(3)]
        for i, page in enumerate(self.pages):
            self.stack.add_titled(page, f'perfil{i + 1}', f'Perfil {i + 1}')

        header = Adw.HeaderBar(title_widget=Gtk.StackSwitcher(stack=self.stack))
        reload = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Voltar para a configuração atual')
        reload.connect('clicked', lambda *_: self.load('Configuração lida'))
        header.pack_start(reload)
        menu = Gio.Menu()
        menu.append('Salvar backup', 'win.backup')
        menu.append('Restaurar backup', 'win.restore')
        header.pack_end(Gtk.MenuButton(icon_name='open-menu-symbolic', menu_model=menu))
        self.save = Gtk.Button(label='Aplicar configuração', css_classes=['suggested-action'])
        self.save.connect('clicked', self.on_save)
        header.pack_end(self.save)
        for name, handler in (('backup', self.on_backup), ('restore', self.on_restore)):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', handler)
            self.add_action(action)

        retry = Gtk.Button(label='Tentar de novo', halign=Gtk.Align.CENTER, css_classes=['pill', 'suggested-action'])
        retry.connect('clicked', lambda *_: self.load('Configuração lida'))
        self.status = Adw.StatusPage(icon_name='input-gaming-symbolic', title='Controle não encontrado', child=retry)
        self.main = Gtk.Stack()
        self.main.add_named(self.status, 'status')
        self.main.add_named(self.stack, 'editor')

        view = Adw.ToolbarView(content=self.main)
        view.add_top_bar(header)
        self.toasts = Adw.ToastOverlay(child=view)
        self.set_content(self.toasts)
        self.load()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text))

    def device(self, fn):
        """Abre o controle, roda fn(dev) e mostra o erro na janela se falhar (None)."""
        # ponytail: leitura e gravação levam ~0,3 s e rodam na thread da janela; usar thread se ficar lento
        try:
            dev = bitdo.connect()
        except OSError as e:
            self.status.set_description(str(e))
            self.main.set_visible_child_name('status')
            self.save.set_sensitive(False)
            return None
        try:
            return fn(dev)
        except OSError as e:
            self.toast(f'Erro de comunicação: {e}')
        finally:
            dev.close()

    def load(self, message=None):
        got = self.device(lambda dev: (bitdo.version(dev), bitdo.read_config(dev)))
        if not got:
            return
        firmware, self.raw = got
        for page, p in zip(self.pages, bitdo.export(self.raw)['perfis']):
            page.fill(p)
        self.main.set_visible_child_name('editor')
        self.save.set_sensitive(True)
        self.set_title(f'8BitDo Ultimate 2.4G — firmware {firmware}')
        if message:
            self.toast(message)

    def write(self, make):
        """Grava make(configuração atual) no controle, com backup automático antes."""
        def run(dev):
            old = bitdo.read_config(dev)
            os.makedirs(BACKUP_DIR, exist_ok=True)
            with open(os.path.join(BACKUP_DIR, time.strftime('backup-%Y%m%d-%H%M%S.bin')), 'wb') as f:
                f.write(old)
            bitdo.write_config(dev, make(old))
            return True
        if self.device(run):
            self.load('Configuração aplicada')

    def on_save(self, *_):
        cfg = {'perfis': [page.collect() for page in self.pages]}
        try:
            bitdo.apply(self.raw, cfg)  # valida antes de abrir o controle
        except (ValueError, struct.error) as e:
            self.toast(str(e))
            return
        self.write(lambda old: bitdo.apply(old, cfg))

    def on_backup(self, *_):
        Gtk.FileDialog(initial_name=time.strftime('backup-8bitdo-%Y%m%d.bin')).save(self, None, self.backup_done)

    def backup_done(self, dialog, result):
        try:
            path = dialog.save_finish(result).get_path()
        except GLib.Error:
            return  # cancelado
        raw = self.device(bitdo.read_config)
        if raw:
            with open(path, 'wb') as f:
                f.write(raw)
            self.toast(f'Backup salvo em {path}')

    def on_restore(self, *_):
        Gtk.FileDialog().open(self, None, self.restore_done)

    def restore_done(self, dialog, result):
        try:
            path = dialog.open_finish(result).get_path()
        except GLib.Error:
            return
        data = open(path, 'rb').read()
        if len(data) != bitdo.SIZE:
            self.toast(f'{os.path.basename(path)} não é um backup válido')
            return
        self.write(lambda old: data)


def main():
    app = Adw.Application(application_id='io.github.gabrielpagani.Bitdo')
    app.connect('activate', lambda app: Window(app).present())
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
