#!/usr/bin/env python3
"""Janela para configurar o 8BitDo Ultimate 2.4G (usa o protocolo do bitdo.py)."""
import glob
import math
import os
import struct
import sys
import time

import cairo
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Adw, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

import bitdo  # noqa: E402

BACKUP_DIR = os.path.expanduser('~/.local/share/8bitdo-ultimate')
DEFAULT = bitdo.export(b'\xff' * bitdo.SIZE)['perfis'][0]  # flash apagada = padrão de fábrica

# Como os botões aparecem impressos no controle.
BUTTON_LABELS = {'LS': 'LSB', 'RS': 'RSB', 'SELECT': '−', 'START': '+', 'STAR': '★', 'HOME': 'Home',
                 'UP': '↑', 'DOWN': '↓', 'LEFT': '←', 'RIGHT': '→'}
# Nas listas de ação − e + sozinhos não dizem nada: lá vale o nome da função.
FUNCTION_LABELS = {**BUTTON_LABELS, 'SELECT': 'Select', 'START': 'Start', 'NONE': 'Desativado', 'TURBO': 'Turbo',
                   'TURBO_SINGLE': 'Turbo (um toque)', 'TURBO_AUTO': 'Turbo automático',
                   'SCREENSHOT': 'Captura de tela', 'SWAP': 'Swap'}
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

# O que o controle envia ao sistema no modo D (evdev), já com o perfil ativo aplicado pelo firmware.
EV_KEY, EV_ABS = 1, 3
# Medido no controle real; LT/RT (312/313) também chegam como eixo de pressão, que é o que o desenho usa.
KEY_CODES = {304: 'A', 305: 'B', 306: 'P1', 307: 'X', 308: 'Y', 309: 'P2', 310: 'LB', 311: 'RB',
             314: 'SELECT', 315: 'START', 316: 'HOME', 317: 'LS', 318: 'RS'}
# Analógicos e gatilhos vão de 0 a 255; o D-pad (hx/hy) vem como -1, 0 ou 1.
ABS_CODES = {0: 'lx', 1: 'ly', 2: 'rx', 5: 'ry', 9: 'rt', 10: 'lt', 16: 'hx', 17: 'hy'}
ACCENT = (0.21, 0.52, 0.89)  # azul de destaque do libadwaita 1.5


def find_event():
    """/dev/input/eventN do controle no cabo com a chave em D."""
    for p in glob.glob('/sys/class/input/event*'):
        try:
            if open(p + '/device/id/vendor').read().strip() == '2dc8' and \
                    int(open(p + '/device/id/product').read(), 16) == bitdo.PID:
                return '/dev/input/' + os.path.basename(p)
        except OSError:
            pass


