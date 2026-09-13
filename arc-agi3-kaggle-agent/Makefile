# [arc-agi3-kaggle-agent] BL.21554 -- cadena de entrega del ARC Prize 2026 (track ARC-AGI-3).
#
# Equivalente del Makefile del starter oficial (arcprize/ARC-AGI-3-Kaggle-Starter), adaptado a
# este monorepo en dos puntos que importan:
#
#   1. NO se clona ningun repositorio externo. El framework `ARC-AGI-3-Agents` viaja DENTRO del
#      dataset de la competencia, asi que baja con el mismo token que los juegos y las wheels.
#   2. Todo lo que habla con Kaggle pasa por `node <monorepo>/scripts/kaggle-cli.cjs` (BL.21581):
#      el token sale del .env cifrado y nunca toca el disco ni el argv.
#
# Ciclo completo:
#   make setup          una vez: venv 3.12 + dataset + framework + motor de juego
#   make agente         regenera agent/my_agent.py desde arc_agent/ (BL.21555)
#   make play-local     loop interno: el agente contra los 25 juegos reales
#   make verify-local   humo rapido: 50 pasos sobre ls20 y vc33  <- CRITERIO de la cadena
#   make gate-costo     GATE DE MERGE: proyecta lo que cuesta antes de pagarlo (~36 min de CPU)
#   make gate-base      GATE DE MERGE (BL.21744): linea base de niveles, harness REAL
#   make gate           GATE DE MERGE: vuelve a medir y falla si los niveles no suben
#   make notebook       arma notebooks/submission.ipynb (regenera el agente primero)
#   make submit         arma y PUBLICA el kernel en Kaggle
#   make status         estado de la ultima corrida del kernel

PYTHON       ?= $(shell command -v python3.12 2>/dev/null || command -v python3)
VENV         := .venv
VENV_PY      := $(VENV)/bin/python
VENV_PIP     := $(VENV)/bin/pip
MONOREPO     := $(abspath $(CURDIR)/../..)
KAGGLE       := KAGGLE_CLI_BIN=$(abspath $(VENV))/bin/kaggle node $(MONOREPO)/scripts/kaggle-cli.cjs
METADATA     := notebooks/kernel-metadata.json
PLACEHOLDER  := REPLACE_WITH_YOUR_USERNAME
JUEGO        ?=
# BL.21701: VACIO a proposito. Fijar PASOS ?= 200 hacia que el loop local midiera SIEMPRE 200
# acciones aunque el entregable llevara otro tope, asi que el numero que se medía nunca era el que
# se entregaba. Sin valor, play_local juega con el MAX_ACTIONS del entregable; para un barrido se
# pide explicito: `make play-local PASOS=1600 PRESUPUESTO=0`.
PASOS        ?=
# Presupuesto de reloj del batch, en horas (0 = sin reloj, para barridos de medicion). Vacio =
# rige el presupuesto entregado por arc_agent/reloj_presupuesto.py.
PRESUPUESTO  ?=

.PHONY: ayuda setup agente play-local verify-local gate-costo gate-base gate list-games notebook \
        submit status test clean \
        _verificar-python _verificar-usuario

ayuda: ## Muestra esta ayuda
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  %-14s %s\n",$$1,$$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "Variables: PYTHON=$(PYTHON)  JUEGO=$(JUEGO)  PASOS=$(PASOS)  PRESUPUESTO=$(PRESUPUESTO)"
	@echo "  PASOS vacio = tope del entregable. PRESUPUESTO=0 apaga el reloj (barridos)."

_verificar-python:
	@$(PYTHON) -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)' || { \
	    echo "ERROR: se necesita Python >= 3.12 (el paquete oficial arc-agi lo exige)."; \
	    echo "       Interprete detectado: $(PYTHON)"; \
	    echo "       Ubuntu: sudo apt install python3.12 python3.12-venv   macOS: brew install python@3.12"; \
	    exit 1; }

