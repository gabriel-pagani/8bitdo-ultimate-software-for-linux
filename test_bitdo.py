"""Testa o protocolo contra um controle simulado: python3 test_bitdo.py"""
import struct

import bitdo


class FakeController:
    """Lado do firmware: responde aos pacotes 81 <len> 04 <header> <dados> como o controle."""

    def __init__(self, mem):
        self.mem, self.staged, self.out = bytearray(mem), bytearray(mem), []

    def write(self, data):
        data = bytes(data).ljust(64, b'\0')  # o Hid real completa até 64
        assert data[0] == 0x81
        if data[1:5] == b'\x05\x00\x21\x01':
            self.out.append(b'\x02\x22\xcc\x00'.ljust(64, b'\0'))  # versão 2.04
            return
        assert data[2] == 4 and data[1] == 16 + 1 + struct.unpack_from('<I', data, 7)[0]
        cmd, sub, n, total, off = struct.unpack_from('<HHIII', data, 3)
        if cmd == 2:
            self.out.append(b'\x02\x04' + bitdo.header(4, 2, n) + self.mem[off:off + n])
        elif cmd == 1:
            assert total == bitdo.SIZE
            self.staged[off:off + n] = data[19:19 + n]
            self.out.append(b'\x02\x04' + bitdo.header(4, 1, n))
        elif cmd == 6 and sub == 0x15:
            self.mem[:] = self.staged
            self.out.append(b'\x02\x04' + bitdo.header(4, 6))

    def read(self, timeout):
        return self.out.pop(0).ljust(64, b'\0') if self.out else None


def test_roundtrip():
    # Flash apagada: export mostra o padrão de fábrica, como o software original.
    dev = FakeController(b'\xff' * bitdo.SIZE)
    assert bitdo.version(dev) == 2.04
    blank = bitdo.read_config(dev)
    cfg = bitdo.export(blank)
    p = cfg['perfis'][0]
    assert not p['ativo'] and p['botoes']['A'] == 'A' and p['botoes']['P1'] == 'NONE'
    assert p['vibracao'] == {'esquerda': 5, 'direita': 5} and p['analogicos']['esquerdo'] == {'inicio': 0, 'fim': 128}

    # Edita o perfil 2 e grava.
    p = cfg['perfis'][1]
    p.update(nome='Jogo', ativo=True)
    p['botoes'].update(A='B', B='A', P1='LB')
    p['vibracao']['direita'] = 2
    p['gatilhos']['direito'] = {'inicio': 10, 'fim': 200}
    p['opcoes']['trocar_analogicos'] = True
    bitdo.write_config(dev, bitdo.apply(blank, cfg))

    raw = bytes(dev.mem)
    assert raw[476 + 3 * 392 - 1] == 0xff and len(raw) == bitdo.SIZE  # macros intactas
    assert struct.unpack_from('<I', raw, bitdo.O_MAP + 84 + 4)[0] == bitdo.TARGETS['B']
    got = bitdo.export(bitdo.read_config(dev))
    assert got['perfis'][1] == p
    assert got['perfis'][0] == bitdo.export(blank)['perfis'][0]

    cfg['perfis'][1]['botoes']['A'] = 'PULO'
    try:
        bitdo.apply(blank, cfg)
        raise AssertionError('aceitou botão inválido')
    except ValueError:
        pass


if __name__ == '__main__':
    test_roundtrip()
    print('ok')
