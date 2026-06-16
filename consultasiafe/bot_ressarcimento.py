# -*- coding: utf-8 -*-
"""
BOT RESSARCIMENTO - SEDUC
Versao integrada ao webapp de Diarias (sem Google Sheets).

Fluxo:
  1. Le a lista de OBs de um arquivo JSON (passado por argv ou variavel de ambiente).
  2. Faz LOGIN automatico no SIAFE (credenciais via variaveis de ambiente).
  3. Navega: Menu -> Gestao Financeira -> Pagamentos -> OB - Ordem Bancaria.
  4. Para cada OB: pesquisa e captura a descricao.
  5. Escreve o progresso/resultado, de forma incremental e atomica, em status.json.

As credenciais NUNCA sao gravadas em disco: chegam apenas por variavel de ambiente.

Uso:
    python bot_ressarcimento.py <input_obs.json> <status.json>
Variaveis de ambiente:
    SIAFE_USER, SIAFE_PASS  (obrigatorias)
    SIAFE_PROXY             (opcional; ex: http://user:pass@host:porta)
"""

import os
import sys
import json
import time
import tempfile
import traceback
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service


# --- CAMINHOS BASE ----------------------------------------------------------
if getattr(sys, "frozen", False):
    PASTA_ATUAL = os.path.dirname(sys.executable)
else:
    PASTA_ATUAL = os.path.dirname(os.path.abspath(__file__))

CAMINHO_DRIVER = os.path.join(PASTA_ATUAL, "chromedriver.exe")
LINK_SIAFE = "http://www.siafe.pa.gov.br/SIAFE/faces/fbFramesetTemplate.xhtml"


# --- ESTADO / STATUS --------------------------------------------------------
class Status:
    """Escreve o estado atual no arquivo de status de forma atomica."""

    def __init__(self, caminho):
        self.caminho = caminho
        self.dados = {
            "state": "starting",       # starting|logging_in|navigating|processing|done|error
            "message": "Iniciando...",
            "total": 0,
            "processed": 0,
            "resultados": [],          # [{ob, descricao, status}]
            "logs": [],                # ["HH:MM:SS  mensagem", ...]
        }
        self.log("Bot iniciado.")

    def set(self, **kwargs):
        self.dados.update(kwargs)
        self.salvar()

    def log(self, msg):
        carimbo = datetime.now().strftime("%H:%M:%S")
        self.dados["logs"].append(f"{carimbo}  {msg}")
        # mantém o log enxuto (ultimas 300 linhas)
        if len(self.dados["logs"]) > 300:
            self.dados["logs"] = self.dados["logs"][-300:]
        self.salvar()

    def add_resultado(self, ob, descricao, status):
        self.dados["resultados"].append(
            {"ob": ob, "descricao": descricao, "status": status}
        )
        self.dados["processed"] = len(self.dados["resultados"])
        self.salvar()

    def salvar(self):
        # escreve em arquivo temporario e substitui (evita leitura parcial pelo Streamlit)
        pasta = os.path.dirname(self.caminho) or "."
        fd, tmp = tempfile.mkstemp(dir=pasta, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.dados, f, ensure_ascii=False)
            os.replace(tmp, self.caminho)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise


# --- HELPERS DE FRAME -------------------------------------------------------
def _achar_em_qualquer_frame(driver, by, value, timeout=10, max_prof=4):
    """
    Procura um elemento no documento principal e em iframes aninhados (recursivo).
    Deixa o driver posicionado no frame onde encontrou e retorna o elemento.
    Retorna None se nao achar dentro do timeout.
    """
    fim = time.time() + timeout
    while time.time() < fim:
        driver.switch_to.default_content()
        el = _buscar_recursivo(driver, by, value, max_prof)
        if el:
            return el
        time.sleep(0.4)
    driver.switch_to.default_content()
    return None