class Preview(Gtk.DrawingArea):
    """Desenho do controle que acende o que ele está enviando agora: botões, gatilhos, analógicos e D-pad."""

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, content_height=400)
        self.set_draw_func(self.draw)
        self.fd = self.watch = None
        self.reset()

    def reset(self):
        self.pressed = set()
        self.axes = {'lx': .5, 'ly': .5, 'rx': .5, 'ry': .5, 'lt': 0, 'rt': 0, 'hx': 0, 'hy': 0}

    def open(self):
        self.close()
        path = find_event()
        if path:
            self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            self.watch = GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, self.fd,
                                               GLib.IOCondition.IN | GLib.IOCondition.HUP, self.on_input)
        self.queue_draw()

    def close(self):
        if self.watch:
            GLib.source_remove(self.watch)
        if self.fd is not None:
            os.close(self.fd)
        self.fd = self.watch = None
        self.reset()

    def on_input(self, fd, condition):
        try:
            data = os.read(fd, 24 * 64)
        except BlockingIOError:
            return True
        except OSError:  # controle desconectado
            data = b''
        if not data:
            self.watch = None
            self.close()
            self.queue_draw()
            return False
        for i in range(0, len(data) - 23, 24):
            _, _, typ, code, val = struct.unpack_from('<qqHHi', data, i)
            if typ == EV_KEY and 304 <= code <= 319 and code not in (312, 313):
                name = KEY_CODES.get(code, f'botão {code}')
                (self.pressed.add if val else self.pressed.discard)(name)
            elif typ == EV_ABS and code in ABS_CODES:
                name = ABS_CODES[code]
                self.axes[name] = val if name[0] == 'h' else val / 255
        self.queue_draw()
        return True

    def draw(self, area, cr, w, h):
        fg = self.get_color()
        s = min(w / 600, h / 400)
        cr.translate((w - 600 * s) / 2, (h - 400 * s) / 2)
        cr.scale(s, s)

        def ink(alpha):
            cr.set_source_rgba(fg.red, fg.green, fg.blue, alpha)

        def text(x, y, label, size, on=False):  # Pango: fonte do sistema e símbolos como − e ↑
            layout = self.create_pango_layout(label)
            font = self.get_pango_context().get_font_description().copy()
            font.set_weight(Pango.Weight.BOLD)
            font.set_absolute_size(size * Pango.SCALE)
            layout.set_font_description(font)
            tw, th = layout.get_pixel_size()
            cr.move_to(x - tw / 2, y - th / 2)
            cr.set_source_rgb(1, 1, 1) if on else ink(.85)
            PangoCairo.show_layout(cr, layout)

        def rounded(x, y, rw, rh, r):
            cr.new_path()
            cr.arc(x + rw - r, y + r, r, -math.pi / 2, 0)
            cr.arc(x + rw - r, y + rh - r, r, 0, math.pi / 2)
            cr.arc(x + r, y + rh - r, r, math.pi / 2, math.pi)
            cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()

        def circle(x, y, r):
            cr.new_path()
            cr.arc(x, y, r, 0, 2 * math.pi)

        def paint(on, idle=.14):  # azul quando ativo, tom do tema quando não
            cr.set_source_rgb(*ACCENT) if on else ink(idle)
            cr.fill()

        def button(x, y, r, name, size=13):
            on = name in self.pressed
            if on:  # brilho em volta
                circle(x, y, r + 5)
                cr.set_source_rgba(*ACCENT, .3)
                cr.fill()
            circle(x, y, r)
            paint(on)
            text(x, y, BUTTON_LABELS.get(name, name), size, on)

        def pill(x, y, pw, ph, name, label_y):
            on = name in self.pressed
            rounded(x, y, pw, ph, ph / 2)
            paint(on, .18)
            text(x + pw / 2, label_y, BUTTON_LABELS.get(name, name), 12, on)

        # atrás do corpo: gatilhos (enchem na proporção exata da pressão), ombros e pás traseiras
        for name, x in (('lt', 122), ('rt', 372)):
            value = self.axes[name]
            rounded(x, 14, 106, 56, 16)
            ink(.10)
            cr.fill_preserve()
            cr.save()
            cr.clip()
            cr.rectangle(x, 14, 106 * value, 56)
            cr.set_source_rgb(*ACCENT)
            cr.fill()
            cr.restore()
            text(x + 53, 36, f'{name.upper()} {round(value * 100)}%', 12, value > .5)
        pill(108, 58, 134, 34, 'LB', 72)
        pill(358, 58, 134, 34, 'RB', 72)
        pill(224, 266, 48, 26, 'P2', 279)  # vistas de frente: P2 à esquerda, P1 à direita
        pill(328, 266, 48, 26, 'P1', 279)

        # corpo com pegadas, simétrico em torno de x = 300
        right = [((360, 92), (400, 84), (450, 90)), ((500, 96), (530, 120), (545, 170)),
                 ((560, 230), (565, 300), (540, 335)), ((520, 362), (478, 362), (462, 335)),
                 ((445, 305), (420, 262), (380, 258))]
        cr.new_path()
        cr.move_to(300, 92)
        for c1, c2, end in right:
            cr.curve_to(*c1, *c2, *end)
        cr.curve_to(345, 255, 255, 255, 220, 258)
        points = [(300, 92)] + [p for seg in right for p in seg]
        for i in range(len(points) - 1, 0, -3):  # mesmo contorno espelhado, percorrido de volta
            (x1, y1), (x2, y2), (x0, y0) = points[i - 1], points[i - 2], points[i - 3]
            cr.curve_to(600 - x1, y1, 600 - x2, y2, 600 - x0, y0)
        cr.close_path()
        shade = cairo.LinearGradient(0, 85, 0, 360)
        shade.add_color_stop_rgba(0, fg.red, fg.green, fg.blue, .16)
        shade.add_color_stop_rgba(1, fg.red, fg.green, fg.blue, .07)
        cr.set_source(shade)
        cr.fill_preserve()
        ink(.12)
        cr.set_line_width(1.5)
        cr.stroke()

        for name, cx, cy in (('LS', 172, 150), ('RS', 364, 222)):  # analógicos: base funda e cabeça que se move
            circle(cx, cy, 36)
            ink(.12)
            cr.fill()
            k = name[0].lower()
            x, y = cx + (self.axes[k + 'x'] - .5) * 32, cy + (self.axes[k + 'y'] - .5) * 32
            button(x, y, 24, name, 11)
            circle(x, y, 18)
            ink(.10)
            cr.set_line_width(1.5)
            cr.stroke()

        cx, cy, a, r = 236, 222, 13, 33  # D-pad em cruz
        cr.new_path()
        for px, py in ((-a, -r), (a, -r), (a, -a), (r, -a), (r, a), (a, a), (a, r), (-a, r), (-a, a), (-r, a),
                       (-r, -a), (-a, -a)):
            cr.line_to(cx + px, cy + py)
        cr.close_path()
        ink(.14)
        cr.fill()
        for dx, dy, on in ((0, -1, self.axes['hy'] < 0), (0, 1, self.axes['hy'] > 0),
                           (-1, 0, self.axes['hx'] < 0), (1, 0, self.axes['hx'] > 0)):
            if on:  # acende só o braço apertado
                x0 = cx - a if not dx else (cx - r if dx < 0 else cx + a)
                y0 = cy - a if not dy else (cy - r if dy < 0 else cy + a)
                cr.rectangle(x0, y0, r - a if dx else 2 * a, r - a if dy else 2 * a)
                cr.set_source_rgb(*ACCENT)
                cr.fill()
            cr.new_path()  # seta apontando para fora
            cr.move_to(cx + dx * 28, cy + dy * 28)
            cr.line_to(cx + dx * 19 - dy * 6, cy + dy * 19 - dx * 6)
            cr.line_to(cx + dx * 19 + dy * 6, cy + dy * 19 + dx * 6)
            cr.close_path()
            cr.set_source_rgb(1, 1, 1) if on else ink(.6)
            cr.fill()

        for name, x, y in (('Y', 428, 121), ('A', 428, 179), ('X', 399, 150), ('B', 457, 150)):
            button(x, y, 15, name)
        button(300, 116, 16, 'HOME', 9)
        button(262, 160, 11, 'SELECT')
        button(300, 160, 11, 'STAR', 12)  # o ★ não envia nada ao sistema, então nunca acende
        button(338, 160, 11, 'START')

        if self.fd is None:
            status = 'Conecte o controle pelo cabo com a chave de trás em D'
        else:
            active = [FUNCTION_LABELS.get(n, n) for n in sorted(self.pressed, key=str)]
            active += [f'{n.upper()} {round(self.axes[n] * 100)}%' for n in ('lt', 'rt') if self.axes[n] > 0]
            status = 'Enviando: ' + ', '.join(active) if active else 'Aperte um botão no controle'
        text(300, 384, status, 14)

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
        self.preview = Preview()
        test = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                       margin_start=18, margin_end=18)
        test.append(Gtk.Label(label='Mostra o que o controle está enviando agora, já com o perfil ativo. '
                                    'Troque de perfil no botão de perfil do controle.',
                              wrap=True, css_classes=['dim-label']))
        test.append(self.preview)
        self.stack.add_titled(test, 'teste', 'Teste')

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
            bitdo.disconnect(dev)

    def load(self, message=None):
        got = self.device(lambda dev: (bitdo.version(dev), bitdo.read_config(dev)))
        if not got:
            return
        firmware, self.raw = got
        for page, p in zip(self.pages, bitdo.export(self.raw)['perfis']):
            page.fill(p)
        self.main.set_visible_child_name('editor')
        self.preview.open()
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
    app.connect('activate', lambda app: (app.get_active_window() or Window(app)).present())
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
