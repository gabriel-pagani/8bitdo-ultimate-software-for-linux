#!/usr/bin/env python3
"""Janela para configurar o 8BitDo Ultimate 2.4G (usa o protocolo do bitdo.py)."""
import glob
import math
import os
import struct
import sys
import time
import zipfile

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
KEY_CODES = {304: 'A', 305: 'B', 307: 'X', 308: 'Y', 310: 'LB', 311: 'RB',
             314: 'SELECT', 315: 'START', 316: 'HOME', 317: 'LS', 318: 'RS'}
# Fora do preview: os gatilhos (desenhados pelo eixo) e os botões extras 306/309 que o modo D manda quando
# P1/P2 estão sem função; as pás não têm função própria, o que elas fazem aparece no botão de destino.
IGNORED_KEYS = (306, 309, 312, 313)
# Analógicos e gatilhos vão de 0 a 255; o D-pad (hx/hy) vem como -1, 0 ou 1.
ABS_CODES = {0: 'lx', 1: 'ly', 2: 'rx', 5: 'ry', 9: 'rt', 10: 'lt', 16: 'hx', 17: 'hy'}
ACCENT = (0.21, 0.52, 0.89)  # azul de destaque do libadwaita 1.5

IMG_DIR = os.path.join(BACKUP_DIR, 'imagens')
# Fotos do controle que vêm no instalador do Windows: de frente e de cima (com os gatilhos).
PHOTOS = {'frente': 'Sticks_BG_Ultimate2_4', 'cima': 'Triggers_BG_Ultimate2_4'}
# Posições medidas nas fotos (828 x 664 px): centro e raio dos botões, centro dos analógicos (cabeça de raio 50),
# centro do D-pad (alcance 66) e faixas em x de ombros (y 232 a 306) e gatilhos (y 309 a 405) na foto de cima.
FRONT_BUTTONS = {'Y': (643, 166, 27), 'X': (586, 223, 27), 'B': (699, 222, 27), 'A': (643, 279, 27),
                 'HOME': (414, 156, 24), 'SELECT': (353, 223, 19), 'START': (475, 223, 19)}
STICKS = {'L': (184, 223), 'R': (523, 350)}
DPAD = (304, 349)
BUMPERS = {'LB': (134, 242), 'RB': (589, 697)}
TRIGGERS = {'lt': (138, 236), 'rt': (593, 691)}
TRIGGER_CENTERS = {'lt': (189, 352), 'rt': (640, 352)}  # centro da área de cada gatilho, onde vai o valor


def dotnet_pngs(exe, wanted):
    """PNGs com os nomes pedidos, lidos do .resources embutido num executável .NET."""
    def read7(buf, i):  # inteiro com 7 bits por byte, como o BinaryReader do .NET
        n = shift = 0
        while True:
            b = buf[i]
            i += 1
            n |= (b & 0x7f) << shift
            shift += 7
            if b < 0x80:
                return n, i
    found = {}
    start = exe.find(b'\xce\xca\xef\xbe')  # assinatura de cada bloco .resources
    while start != -1 and len(found) < len(wanted):
        i = start + 8
        i += 4 + struct.unpack_from('<i', exe, i)[0]  # pula os nomes de tipo do leitor
        _, count, types = struct.unpack_from('<iii', exe, i)
        i += 12
        for _ in range(types):
            n, i = read7(exe, i)
            i += n
        i += -(i - start) % 8  # alinhamento de 8 bytes
        positions = struct.unpack_from(f'<{count}i', exe, i + 4 * count)
        i += 8 * count
        data_section, names = struct.unpack_from('<i', exe, i)[0], i + 4
        for pos in positions:
            n, j = read7(exe, names + pos)
            if exe[j:j + n].decode('utf-16-le') in wanted:
                png = exe.find(b'\x89PNG', start + data_section + struct.unpack_from('<i', exe, j + n)[0])
                found[exe[j:j + n].decode('utf-16-le')] = exe[png:exe.find(b'IEND', png) + 8]
        start = exe.find(b'\xce\xca\xef\xbe', start + 4)
    return found