setup: _verificar-python ## Instalacion unica: venv 3.12, dataset, framework y motor de juego
	$(PYTHON) -m venv $(VENV)
	$(VENV_PIP) install --upgrade pip
	$(VENV_PIP) install "kaggle>=2.2" python-dotenv pandas pyarrow -r requirements-dev.txt
	$(VENV_PY) scripts/fetch_competition_data.py
	$(VENV_PY) scripts/install_arc_agi.py
	$(VENV_PY) scripts/slim_framework.py
	@echo ""
	@echo "Listo. Probalo con:  make verify-local"

agente: ## Regenera agent/my_agent.py (nucleo arc_agent/ + wrapper MyAgent, un solo archivo)
	$(PYTHON) submission/build_agent.py

play-local: ## Corre agent/my_agent.py contra TODOS los juegos (o JUEGO=ls20 para uno solo)
	$(VENV_PY) scripts/play_local.py $(if $(JUEGO),--juego $(JUEGO)) \
	    $(if $(PASOS),--max-pasos $(PASOS)) \
	    $(if $(PRESUPUESTO),--presupuesto-horas $(PRESUPUESTO))

verify-local: ## Humo rapido: 50 pasos sobre ls20 y vc33
	$(VENV_PY) scripts/play_local.py --juego ls20,vc33 --max-pasos 50

# GATE DE MERGE (BL.21744). Corre contra el HARNESS REAL, nunca contra el banco parametrico
# de tests/support/: ese banco simula el mapeo de acciones, no los puzzles, y su columna
# `niveles` fue CERO POR CONSTRUCCION en 19 de los 25 mundos hasta BL.21744.
GATE_BASE    ?= runtime_reports/gate_base.json
GATE_NUEVO   ?= runtime_reports/gate_nuevo.json
GATE_PASOS   ?= 200
GATE_SEMILLAS ?= gate-1,gate-2,gate-3

gate-costo: ## Cuanto va a costar el gate en CPU y en reloj, ANTES de ocupar la maquina
	$(VENV_PY) scripts/gate_de_merge.py --pasos $(GATE_PASOS) \
	    --semillas $(GATE_SEMILLAS) --reportar-costo

gate-base: ## Linea base del gate de merge (correr ANTES del cambio)
	$(VENV_PY) scripts/gate_de_merge.py --pasos $(GATE_PASOS) \
	    --semillas $(GATE_SEMILLAS) --json $(GATE_BASE)

gate: ## Gate de merge: falla (codigo 1) si los niveles totales no superan a GATE_BASE
	$(VENV_PY) scripts/gate_de_merge.py --pasos $(GATE_PASOS) \
	    --semillas $(GATE_SEMILLAS) --json $(GATE_NUEVO) --contra $(GATE_BASE)

list-games: ## Lista los juegos reales disponibles
	$(VENV_PY) scripts/play_local.py --listar

notebook: agente ## Arma notebooks/submission.ipynb desde agent/my_agent.py (lo regenera antes)
	$(PYTHON) scripts/build_kernel_notebook.py

_verificar-usuario:
	@if grep -q $(PLACEHOLDER) $(METADATA); then \
	    echo "ERROR: $(METADATA) todavia tiene $(PLACEHOLDER). Reemplazalo por tu usuario de Kaggle."; \
	    exit 1; \
	fi

submit: notebook _verificar-usuario ## Arma el notebook y lo publica como kernel en Kaggle
	$(KAGGLE) kernels push -p notebooks/
	@echo ""
	@echo "Publicado. Segui la corrida con:  make status"

status: _verificar-usuario ## Estado de la ultima corrida del kernel
	@ID=$$($(VENV_PY) -c "import json; print(json.load(open('$(METADATA)'))['id'])"); \
	$(KAGGLE) kernels status $$ID

test: ## Corre la suite de tests del sub-proyecto
	$(VENV_PY) -m pytest -q

clean: ## Borra todo lo descargado y generado (venv, dataset, framework, notebook)
	rm -rf $(VENV) vendor environment_files wheels .cache recordings logs.log \
	       notebooks/submission.ipynb __pycache__ .pytest_cache
