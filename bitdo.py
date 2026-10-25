#!/usr/bin/env python3
"""Configura o 8BitDo Ultimate 2.4G no Linux, pelo cabo USB com a chave de trás em D.

Reimplementa o protocolo do 8BitDo Ultimate Software V2.16 (8BitDoAdvance.dll):
a configuração é um bloco de 1652 bytes (custom_config_record_t) com 3 perfis,
lido e gravado em pedaços de 45 bytes pelo relatório HID 0x81 (resposta no 0x02).

O controle guarda um bloco por posição da chave. Com a chave em X (Windows, e sempre
pelo receptor) ele vira um controle de Xbox sem canal de configuração: no Windows o
software entra nesse modo com uma sequência de vibração que não funcionou no Linux.
"""
import glob
import json
import os
import select
import struct
import sys
import time

PID = 0x3012  # Ultimate 2.4G no cabo com a chave em D (Android)
SIZE = 0x674
CHUNK = 45
ENABLED = 0x20200911  # Ultimate2_4AdvanceUI.enableFlag; desativado = 0

# Offsets dentro do custom_config_record_t (3 registros de cada).
O_FLAG, O_CRC, O_MODE, O_NAME = 0, 12, 16, 20  # o cur_slot (18) o controle ignora
O_RUMBLE, O_STICK, O_TRIG, O_FEAT, O_MAP = 116, 152, 176, 200, 224  # o resto (macros) não é usado no 2.4G
MODES = {0: 'switch', 1: 'android', 3: 'windows (x-input)'}

# Ordem dos 20 botões físicos no mapa (MAP_KEY_E + P1/P2).
BUTTONS = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'LS', 'RS', 'SELECT', 'START',
           'STAR', 'HOME', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'P1', 'P2']
TARGETS = {'NONE': 0, 'START': 1, 'LS': 2, 'RS': 4, 'SELECT': 8, 'X': 0x10, 'Y': 0x20,
           'RIGHT': 0x40, 'LEFT': 0x80, 'DOWN': 0x100, 'UP': 0x200, 'LB': 0x400, 'RB': 0x800,
           'B': 0x1000, 'A': 0x2000, 'LT': 0x4000, 'HOME': 0x8000, 'TURBO': 0x10000, 'RT': 0x20000,
           'SCREENSHOT': 0x400000, 'TURBO_SINGLE': 0x800000, 'TURBO_AUTO': 0x1000000,
           'P1': 0x2000000, 'P2': 0x4000000, 'SWAP': 0x8000000}
NAMES = {v: k for k, v in TARGETS.items()}
OPTIONS = {'inverter_x_esquerdo': 0x1, 'inverter_y_esquerdo': 0x2, 'inverter_x_direito': 0x4,
           'inverter_y_direito': 0x8, 'trocar_analogicos': 0x10, 'trocar_gatilhos': 0x80,
           'trocar_dpad_e_analogico_esquerdo': 0x100, 'gatilhos_digitais': 0x200,
           'trocar_analogico_direito_e_gatilhos': 0x400, 'sensibilidade_de_movimento': 0x800,
           'desativar_zona_morta': 0x1000, 'dpad_so_4_direcoes': 0x2000,
           'switch_dormir_na_base': 0x4000, 'switch_acordar_ao_tirar_da_base': 0x8000}


class Hid:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR)

    def close(self):
        os.close(self.fd)

    def write(self, data):
        os.write(self.fd, bytes(data).ljust(64, b'\0'))

    def read(self, timeout):
        if select.select([self.fd], [], [], timeout)[0]:
            return os.read(self.fd, 64)


def header(cmd, sub=0, length=0, total=0, offset=0):
    return struct.pack('<HHIII', cmd, sub, length, total, offset)


def wait(dev, match, timeout=1.0):
    end = time.monotonic() + timeout
    while (left := end - time.monotonic()) > 0:
        r = dev.read(left)
        if r and match(r):
            return r


def send(dev, packet):
    while dev.read(0):  # descarta respostas antigas
        pass
    dev.write(bytes([0x81, len(packet) + 1, 4]) + packet)


def reply(dev, cmd, sub, timeout=1.0):
    """Espera '02 04 <cmd> <sub> <len> ...' e devolve (len, dados)."""
    r = wait(dev, lambda r: r[:2] == b'\x02\x04' and struct.unpack_from('<HH', r, 2) == (cmd, sub), timeout)
    if r:
        n = struct.unpack_from('<I', r, 6)[0]
        return n, r[18:18 + n]


def version(dev):
    for _ in range(5):
        while dev.read(0):
            pass
        dev.write(b'\x81\x05\x00\x21\x01')
        r = wait(dev, lambda r: r[:2] == b'\x02\x22')
        if r:
            return (r[2] | r[3] << 8) / 100