def trigger_mask(top):
    """Tira o azul dos gatilhos da foto de cima (ficam cinza como o plástico) e devolve a máscara do formato deles."""
    top.flush()
    data, stride = top.get_data(), top.get_stride()
    mask = cairo.ImageSurface(cairo.FORMAT_A8, top.get_width(), top.get_height())
    mdata, mstride = mask.get_data(), mask.get_stride()
    for x0, x1 in TRIGGERS.values():
        for y in range(300, 415):
            for x in range(x0 - 5, x1 + 6):
                i = y * stride + 4 * x
                b, g, r = data[i], data[i + 1], data[i + 2]  # ARGB32 na memória: B, G, R, A
                if b > 150 and b - r > 25:
                    gray = (3 * r + 6 * g + b) // 10
                    data[i:i + 3] = bytes((gray, gray, gray))
                    mdata[y * mstride + x] = 255
    top.mark_dirty()
    mask.mark_dirty()
    return mask


def load_photos():
    """As fotos são da 8BitDo: saem do instalador do Windows do usuário (zip em Downloads) para IMG_DIR e
    nunca vão para o repositório. None se o instalador não for encontrado."""
    paths = {k: os.path.join(IMG_DIR, k + '.png') for k in PHOTOS}
    if not all(map(os.path.exists, paths.values())):
        for z in glob.glob(os.path.expanduser('~/Downloads/8BitDo*Ultimate*Software*.zip')):
            try:
                with zipfile.ZipFile(z) as zf:
                    exe = next(n for n in zf.namelist() if n.endswith('Ultimate Software.exe'))
                    pngs = dotnet_pngs(zf.read(exe), set(PHOTOS.values()))
            except (OSError, zipfile.BadZipFile, StopIteration, struct.error, IndexError, UnicodeDecodeError):
                continue
            if len(pngs) == len(PHOTOS):
                os.makedirs(IMG_DIR, exist_ok=True)
                for k, name in PHOTOS.items():
                    with open(paths[k], 'wb') as f:
                        f.write(pngs[name])
                break
        else:
            return None
    photos = {k: cairo.ImageSurface.create_from_png(p) for k, p in paths.items()}
    photos['gatilhos'] = trigger_mask(photos['cima'])
    return photos


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
        super().__init__(hexpand=True, vexpand=True, content_height=360,
                         margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        self.set_draw_func(self.draw)
        self.photos = load_photos()
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
            if typ == EV_KEY and 304 <= code <= 319 and code not in IGNORED_KEYS:
                name = KEY_CODES.get(code, f'botão {code}')
                (self.pressed.add if val else self.pressed.discard)(name)
            elif typ == EV_ABS and code in ABS_CODES:
                name = ABS_CODES[code]
                self.axes[name] = val if name[0] == 'h' else val / 255
        self.queue_draw()
        return True

    def draw(self, area, cr, w, h):
        fg = self.get_color()

        def text(x, y, label, size, alpha=.85, rgb=None):  # Pango: fonte do sistema; rgb troca a cor do tema
            layout = self.create_pango_layout(label)
            font = self.get_pango_context().get_font_description().copy()
            font.set_weight(Pango.Weight.BOLD)
            font.set_absolute_size(size * Pango.SCALE)
            layout.set_font_description(font)
            ink = layout.get_pixel_extents()[0]  # centraliza pelo desenho das letras, não pela altura da linha
            cr.move_to(x - ink.x - ink.width / 2, y - ink.y - ink.height / 2)
            cr.set_source_rgb(*rgb) if rgb else cr.set_source_rgba(fg.red, fg.green, fg.blue, alpha)
            PangoCairo.show_layout(cr, layout)

        if not self.photos:
            text(w / 2, h / 2 - 14, 'Para mostrar o controle, deixe o instalador do Windows da 8BitDo', 15)
            text(w / 2, h / 2 + 12, '(8BitDo-Ultimate-Software-for-Windows.zip) em Downloads e reabra o programa.',
                 13, .6)
            return

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

        def glow():  # destaque do que está ativo: azul translúcido com contorno
            cr.set_source_rgba(*ACCENT, .55)
            cr.fill_preserve()
            cr.set_source_rgb(*ACCENT)
            cr.set_line_width(3)
            cr.stroke()

        # as duas fotos lado a lado, cortadas no contorno do controle:
        # frente (18..810 x 62..625) e cima (73..756 x 146..451)
        fw, fh, tw, th, gap = 792, 563, 683, 305, 40
        total_w, total_h = fw + gap + tw, fh + 60
        s = min(w / total_w, h / total_h)
        cr.translate((w - total_w * s) / 2, (h - total_h * s) / 2)
        cr.scale(s, s)

        cr.save()
        cr.translate(-18, -62)
        cr.rectangle(18, 62, fw, fh)
        cr.clip()
        cr.set_source_surface(self.photos['frente'], 0, 0)
        cr.paint()
        for name, (x, y, r) in FRONT_BUTTONS.items():
            if name in self.pressed:
                circle(x, y, r + 2)
                glow()
        for side, (cx, cy) in STICKS.items():
            dx, dy = (self.axes[side.lower() + 'x'] - .5) * 2, (self.axes[side.lower() + 'y'] - .5) * 2
            if side + 'S' in self.pressed:
                circle(cx, cy, 52)
                glow()
            if math.hypot(dx, dy) > .1:  # inclinado: anel e ponto azuis deslocados para onde aponta
                circle(cx + dx * 22, cy + dy * 22, 50)
                cr.set_source_rgb(*ACCENT)
                cr.set_line_width(4)
                cr.stroke()
                circle(cx + dx * 22, cy + dy * 22, 9)
                cr.fill()
        cx, cy = DPAD
        a, r = 23, 66
        for dx, dy, on in ((0, -1, self.axes['hy'] < 0), (0, 1, self.axes['hy'] > 0),
                           (-1, 0, self.axes['hx'] < 0), (1, 0, self.axes['hx'] > 0)):
            if on:  # acende só o braço apertado
                x0 = cx - a if not dx else (cx - r if dx < 0 else cx + a)
                y0 = cy - a if not dy else (cy - r if dy < 0 else cy + a)
                rounded(x0, y0, r - a if dx else 2 * a, r - a if dy else 2 * a, 6)
                glow()
        cr.restore()

        ox, oy = fw + gap - 73, (fh - th) / 2 - 146
        cr.save()
        cr.translate(ox, oy)
        cr.rectangle(73, 146, tw, th)
        cr.clip()
        cr.set_source_surface(self.photos['cima'], 0, 0)
        cr.paint()
        for name, (x0, x1) in BUMPERS.items():
            if name in self.pressed:
                rounded(x0, 232, x1 - x0, 74, 12)
                glow()
        for name, (x0, x1) in TRIGGERS.items():  # gatilho: enche de baixo para cima no formato real
            value = self.axes[name]
            if value > 0:
                cr.save()
                cr.rectangle(x0 - 6, 405 - 96 * value, x1 - x0 + 12, 96 * value + 6)
                cr.clip()
                cr.set_source_rgba(*ACCENT, .85)
                cr.mask_surface(self.photos['gatilhos'], 0, 0)
                cr.restore()
        cr.restore()
        for name, (cx, cy) in TRIGGER_CENTERS.items():  # valor no meio do gatilho: branco quando o azul chega nele
            value = self.axes[name]
            text(ox + cx, oy + cy, f'{round(value * 100)}%', 24,
                 rgb=(1, 1, 1) if 96 * value > 405 - cy else (.25, .25, .25))

        if self.fd is None:  # sem leitura do controle nada acende: diz o porquê
            text(total_w / 2, fh + 38, 'Conecte o controle pelo cabo com a chave de trás em D', 24)

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
        super().__init__(application=app, title='8BitDo Ultimate 2.4G', default_width=900, default_height=820)
        self.raw = None
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.pages = [ProfilePage() for _ in range(3)]
        for i, page in enumerate(self.pages):
            self.stack.add_titled(page, f'perfil{i + 1}', f'Perfil {i + 1}')
        self.preview = Preview()
        self.stack.add_titled(self.preview, 'previsualizacao', 'Pré-Visualização')

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