def _buscar_recursivo(driver, by, value, prof):
    """Busca o elemento no frame atual e desce recursivamente nos frames filhos."""
    el = _tenta_achar(driver, by, value)
    if el:
        return el
    if prof <= 0:
        return None
    # o SIAFE usa <frameset>/<frame> (nao apenas <iframe>) -> pega os dois
    frames = driver.find_elements(By.CSS_SELECTOR, "frame, iframe")
    n = len(frames)
    for idx in range(n):
        # re-resolve os frames a cada iteracao (evita stale reference)
        frames = driver.find_elements(By.CSS_SELECTOR, "frame, iframe")
        if idx >= len(frames):
            break
        try:
            driver.switch_to.frame(frames[idx])
        except Exception:
            continue
        achado = _buscar_recursivo(driver, by, value, prof - 1)
        if achado:
            # mantem o driver posicionado no frame onde o elemento vive
            return achado
        # nao achou nesta subarvore: volta um nivel acima e tenta o proximo
        try:
            driver.switch_to.parent_frame()
        except Exception:
            driver.switch_to.default_content()
    return None


def _tenta_achar(driver, by, value):
    try:
        elementos = driver.find_elements(by, value)
        for el in elementos:
            if el.is_displayed():
                return el
    except Exception:
        pass
    return None


def _clicar_menu_por_texto(driver, texto, timeout=15):
    """Clica num item de menu da sidebar identificado pelo texto exato."""
    xpath = (
        "//div[contains(@class,'itemHeader__name') and "
        "normalize-space(text())=" + _xpath_literal(texto) + "]"
    )
    el = _achar_em_qualquer_frame(driver, By.XPATH, xpath, timeout)
    if not el:
        raise RuntimeError("Item de menu nao encontrado: " + texto)
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    time.sleep(0.2)
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)
    time.sleep(1.0)


def _xpath_literal(s):
    """Gera um literal XPath seguro mesmo com aspas no texto."""
    if '"' not in s:
        return '"' + s + '"'
    if "'" not in s:
        return "'" + s + "'"
    partes = s.split('"')
    return "concat(" + ", '\"', ".join('"' + p + '"' for p in partes) + ")"


# --- ETAPAS -----------------------------------------------------------------
def fazer_login(driver, status, usuario, senha):
    status.set(state="logging_in", message="Fazendo login no SIAFE...")
    status.log("Procurando campo de usuario (fbUser)...")

    campo_user = _achar_em_qualquer_frame(driver, By.ID, "fbUser", timeout=30)
    if not campo_user:
        raise RuntimeError("Campo de usuario (fbUser) nao encontrado.")
    campo_user.clear()
    campo_user.send_keys(usuario)
    status.log("Usuario preenchido.")

    campo_pass = _achar_em_qualquer_frame(driver, By.ID, "fbPass", timeout=10)
    if not campo_pass:
        raise RuntimeError("Campo de senha (fbPass) nao encontrado.")
    campo_pass.clear()
    campo_pass.send_keys(senha)
    status.log("Senha preenchida.")

    botao = _achar_em_qualquer_frame(
        driver, By.CSS_SELECTOR, "input.btLogin", timeout=10
    )
    if not botao:
        raise RuntimeError("Botao de login (btLogin) nao encontrado.")
    try:
        botao.click()
    except Exception:
        driver.execute_script("arguments[0].click();", botao)
    status.log("Botao de login clicado. Aguardando o ambiente carregar...")

    time.sleep(4.0)  # aguarda carregar o ambiente
    status.log("Login concluido.")


def _trocar_para_janela_mais_recente(driver, status):
    """Se o SIAFE abriu nova janela/aba apos o login, foca nela."""
    try:
        handles = driver.window_handles
        status.log(f"Janelas abertas: {len(handles)}")
        if len(handles) > 1:
            driver.switch_to.window(handles[-1])
            status.log("Trocado para a janela mais recente.")
    except Exception as e:
        status.log("Erro ao listar/trocar janelas: " + str(e))


