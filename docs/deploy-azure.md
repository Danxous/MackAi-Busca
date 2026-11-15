# Deploy do mackai-busca no Azure

Complementa o guia do grupo ([MackAi-Conversa/docs/deploy-azure.md](https://github.com/gabrielmarinhorosa/MackAi-Conversa/blob/main/docs/deploy-azure.md)),
Partes 1.4, 2.3, 2.4 e 5. O banco `busca_db`, a extensão `VECTOR` em `azure.extensions` e o ambiente
`mackai-env` já existem. O `CREATE EXTENSION IF NOT EXISTS vector` roda sozinho quando o serviço inicia
(ver [schema.sql](../busca_semantica/schema.sql)).

## 1. Imagem no GitHub Container Registry

1. Faça merge na `main`. O workflow `ci` roda os testes, monta `conhecimento/` a partir de `fontes.json` e
   publica `ghcr.io/danxous/mackai-busca:latest` e uma tag com o commit (7 caracteres).
2. Na primeira vez, deixe o pacote público: GitHub → seu perfil → **Packages** → `mackai-busca` →
   **Package settings** → **Danger Zone** → **Change visibility** → **Public**. O código já é público e a
   imagem não leva segredos: banco e chave ficam no Azure.

## 2. Acesso ao `mackai-rg` (Parte 1.4)

1. Entre em [portal.azure.com](https://portal.azure.com) com a conta da faculdade.
2. **Engrenagem → Diretórios + assinaturas**: confira o diretório da faculdade e marque, no filtro de
   assinatura, a assinatura **Azure for Students** do dono (confira pelo ID que ele enviar).
3. Busque **Grupos de recursos** e confira se o `mackai-rg` aparece.

## 3. Criar o Container App

1. **Aplicativos de Contêiner → + Criar → Aplicativo de Contêiner**.
2. **Básico:** grupo `mackai-rg`, nome **`mackai-busca`** (exato: vira o endereço `http://mackai-busca`
   que o Orquestrador chama), origem **Imagem de contêiner**, mesma região dos outros recursos e o ambiente
   **`mackai-env` existente** (não crie outro).
3. **Contêiner:** marque **Usar imagem de início rápido**. A imagem real entra na etapa 5.
4. **Entrada:** habilitada, **Limitada ao Ambiente de Aplicativos de Contêiner** (interno), HTTP, porta 80
   por enquanto, porque a imagem de início rápido usa a 80.
5. **Revisar + criar → Criar**.

## 4. Segredos

Em **Configurações → Segredos → + Adicionar**:

| Chave | Valor |
|---|---|
| `database-url` | Cadeia do `busca_db` que o Gabriel envia em mensagem privada (`postgresql://mackai:<SENHA>@<servidor>.postgres.database.azure.com:5432/busca_db?sslmode=require`) |
| `gemini-api-key` | Cadastrada pelo Lucas. Ninguém mais vê a chave |

A cadeia nunca vai para o repositório nem para grupo aberto. Se a senha tiver `@`, `:` ou `/`, codifique (`@` vira `%40`).

## 5. Imagem, recursos, variáveis e porta

1. **Aplicativo → Contêineres → Editar e implantar**, selecione o contêiner e clique em **Editar**.
2. Imagem: **Docker Hub ou outros registros**, **Público**, servidor `ghcr.io`, imagem `danxous/mackai-busca:latest`.
3. Recursos: CPU **0,25**, memória **0,5 Gi**.
4. Variáveis de ambiente:

   | Nome | Origem | Valor |
   |---|---|---|
   | `DATABASE_URL` | Referenciar um segredo | `database-url` |
   | `GEMINI_API_KEY` | Referenciar um segredo | `gemini-api-key` |

   Os demais valores (`EMBEDDING_MODEL`, limiares e `REINDEX_ON_STARTUP=true`) já têm padrão. Só crie a
   variável se for mudar o valor.
5. **Investigações de integridade:** Atividade e Preparação em HTTP, caminho `/health`, porta 8000.
6. **Salvar → Criar** (revisão nova).
7. **Escala:** mínimo 0, máximo 1. No dia da apresentação, mínimo 1.
8. **Configurações → Entrada:** porta de destino **8000**. Se o Orquestrador falhar por redirecionamento
   para HTTPS, ative **Permitir conexões inseguras**.

**Versão nova:** depois de um push na `main` com o workflow concluído, abra **Contêineres → Editar e implantar →
Criar**. A revisão nova baixa a `latest`, e a reindexação da inicialização gera embeddings só dos arquivos alterados.

## 6. Testar

1. **Monitoramento → Fluxo de log:** procure `busca_db conectado` e uma linha `ingestao: ResultadoReindex(documents=...)`.
   - `busca_db indisponível`: confira a `DATABASE_URL` e a rede do PostgreSQL (Parte 2.1 do guia do grupo).
   - `extension "vector" is not allow-listed`: falta `VECTOR` em `azure.extensions` (Parte 2.3).
   - Muitos `falha nos embeddings`: cota ou modelo indisponível para a chave. Esses arquivos entram na próxima indexação.
2. Como o ingress é interno, o teste é pelo Conversas: abra `<URL do mackai-conversas>/api/health`. Com o
   Orquestrador no ar, `documents` e `chunks` devem ser maiores que 0, e `status` deve ser `"ok"`.

## Primeira indexação e cota

A primeira indexação gera embeddings de todos os trechos (cerca de 400 hoje, em lotes de 20). Em caso de 429,
o serviço espera e tenta de novo. Enquanto isso, `/health` responde e `/v1/search` usa o que já está no
banco; `GET /v1/stats` mostra `indexing: true`.
