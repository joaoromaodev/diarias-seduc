# -*- coding: utf-8 -*-
"""
Gera dados FICTÍCIOS para demonstração do sistema de Cruzamento de Diárias.

Nenhum dado real — nomes, CPFs, matrículas, OBs, processos e valores são
aleatórios. Saídas (em exemplos/):
  • base_of_exemplo.csv            -> carregar na aba Configurações
  • relatorio_diarias_exemplo.csv  -> subir na aba Processamento (competência 05/2026)

O conjunto é internamente consistente e já inclui casos que exercitam os três
resultados do cruzamento:
  - a maioria casa por OB           -> "Vinculados" (ORIGEM = OB)
  - algumas OBs ausentes da OF       -> "A cadastrar na OF" (vínculo por CPF)
  - alguns servidores fora da OF     -> "Não encontradas"
além de linhas ANULADO e um estorno (valor negativo) para exercitar os filtros.
"""
import csv
import os
import random

random.seed(42)
AQUI = os.path.dirname(os.path.abspath(__file__))

PRENOMES = ["ANA", "BRUNO", "CARLA", "DIEGO", "ELISA", "FABIO", "GISELE", "HUGO",
            "ISABEL", "JOAO", "KARINA", "LUCAS", "MARIA", "NUNO", "OLGA", "PEDRO",
            "QUEILA", "RAFAEL", "SOFIA", "TIAGO", "VALERIA", "WAGNER", "YARA",
            "ANDRE", "BEATRIZ", "CESAR", "DANIELA", "EDUARDO", "FERNANDA", "GUSTAVO"]
SOBRENOMES = ["SILVA", "SANTOS", "OLIVEIRA", "SOUZA", "LIMA", "PEREIRA", "COSTA",
              "RODRIGUES", "ALMEIDA", "NASCIMENTO", "ARAUJO", "FERREIRA", "BARBOSA",
              "MONTEIRO", "CARDOSO", "ROCHA", "MARTINS", "TAVARES", "MIRANDA",
              "CORREA", "DIAS", "RIBEIRO", "GOMES", "MORAES"]
VALORES = [123.54, 247.07, 370.61, 617.68, 864.75, 1111.82, 1358.89, 1605.96, 1842.50]


def nome():
    return f"{random.choice(PRENOMES)} {random.choice(SOBRENOMES)} {random.choice(SOBRENOMES)}"


def cpf():
    return "".join(str(random.randint(0, 9)) for _ in range(11))


def matricula():
    return str(random.randint(100000, 9999999))


# 1) servidores fictícios ------------------------------------------------------
servidores = [
    {"nome": nome(), "cpf": cpf(), "matricula": matricula(),
     "vinculo": random.choice([1, 1, 1, 2, 2, 3, 4])}
    for _ in range(40)
]

# 2) lançamentos (pagamentos), cada um com um nº de OB sequencial --------------
seq = 9000
lancamentos = []
for srv in servidores:
    for _ in range(random.randint(1, 3)):
        seq += random.randint(1, 5)
        lancamentos.append({"srv": srv, "seq": seq,
                            "valor": random.choice(VALORES),
                            "dia": random.randint(1, 28)})

# 3) monta a base OF -----------------------------------------------------------
# três servidores ficam totalmente fora da OF -> "não encontradas"
fora_total = {id(s) for s in random.sample(servidores, 3)}
of_rows = []
num_despesa = 100000
for l in lancamentos:
    if id(l["srv"]) in fora_total:
        continue
    if random.random() < 0.12:
        continue  # OB ausente da OF -> "a cadastrar" (recuperável por CPF)
    num_despesa += 1
    s = l["srv"]
    of_rows.append([num_despesa, s["matricula"], s["vinculo"], s["cpf"],
                    f"2026OB{l['seq']:05d}", f"{l['dia']:02d}/05/2026", "5/2026"])

with open(os.path.join(AQUI, "base_of_exemplo.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["num_despesa", "matricula", "vinculo", "cpf",
                "num_ordem_bancaria", "dt_pagamento", "mes_pagamento"])
    w.writerows(of_rows)

# 4) monta o relatório de diárias no formato SIAFE (9 colunas) -----------------
linhas = [
    ["NOME DO CREDOR", "", "SITUAÇÃO", "DOCUMENTO", "NÚMERO DO PROCESSO",
     "DATA", "EVENTO", "FONTE DE RECURSO", "VALOR"],
    ["160101 - Secretaria de Estado de Educação", "", "", "", "", "", "", "", ""],
]
for i, l in enumerate(lancamentos):
    s = l["srv"]
    situacao = "ANULADO" if i % 25 == 7 else "ENVIADO"     # algumas anuladas
    valor = -l["valor"] if i % 37 == 11 else l["valor"]     # um estorno (negativo)
    linhas.append([
        f"{s['nome']} - {s['cpf']}", "", situacao,
        f"2026160101OB{l['seq']:05d}",
        str(random.randint(20260000000, 20269999999)),
        f"{l['dia']:02d}/05/2026", "700414", "01500100102 000000",
        f"{valor:.2f}".replace(".", ","),
    ])

with open(os.path.join(AQUI, "relatorio_diarias_exemplo.csv"), "w", newline="", encoding="utf-8-sig") as f:
    csv.writer(f).writerows(linhas)

print("Dados fictícios gerados em exemplos/:")
print(f"  base_of_exemplo.csv            ({len(of_rows)} registros na OF)")
print(f"  relatorio_diarias_exemplo.csv ({len(lancamentos)} lançamentos)")
print("\nNo app: Configurações -> enviar base_of_exemplo.csv;")
print("        Processamento -> competência 05/2026 -> subir relatorio_diarias_exemplo.csv.")
