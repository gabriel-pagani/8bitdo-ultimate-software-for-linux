# 8BitDo Ultimate 2.4G no Linux

Configura o controle **8BitDo Ultimate 2.4G** sem o Ultimate Software do Windows: mapeamento dos botões (inclusive as pás traseiras P1/P2), vibração, zona morta dos analógicos e dos gatilhos, inversão de eixos e as demais opções, nos 3 perfis do controle.

Tem uma janela (`bitdo_gui.py`, GTK 4 + libadwaita, que já vêm no GNOME/Zorin) e uma versão de terminal (`bitdo.py`), em Python, sem outras dependências. O protocolo foi extraído do Ultimate Software V2.16 (`8BitDoAdvance.dll`).

## Como funciona

O controle tem uma chave atrás, entre as pás P1 e P2:

- **D (Android):** o controle aparece como gamepad HID e tem o canal de configuração. É o modo que o programa usa, **pelo cabo USB**.
- **X (Windows):** o controle aparece como controle de Xbox, sem canal de configuração. Pelo receptor 2.4G ele só conecta nesse modo.

O controle guarda uma configuração separada para cada posição da chave. Os perfis gravados pelo programa valem com a **chave em D**. A configuração do modo X continua a de fábrica: no Windows, o software da 8BitDo entra nela com uma sequência de vibração que não funcionou no Linux.

## Instalação

Libere o acesso ao controle sem sudo (uma vez só):

```bash
sudo cp 70-8bitdo.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger
```

Para ter o atalho "8BitDo Ultimate" no menu de aplicativos, rode na pasta do projeto:

```bash
printf '[Desktop Entry]\nType=Application\nName=8BitDo Ultimate\nComment=Configurar o controle 8BitDo Ultimate 2.4G\nExec=python3 %s/bitdo_gui.py\nIcon=input-gaming\nCategories=Settings;HardwareSettings;\n' "$PWD" > ~/.local/share/applications/io.github.gabrielpagani.Bitdo.desktop
```

## Uso

1. Coloque a chave de trás em **D** e conecte o controle pelo **cabo USB**, de preferência numa porta direta do computador.
2. Abra **8BitDo Ultimate** no menu de aplicativos (ou `python3 bitdo_gui.py`). A janela lê o controle e mostra os 3 perfis em abas.
3. Ajuste o perfil e clique em **Gravar no controle**. Antes de gravar, o programa salva um backup automático em `~/.local/share/8bitdo-ultimate/`. O menu (☰) salva e restaura backups.
4. Escolha o perfil no **botão de perfil** do controle: o programa grava os perfis, mas quem escolhe o perfil em uso é o controle.

### No terminal

Antes de mudar qualquer coisa, salve a configuração atual com `python3 bitdo.py backup original.bin`. Depois exporte, edite e grave:

```
python3 bitdo.py info                 # versão do firmware e resumo dos perfis (só lê)
python3 bitdo.py exportar perfis.json # salva os 3 perfis num JSON editável
python3 bitdo.py importar perfis.json # grava o JSON no controle (faz backup antes)
python3 bitdo.py restaurar original.bin
```

## Formato do JSON (terminal)

Cada um dos 3 perfis tem:

- `nome`: até 16 caracteres.
- `ativo`: `true` liga o perfil personalizado; `false` o desliga (o software original mostra o padrão de fábrica nesse caso).
- `botoes`: a função de cada botão físico (`A B X Y LB RB LT RT LS RS SELECT START STAR HOME UP DOWN LEFT RIGHT P1 P2`). Funções aceitas: os próprios nomes dos botões, `NONE` (desativa), `TURBO`, `TURBO_SINGLE`, `TURBO_AUTO`, `SCREENSHOT` e `SWAP`. SELECT e START não são remapeáveis no software original.
- `vibracao`: `esquerda` e `direita`, de 0 (desligada) a 5 (máxima).
- `analogicos`: `inicio` é a zona morta interna e `fim` é o ponto de deflexão máxima (padrão 0 e 128).
- `gatilhos`: `inicio` é onde o gatilho começa a registrar e `fim` é o ponto de pressão máxima (padrão 0 e 255).
- `opcoes`: inverter eixos, trocar analógicos, trocar gatilhos, gatilhos digitais, D-pad só 4 direções, desativar zona morta etc.

O campo `modo` no topo só informa a plataforma atual e é ignorado na importação.

## O que não faz

- Configurar o modo X (Windows) nem configurar pelo receptor 2.4G.
- Atualizar firmware: use o <https://web.8bitdo.com/> no Chrome ou Chromium. O site não reconheceu o receptor no modo normal.
- Macros: o Ultimate 2.4G não tem (o software original também as esconde para esse modelo).

## Teste

`python3 test_bitdo.py` roda o protocolo contra um controle simulado.