def _diagnostico_pagina(driver, status):
    """Loga o estado atual da pagina para depuracao do menu."""
    driver.switch_to.default_content()
    try:
        status.log("URL atual: " + str(driver.current_url))
    except Exception:
        pass
    try:
        status.log("Titulo da pagina: " + str(driver.title))
    except Exception:
        pass

    # ainda na tela de login?
    if _tenta_achar(driver, By.ID, "fbUser"):
        status.log("ATENCAO: campo de login (fbUser) ainda visivel -> login pode ter falhado.")

    # frames/iframes no nivel principal
    try:
        iframes = driver.find_elements(By.CSS_SELECTOR, "frame, iframe")
        status.log(f"frames no nivel raiz: {len(iframes)}")
        for i, fr in enumerate(iframes):
            tag = fr.tag_name
            fid = fr.get_attribute("id") or ""
            fname = fr.get_attribute("name") or ""
            fsrc = (fr.get_attribute("src") or "")[:80]
            status.log(f"  {tag}[{i}] id='{fid}' name='{fname}' src='{fsrc}'")
    except Exception as e:
        status.log("Erro ao listar frames: " + str(e))

    # procura divs com classe 'action' (onde mora o toggle) em qualquer frame
    achou_action = _achar_em_qualquer_frame(
        driver, By.CSS_SELECTOR, "div[class*='action']", timeout=3
    )
    status.log("div[class*='action'] encontrado em algum frame? "
               + ("SIM" if achou_action else "NAO"))
    driver.switch_to.default_content()

    # procura qualquer elemento com classe bi-list (icone do menu)
    achou_bilist = _achar_em_qualquer_frame(
        driver, By.CSS_SELECTOR, "i.bi-list", timeout=2
    )
    status.log("icone i.bi-list (hamburguer) encontrado? "
               + ("SIM" if achou_bilist else "NAO"))
    driver.switch_to.default_content()


XPATH_ITENS_MENU = "//div[contains(@class,'itemHeader__name')]"


def _menu_aberto(driver):
    """True se os itens do menu (itemHeader__name) estao presentes em algum frame."""
    el = _achar_em_qualquer_frame(driver, By.XPATH, XPATH_ITENS_MENU, timeout=2)
    return el is not None


def _abrir_menu(driver, status):
    """Garante que o menu lateral esteja aberto. Tenta toggle + atalho."""
    for tentativa in range(1, 5):
        if _menu_aberto(driver):
            status.log("Menu lateral aberto.")
            return True

        # tenta achar e clicar no botao toggle (em qualquer frame)
        toggle = _achar_em_qualquer_frame(
            driver, By.CSS_SELECTOR, "div.action--toggle", timeout=3
        )
        if not toggle:
            toggle = _achar_em_qualquer_frame(
                driver, By.XPATH, "//div[starts-with(@title,'Menu')]", timeout=2
            )
        if toggle:
            try:
                toggle.click()
            except Exception:
                driver.execute_script("arguments[0].click();", toggle)
            status.log(f"Botao de menu (toggle) clicado (tentativa {tentativa}).")
            time.sleep(1.5)
            continue

        # fallback: atalho Ctrl+Shift+M no documento principal
        try:
            driver.switch_to.default_content()
            driver.find_element(By.TAG_NAME, "body").send_keys(
                Keys.CONTROL, Keys.SHIFT, "m"
            )
            status.log(f"Atalho Ctrl+Shift+M enviado (tentativa {tentativa}).")
            time.sleep(1.5)
        except Exception:
            status.log("Nao foi possivel abrir o menu nesta tentativa.")
            time.sleep(1.0)

    return _menu_aberto(driver)


def navegar_ate_consulta_ob(driver, status):
    status.set(state="navigating", message="Navegando ate a consulta de OB...")

    _trocar_para_janela_mais_recente(driver, status)
    _diagnostico_pagina(driver, status)

    if not _abrir_menu(driver, status):
        raise RuntimeError(
            "Nao foi possivel abrir o menu lateral (toggle/atalho falharam)."
        )

    status.log("Procurando item 'Gestão Financeira'...")
    _clicar_menu_por_texto(driver, "Gestão Financeira")
    status.log("Clicou em 'Gestão Financeira'. Procurando 'Pagamentos'...")
    _clicar_menu_por_texto(driver, "Pagamentos")
    status.log("Clicou em 'Pagamentos'. Procurando 'OB - Ordem Bancária'...")
    _clicar_menu_por_texto(driver, "OB - Ordem Bancária")
    status.log("Clicou em 'OB - Ordem Bancária'. Tela de consulta deve estar aberta.")
    time.sleep(2.0)