def read_config(dev):
    data, retries = bytearray(), 0
    while len(data) < SIZE:
        n = min(SIZE - len(data), CHUNK)
        send(dev, header(2, 0, n, SIZE, len(data)) + bytes(n))
        got = reply(dev, 4, 2)
        if got and got[0]:
            data += got[1]
            retries = 0
        else:
            retries += 1
            if retries >= 30:
                raise IOError('o controle não respondeu à leitura')
    return bytes(data[:SIZE])


def write_config(dev, data):
    off = retries = 0
    while off < SIZE:
        n = min(SIZE - off, CHUNK)
        send(dev, header(1, 0, n, SIZE, off) + data[off:off + n])
        got = reply(dev, 4, 1)
        if got and got[0]:
            off += got[0]
            retries = 0
        else:
            retries += 1
            if retries >= 30:
                raise IOError('o controle não confirmou a gravação')
    send(dev, header(6, 0x15))  # aplica a configuração gravada
    if not reply(dev, 4, 6, timeout=3):
        raise IOError('o controle não confirmou a gravação')


def crc_config(raw):
    """ANSI_CRC_16_Ultimate2_4: CRC-16 (poly 0x8408, init 0xFFFF) com os bytes trocados."""
    crc = 0xFFFF
    for b in raw:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return ((crc >> 8) | (crc << 8)) & 0xFFFF


def export(raw):
    mode = struct.unpack_from('<H', raw, O_MODE)[0]
    star = TARGETS['SCREENSHOT'] if mode == 0 else TARGETS['TURBO']
    default_keys = [TARGETS[b] for b in BUTTONS[:12]] + [star] + [TARGETS[b] for b in BUTTONS[13:18]] + [0, 0]
    profiles = []
    for i in range(3):
        def on(base, size):  # registro não habilitado = padrão de fábrica (como o software original)
            return struct.unpack_from('<I', raw, base + i * size)[0] == ENABLED
        keys = struct.unpack_from('<20I', raw, O_MAP + i * 84 + 4) if on(O_MAP, 84) else default_keys
        rumble = struct.unpack_from('<2f', raw, O_RUMBLE + i * 12 + 4) if on(O_RUMBLE, 12) else (1.0, 1.0)
        sticks = struct.unpack_from('<4B', raw, O_STICK + i * 8 + 4) if on(O_STICK, 8) else (0, 128, 0, 128)
        trig = struct.unpack_from('<4B', raw, O_TRIG + i * 8 + 4) if on(O_TRIG, 8) else (0, 255, 0, 255)
        feat = struct.unpack_from('<I', raw, O_FEAT + i * 8 + 4)[0] if on(O_FEAT, 8) else 0
        name = raw[O_NAME + i * 32:O_NAME + i * 32 + 32]
        profiles.append({
            'nome': '' if name in (bytes(32), b'\xff' * 32) else name.decode('utf-16-le', 'replace').split('\0')[0],
            'ativo': struct.unpack_from('<I', raw, O_FLAG + i * 4)[0] == ENABLED,
            'botoes': {b: NAMES.get(k, hex(k)) for b, k in zip(BUTTONS, keys)},
            'vibracao': {'esquerda': level(rumble[0]), 'direita': level(rumble[1])},
            'analogicos': {'esquerdo': {'inicio': sticks[0], 'fim': sticks[1]},
                           'direito': {'inicio': sticks[2], 'fim': sticks[3]}},
            'gatilhos': {'esquerdo': {'inicio': trig[0], 'fim': trig[1]},
                         'direito': {'inicio': trig[2], 'fim': trig[3]}},
            'opcoes': {k: bool(feat & bit) for k, bit in OPTIONS.items()},
        })
    return {'modo': MODES.get(mode, mode), 'perfis': profiles}


def level(f):
    return max(0, min(5, int(f * 5 + 1e-4))) if f == f else 5  # NaN = flash apagada


def target(v):
    if v in TARGETS:
        return TARGETS[v]
    if isinstance(v, str) and v.startswith('0x'):
        return int(v, 16)
    raise ValueError(f'função de botão desconhecida: {v!r} (use uma de {", ".join(TARGETS)})')


