"""Gestor de Demandas — o miolo.

- `clientes`     o cadastro de clientes (`clientes.json`), apelidos e contatos por e-mail/telefone;
- `catalogo`     os tipos de demanda, com prazo padrão, importância e checklist (`catalogo.json`);
- `calendario`   dias úteis, feriados nacionais e móveis, e as obrigações do mês;
- `entender`     a linha única: tira cliente, tipo, prazo, pessoa, recorrência e aviso do texto;
- `conversa`     a conversa colada: quem falou, o que foi pedido, o que você combinou;
- `mensagem`     formato e remetente de uma mensagem (WhatsApp, e-mail, texto);
- `importancia`  a prioridade sugerida, sempre com o motivo escrito;
- `dados`        a área de um departamento: espaços, listas, tarefas, eventos, notificações;
- `armazem`      onde a área grava: pasta de JSON ou banco SQLite;
- `escritorio`   vários departamentos, cada um com a sua pasta, e o espaço pessoal de cada um;
- `usuarios`     login, senhas e papéis do servidor central;
- `avisos`       o relógio que lembra pelo balão do Windows mesmo com a página fechada;
- `config`       o domínio de e-mail da equipe.

Nada aqui escreve fora da pasta de dados e de `%LOCALAPPDATA%/GestorDemandas`.
"""