def capturar_descricao(driver, wait, ob):
    """Pesquisa uma OB e devolve (descricao, status)."""
    try:
        driver.switch_to.default_content()
        try:
            driver.switch_to.frame("MainBody")
        except Exception:
            pass

        # limpar / nova busca
        try:
            btn_nova = wait.until(
                EC.element_to_be_clickable((By.ID, "SearchButton"))
            )
            btn_nova.click()
            time.sleep(0.5)
        except Exception:
            pass

        # preencher campo de OB
        try:
            campo_ob = wait.until(
                EC.visibility_of_element_located(
                    (By.ID, "paymentExtractPayment:applicationId")
                )
            )
            campo_ob.clear()
            campo_ob.send_keys(ob)
        except Exception:
            return "", "erro"

        # procurar
        try:
            driver.find_element(By.ID, "FindButton").click()
            time.sleep(1.5)
        except Exception:
            return "", "erro"

        # ler descricao
        try:
            el_desc = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located(
                    (By.ID, "paymentExtractPayment:description")
                )
            )
            descricao = el_desc.get_attribute("value") or ""
            descricao = descricao.strip()
            if descricao:
                return descricao, "ok"
            return "", "vazio"
        except Exception:
            return "", "vazio"

    except Exception:
        return "", "erro"


# --- MAIN -------------------------------------------------------------------
def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        PASTA_ATUAL, "ressarcimento_obs.json"
    )
    status_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        PASTA_ATUAL, "ressarcimento_status.json"
    )

    status = Status(status_path)

    # proxy opcional
    proxy = os.environ.get("SIAFE_PROXY", "").strip()
    if proxy:
        os.environ["http_proxy"] = proxy
        os.environ["https_proxy"] = proxy
        os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

    usuario = os.environ.get("SIAFE_USER", "")
    senha = os.environ.get("SIAFE_PASS", "")
    if not usuario or not senha:
        status.set(state="error", message="Credenciais do SIAFE nao informadas.")
        return

    # ler OBs
    try:
        with open(input_path, encoding="utf-8") as f:
            obs = json.load(f)
        obs = [str(o).strip() for o in obs if str(o).strip()]
    except Exception as e:
        status.set(state="error", message="Erro ao ler lista de OBs: " + str(e))
        return

    if not obs:
        status.set(state="error", message="Nenhuma OB para processar.")
        return

    status.set(total=len(obs))

    # navegador
    if not os.path.exists(CAMINHO_DRIVER):
        status.set(state="error", message="chromedriver.exe nao encontrado.")
        return

    status.log("Abrindo o navegador Chrome...")
    try:
        service = Service(executable_path=CAMINHO_DRIVER)
        driver = webdriver.Chrome(service=service)
    except Exception as e:
        status.log("Traceback:\n" + traceback.format_exc())
        status.set(state="error", message="Erro ao abrir o Chrome: " + str(e))
        return

    try:
        driver.maximize_window()
        status.log("Acessando o SIAFE: " + LINK_SIAFE)
        driver.get(LINK_SIAFE)

        fazer_login(driver, status, usuario, senha)
        navegar_ate_consulta_ob(driver, status)

        status.set(state="processing", message="Capturando descricoes...")
        status.log(f"Iniciando captura de {len(obs)} OBs.")
        wait = WebDriverWait(driver, 10)

        for i, ob in enumerate(obs, 1):
            descricao, st = capturar_descricao(driver, wait, ob)
            icone = {"ok": "OK", "vazio": "VAZIO", "erro": "ERRO"}.get(st, st)
            status.add_resultado(ob, descricao, st)
            status.log(f"[{i}/{len(obs)}] OB {ob} -> {icone}")

        status.set(state="done", message="Concluido.")
        status.log("Processo finalizado com sucesso.")

    except Exception as e:
        status.log("ERRO: " + str(e))
        status.log("Traceback:\n" + traceback.format_exc())
        status.set(state="error", message="Falha na execucao: " + str(e))
        # mantem o Chrome aberto alguns segundos para inspecao visual
        try:
            status.log("Mantendo o navegador aberto por 15s para inspecao...")
            time.sleep(15)
        except Exception:
            pass
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