def apply(raw, cfg):
    raw = bytearray(raw)
    if len(cfg['perfis']) > 3:
        raise ValueError('são no máximo 3 perfis')
    for i, p in enumerate(cfg['perfis']):
        if set(p['botoes']) != set(BUTTONS):
            raise ValueError(f'perfil {i + 1}: "botoes" precisa ter exatamente {", ".join(BUTTONS)}')
        vib = [p['vibracao']['esquerda'], p['vibracao']['direita']]
        if not all(v in range(6) for v in vib):
            raise ValueError(f'perfil {i + 1}: vibração vai de 0 a 5')
        a, g = p['analogicos'], p['gatilhos']
        if not all(0 <= a[s][k] <= 128 for s in a for k in a[s]):
            raise ValueError(f'perfil {i + 1}: analógicos vão de 0 a 128')
        name = p['nome'].encode('utf-16-le')[:32]
        raw[O_NAME + i * 32:O_NAME + i * 32 + 32] = name.ljust(32, b'\0')
        struct.pack_into('<20I', raw, O_MAP + i * 84 + 4, *(target(p['botoes'][b]) for b in BUTTONS))
        struct.pack_into('<2f', raw, O_RUMBLE + i * 12 + 4, *(v * 0.2 for v in vib))
        struct.pack_into('<4B', raw, O_STICK + i * 8 + 4, a['esquerdo']['inicio'], a['esquerdo']['fim'],
                         a['direito']['inicio'], a['direito']['fim'])
        struct.pack_into('<4B', raw, O_TRIG + i * 8 + 4, g['esquerdo']['inicio'], g['esquerdo']['fim'],
                         g['direito']['inicio'], g['direito']['fim'])
        feat = struct.unpack_from('<I', raw, O_FEAT + i * 8 + 4)[0]
        for k, on in p['opcoes'].items():
            feat = feat | OPTIONS[k] if on else feat & ~OPTIONS[k]
        struct.pack_into('<I', raw, O_FEAT + i * 8 + 4, feat)
        flag = ENABLED if p['ativo'] else 0
        struct.pack_into('<I', raw, O_FLAG + i * 4, flag)
        for base, size in ((O_MAP, 84), (O_RUMBLE, 12), (O_STICK, 8), (O_TRIG, 8), (O_FEAT, 8), (476, 392)):
            struct.pack_into('<I', raw, base + i * size, flag)  # 476 = macro_fun, que o 2.4G não usa
    struct.pack_into('<I', raw, O_CRC, crc_config(raw))
    return bytes(raw)


def find_hidraw():
    """/dev/hidrawN do canal de configuração (relatório de saída 0x81) do controle no cabo em D."""
    for p in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        if f'HID_ID=0003:00002DC8:0000{PID:04X}' in open(p + '/device/uevent').read() and \
                b'\x85\x81' in open(p + '/device/report_descriptor', 'rb').read():
            return '/dev/' + os.path.basename(p)


def connect():
    path = find_hidraw()
    if not path:
        raise IOError('Controle não encontrado: conecte o Ultimate 2.4G pelo cabo USB com a chave de trás '
                      '(entre P1 e P2) em D.')
    try:
        dev = Hid(path)
    except PermissionError:
        raise IOError(f'Sem permissão em {path}: instale a regra udev (70-8bitdo.rules) e reconecte o cabo.') from None
    send(dev, header(7, 0))  # pausa o envio de teclas pelo canal de configuração
    time.sleep(0.1)
    return dev


USAGE = """uso: bitdo.py <comando>
  info                 versão do firmware e resumo dos perfis
  exportar ARQ.json    salva os 3 perfis num JSON editável
  importar ARQ.json    grava o JSON no controle (faz backup antes)
  backup ARQ.bin       salva a configuração bruta
  restaurar ARQ.bin    grava uma configuração bruta salva antes"""


def main():
    cmd, *args = sys.argv[1:] or ['']
    if (cmd, len(args)) not in (('info', 0), ('exportar', 1), ('importar', 1), ('backup', 1), ('restaurar', 1)):
        sys.exit(USAGE)
    if cmd == 'importar':
        try:
            cfg = json.load(open(args[0]))
            apply(bytes(SIZE), cfg)  # valida antes de mexer no controle
        except (OSError, KeyError, TypeError, ValueError, struct.error) as e:
            sys.exit(f'Erro em {args[0]}: {e!r}')
    if cmd == 'restaurar':
        new = open(args[0], 'rb').read()
        if len(new) != SIZE:
            sys.exit(f'{args[0]} não é um backup válido ({len(new)} bytes, esperado {SIZE})')
    try:
        dev = connect()
    except OSError as e:
        sys.exit(str(e))
    try:
        if cmd == 'info':
            print(f'Firmware: {version(dev)}')
            cfg = export(read_config(dev))
            print(f'Modo: {cfg["modo"]}')
            for i, p in enumerate(cfg['perfis'], 1):
                print(f'  Perfil {i}: {p["nome"] or "(sem nome)"} {"[personalizado]" if p["ativo"] else "[padrão]"}')
        elif cmd == 'exportar':
            json.dump(export(read_config(dev)), open(args[0], 'w'), indent=2, ensure_ascii=False)
            print(f'Perfis salvos em {args[0]}')
        elif cmd == 'backup':
            open(args[0], 'wb').write(read_config(dev))
            print(f'Backup salvo em {args[0]}')
        else:
            old = read_config(dev)
            bak = time.strftime('backup-%Y%m%d-%H%M%S.bin')
            open(bak, 'wb').write(old)
            print(f'Configuração atual salva em {bak}')
            write_config(dev, apply(old, cfg) if cmd == 'importar' else new)
            print('Gravado. Confira com: bitdo.py exportar conferir.json')
    finally:
        dev.close()


if __name__ == '__main__':
    main()
