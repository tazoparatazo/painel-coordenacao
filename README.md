# Painel da Coordenação

Painel gerado a partir do Asana. O GitHub roda o script de hora em hora (8h às 20h, segunda a sexta) e publica o resultado num link fixo, protegido por senha.

## Como funciona

1. O GitHub Actions roda `painel_coordenacao.py`, que busca os dados no Asana.
2. O painel gerado é criptografado com a senha (StatiCrypt). Sem a senha, o conteúdo não pode ser lido.
3. O resultado é publicado no GitHub Pages: `https://SEU-USUARIO.github.io/painel-coordenacao/`

## Segredos necessários (Settings > Secrets and variables > Actions)

| Nome | Valor |
|---|---|
| `ASANA_TOKEN` | Token pessoal do Asana |
| `PAINEL_CLIENTES` | Lista de clientes e projetos em JSON |
| `PAINEL_SENHA` | Senha que a coordenação vai usar para abrir o painel |

Os nomes dos clientes e o token ficam só nos segredos, nunca no código.

## Atualizar na hora

Aba **Actions** > **Atualizar painel da coordenação** > **Run workflow**.

## Mudar regras

As regras (dias de risco, atraso antigo, abas visíveis) ficam no topo de `painel_coordenacao.py`.
Para adicionar ou tirar clientes, edite o segredo `PAINEL_CLIENTES`.
