from datetime import date, timedelta

CARGOS = {
    'supervisor': 'Supervisor',
    'operador_caixa': 'Operador de Caixa',
    'embalador': 'Embalador',
    'guarda_volumes': 'Guarda-Volumes',
}

DIAS_PT = {0: 'segunda', 1: 'terca', 2: 'quarta', 3: 'quinta', 4: 'sexta', 5: 'sabado', 6: 'domingo'}

REGIMES_TRABALHO = {
    '44h': {'horas_semanais': 44, 'descricao': '44h semanais (CLT padrão)'},
    '48h': {'horas_semanais': 48, 'descricao': '48h semanais (máximo CLT)'},
    '36h': {'horas_semanais': 36, 'descricao': '36h semanais'},
    '32h': {'horas_semanais': 32, 'descricao': '32h semanais'},
    '30h': {'horas_semanais': 30, 'descricao': '30h semanais'},
    '5x2': {'horas_semanais': None, 'descricao': '5x2 (5 dias trabalho, 2 folgas consecutivas)'},
}


# ── Feriados nacionais (fixos + móveis) ───────────────────────────────────────

def _calcular_pascoa(ano):
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, month, day)


def feriados_brasil(ano):
    """Retorna lista de datas (date) de feriados nacionais, incluindo datas móveis."""
    pascoa = _calcular_pascoa(ano)
    fixos = [
        date(ano, 1, 1),    # Ano Novo
        date(ano, 4, 21),   # Tiradentes
        date(ano, 5, 1),    # Dia do Trabalho
        date(ano, 9, 7),    # Independência
        date(ano, 10, 12),  # Nossa Senhora Aparecida
        date(ano, 11, 2),   # Finados
        date(ano, 11, 15),  # Proclamação da República
        date(ano, 11, 20),  # Consciência Negra (lei federal desde 2023)
        date(ano, 12, 25),  # Natal
    ]
    moveis = [
        pascoa - timedelta(days=48),  # Carnaval — Segunda
        pascoa - timedelta(days=47),  # Carnaval — Terça
        pascoa - timedelta(days=2),   # Sexta-Feira Santa
        pascoa,                        # Páscoa
        pascoa + timedelta(days=60),  # Corpus Christi
    ]
    return sorted(set(fixos + moveis))


def horas_turno(turno_config):
    """Calcula a duração em horas de um turno a partir de seu horário."""
    from datetime import datetime as _dt
    try:
        inicio = _dt.strptime(turno_config.get('horario_inicio', '00:00'), '%H:%M')
        fim = _dt.strptime(turno_config.get('horario_fim', '00:00'), '%H:%M')
        diff = (fim - inicio).total_seconds()
        if diff <= 0:
            diff += 86400  # turno que passa da meia-noite
        return diff / 3600
    except Exception:
        return 8.0


def tempo_de_casa(func):
    try:
        return date.fromisoformat(func['data_admissao'])
    except Exception:
        return date.today()


def _is_domingo_folga(func, domingo):
    ref_str = func.get('domingo_ref')
    domingos_trabalha = int(func.get('rotacao_domingo', 2))
    domingos_folga = int(func.get('domingos_folga', 1))
    if not ref_str:
        return False
    ref = date.fromisoformat(ref_str)
    diff_dias = (domingo - ref).days
    if diff_dias % 7 != 0:
        return False
    semanas = diff_dias // 7
    ciclo = domingos_folga + domingos_trabalha
    posicao = semanas % ciclo
    return posicao < domingos_folga


def is_disponivel(func, data):
    fi, ff = func.get('ferias_inicio'), func.get('ferias_fim')
    if fi and ff:
        if date.fromisoformat(fi) <= data <= date.fromisoformat(ff):
            return False
    for at in func.get('atestados', []):
        if date.fromisoformat(at['inicio']) <= data <= date.fromisoformat(at['fim']):
            return False
    if data.weekday() == 6 and _is_domingo_folga(func, data):
        return False
    folga_semana = func.get('folga_semana')
    if folga_semana:
        dias_inv = {v: k for k, v in DIAS_PT.items()}
        num = dias_inv.get(folga_semana)
        if num is not None and data.weekday() == num:
            return False
    return True


def get_cargos_turno(turno_config):
    return {
        'supervisor': turno_config.get('supervisores', 0),
        'operador_caixa': turno_config.get('operadores_caixa', 0),
        'embalador': turno_config.get('embaladores', 0),
        'guarda_volumes': turno_config.get('guarda_volumes', 0),
    }


# ── Lógica de rotação de caixas ───────────────────────────────────────────────

def distribuir_caixas(operadores, caixas_config, historico_caixas, turno_nome=''):
    """
    Distribui operadores nos caixas disponíveis evitando repetição prolongada.

    - Caixas fechados para o turno são ignorados.
    - Operadores com caixa_fixo são alocados primeiro naquele caixa.
    - Sem operadores suficientes: prioriza caixas rápidos e de número menor.
    - Penaliza repetição recente de caixa para favorecer rodízio.

    operadores: lista de dicts com id, nome, velocidade, caixas_preferidos, caixa_fixo (id ou None)
    caixas_config: lista de dicts com id, numero, tipo, status_turno, restricoes_ergonomicas
    historico_caixas: dict {func_id: [caixa_id, ...]} — mais recente no fim
    """
    if not caixas_config or not operadores:
        return []

    # Filtra caixas abertos para este turno
    if turno_nome:
        caixas_disponiveis = [
            cx for cx in caixas_config
            if cx.get('status_turno', {}).get(turno_nome, 'aberto') == 'aberto'
        ]
        if not caixas_disponiveis:
            caixas_disponiveis = list(caixas_config)
    else:
        caixas_disponiveis = list(caixas_config)

    caixas_alocadas = {}   # caixa_id -> operador dict
    ops_alocados_ids = set()

    ops_com_fixo = [op for op in operadores if op.get('caixa_fixo')]
    ops_sem_fixo = [op for op in operadores if not op.get('caixa_fixo')]

    # 1. Aloca operadores com caixa fixo primeiro
    for op in ops_com_fixo:
        cx = next((cx for cx in caixas_disponiveis
                   if cx['id'] == op['caixa_fixo'] and cx['id'] not in caixas_alocadas), None)
        if cx:
            caixas_alocadas[cx['id']] = op
            ops_alocados_ids.add(op['id'])
        else:
            ops_sem_fixo.append(op)  # caixa fixo indisponível: aloca normalmente

    # 2. Ordena caixas restantes por prioridade: rápido e preferencial primeiro, menor número primeiro
    def prioridade_caixa(cx):
        # Preferencial sempre primeiro, depois rápido, depois normal por número
        tipo_prio = {'preferencial': 0, 'rapido': 1, 'normal': 2}.get(cx.get('tipo', 'normal'), 2)
        try:
            num = int(cx.get('numero', 99))
        except (ValueError, TypeError):
            num = 99
        return (tipo_prio, num)

    caixas_pendentes = sorted(
        [cx for cx in caixas_disponiveis if cx['id'] not in caixas_alocadas],
        key=prioridade_caixa
    )

    # 3. Atribuição de custo mínimo global (backtracking) para garantir rodízio correto
    ops_disponiveis = [op for op in ops_sem_fixo if op['id'] not in ops_alocados_ids]

    # Garante caixa para todos os operadores: cria virtuais para os que excederem os configurados
    if len(caixas_pendentes) < len(ops_disponiveis):
        nums_existentes = {str(cx.get('numero', '')) for cx in caixas_disponiveis}
        v = 1
        while len(caixas_pendentes) < len(ops_disponiveis):
            while str(v) in nums_existentes:
                v += 1
            caixas_pendentes.append({
                'id': f'virtual-cx-{v:02d}',
                'numero': str(v),
                'tipo': 'normal',
                'status_turno': {},
            })
            nums_existentes.add(str(v))
            v += 1

    def score(op, cx):
        hist = historico_caixas.get(op['id'], [])
        last_idx = next((i for i in range(len(hist) - 1, -1, -1) if hist[i] == cx['id']), None)
        passos = (len(hist) - last_idx) if last_idx is not None else (len(hist) + 1)
        # Custo POSITIVO: caixa usada recentemente → custo alto; não usada → custo baixo
        # Isso garante que a poda (custo >= melhor) funcione corretamente
        s = max(0, 32 - passos) * 5
        if cx['id'] in op.get('caixas_preferidos', []):
            s = max(0, s - 5)
        if op.get('velocidade') == 'rapido' and cx.get('tipo') == 'rapido':
            s = max(0, s - 3)
        if op.get('velocidade') == 'rapido' and cx.get('tipo') == 'preferencial':
            s += 2
        return s

    caixas_a_preencher = caixas_pendentes[:len(ops_disponiveis)]

    if caixas_a_preencher and ops_disponiveis:
        n_cx = len(caixas_a_preencher)
        n_op = len(ops_disponiveis)

        melhor = {'custo': float('inf'), 'atrib': None}

        def backtrack(j, usados, atrib, custo):
            if j == n_cx:
                if custo < melhor['custo']:
                    melhor['custo'] = custo
                    melhor['atrib'] = list(atrib)
                return
            if custo >= melhor['custo']:  # poda válida pois todos os custos são ≥ 0
                return
            cx = caixas_a_preencher[j]
            for i in range(n_op):
                if i in usados:
                    continue
                usados.add(i)
                atrib.append(i)
                backtrack(j + 1, usados, atrib, custo + score(ops_disponiveis[i], cx))
                usados.discard(i)
                atrib.pop()

        backtrack(0, set(), [], 0)

        if melhor['atrib'] is not None:
            for j, i in enumerate(melhor['atrib']):
                cx = caixas_a_preencher[j]
                op = ops_disponiveis[i]
                caixas_alocadas[cx['id']] = op
                ops_alocados_ids.add(op['id'])

    # 4. Monta resultado — caixas configurados (inclui fixos) + virtuais, ordenados por número
    virtuais = [cx for cx in caixas_pendentes if cx['id'].startswith('virtual-')]
    todos_cx = list(caixas_disponiveis) + virtuais

    def _num_caixa(cx):
        try:
            return int(cx['numero'])
        except (ValueError, TypeError):
            return 9999

    resultado = []
    incluidos = set()
    for cx in sorted(todos_cx, key=_num_caixa):
        if cx['id'] in caixas_alocadas and cx['id'] not in incluidos:
            op = caixas_alocadas[cx['id']]
            resultado.append({
                'operador_id': op['id'], 'operador_nome': op['nome'],
                'caixa_id': cx['id'], 'caixa_numero': cx['numero'],
                'caixa_tipo': cx.get('tipo', 'normal'),
                'tipo_alocacao': op.get('tipo', 'titular'),
            })
            incluidos.add(cx['id'])

    # Segurança: operadores ainda sem caixa (não deve ocorrer com a lógica acima)
    for op in operadores:
        if op['id'] not in ops_alocados_ids:
            resultado.append({
                'operador_id': op['id'], 'operador_nome': op['nome'],
                'caixa_id': None, 'caixa_numero': '?', 'caixa_tipo': None,
                'tipo_alocacao': op.get('tipo', 'titular'),
            })

    return resultado


# ── Geração de dias ───────────────────────────────────────────────────────────

def _planejar_folgas_regime(funcionarios, config, datas_semana):
    """
    Planeja as folgas da semana segundo o regime global.
    Distribui folgas adicionais (além das fixas) nos dias com maior cobertura,
    garantindo que os dias mais cheios absorvam as ausências.
    Retorna {func_id: set(data_str)} com TODAS as folgas da semana.
    """
    regime = config.get('regime_trabalho', '44h')
    if not datas_semana:
        return {}

    # Dias de trabalho alvo por semana
    if regime == '5x2':
        dias_trabalho_alvo = 5
    else:
        info = REGIMES_TRABALHO.get(regime, REGIMES_TRABALHO['44h'])
        h_sem = info.get('horas_semanais') or 44
        turnos_cfg = config.get('turnos', {})
        h_media = (sum(horas_turno(t) for t in turnos_cfg.values()) / len(turnos_cfg)) if turnos_cfg else 8.0
        dias_trabalho_alvo = min(len(datas_semana), max(1, round(h_sem / h_media)))

    folgas = {f['id']: set() for f in funcionarios}

    # 1. Registra folgas fixas (férias, atestados, rotação de domingo, folga semanal)
    for func in funcionarios:
        for data in datas_semana:
            if not is_disponivel(func, data):
                folgas[func['id']].add(data.isoformat())

    # 2. Contagem de disponíveis por dia (sem folgas fixas) para guiar distribuição
    cobertura = {}
    for data in datas_semana:
        ds = data.isoformat()
        cobertura[ds] = sum(1 for f in funcionarios if ds not in folgas[f['id']])

    # 3. Para cada funcionário, distribui folgas adicionais nos dias com mais cobertura
    for func in funcionarios:
        fixas = len(folgas[func['id']])
        adicionais = max(0, len(datas_semana) - dias_trabalho_alvo - fixas)
        if adicionais <= 0:
            continue

        candidatos = sorted(
            [d for d in datas_semana if d.isoformat() not in folgas[func['id']]],
            key=lambda d: -cobertura[d.isoformat()]
        )
        for data in candidatos[:adicionais]:
            folgas[func['id']].add(data.isoformat())
            cobertura[data.isoformat()] -= 1

    return folgas


def gerar_dia(funcionarios, config, data, historico_caixas=None, ausencias_extras=None):
    if historico_caixas is None:
        historico_caixas = {}
    if ausencias_extras is None:
        ausencias_extras = set()
    alocados_ids = set()
    vacancias_criadas = {}
    turnos_resultado = {}

    for turno_nome, turno_config in config.get('turnos', {}).items():
        turno_resultado = {}
        disponiveis_turno = [
            f for f in funcionarios
            if f.get('turno') == turno_nome
            and is_disponivel(f, data)
            and f['id'] not in ausencias_extras
        ]

        for cargo, qtd in get_cargos_turno(turno_config).items():
            if qtd == 0:
                continue
            alocados = []

            titulares = sorted(
                [f for f in disponiveis_turno if f['cargo_primario'] == cargo and f['id'] not in alocados_ids],
                key=tempo_de_casa
            )

            for _ in range(qtd):
                if titulares:
                    func = titulares.pop(0)
                    alocados.append({'id': func['id'], 'nome': func['nome'], 'tipo': 'titular',
                                     'velocidade': func.get('velocidade', 'normal'),
                                     'caixas_preferidos': func.get('caixas_preferidos', []),
                                     'caixa_fixo': func.get('caixa_fixo') or None})
                    alocados_ids.add(func['id'])
                else:
                    sub = _buscar_substituto(funcionarios, cargo, turno_nome, data, alocados_ids)
                    if sub:
                        sub.setdefault('caixa_fixo', None)
                        alocados.append(sub)
                        alocados_ids.add(sub['id'])
                        if sub.get('tipo') in ('substituto_outro_turno', 'intermediario'):
                            t_orig = sub['turno_original']
                            vacancias_criadas.setdefault(t_orig, {})
                            vacancias_criadas[t_orig][cargo] = vacancias_criadas[t_orig].get(cargo, 0) + 1
                    else:
                        alocados.append({'id': None, 'nome': 'VAGA', 'tipo': 'vaga'})

            # Distribuição nos caixas para operadores de caixa
            if cargo == 'operador_caixa':
                caixas_config = config.get('caixas', [])
                ops_validos = [a for a in alocados if a['id'] is not None]
                # Sem caixas configurados: cria virtuais com IDs estáveis para que o rodízio funcione
                if not caixas_config and ops_validos:
                    caixas_config = [
                        {'id': f'virtual-cx-{i+1:02d}', 'numero': f'{i+1:02d}',
                         'tipo': 'normal', 'status_turno': {}}
                        for i in range(len(ops_validos))
                    ]
                distribuicao = distribuir_caixas(ops_validos, caixas_config, historico_caixas, turno_nome)
                # Atualiza histórico
                for d in distribuicao:
                    if d['caixa_id']:
                        hist = historico_caixas.setdefault(d['operador_id'], [])
                        hist.append(d['caixa_id'])
                        if len(hist) > 30:
                            hist.pop(0)
                # Enriquece alocados com info do caixa
                dist_map = {d['operador_id']: d for d in distribuicao}
                for a in alocados:
                    if a['id'] in dist_map:
                        a['caixa_id'] = dist_map[a['id']]['caixa_id']
                        a['caixa_numero'] = dist_map[a['id']]['caixa_numero']
                        a['caixa_tipo'] = dist_map[a['id']]['caixa_tipo']

            turno_resultado[cargo] = {
                'nome': CARGOS.get(cargo, cargo),
                'necessario': qtd,
                'funcionarios': alocados,
            }

        turnos_resultado[turno_nome] = {
            'horario': f"{turno_config.get('horario_inicio', '')} - {turno_config.get('horario_fim', '')}",
            'cargos': turno_resultado,
        }

    for turno_nome, cargos_vagos in vacancias_criadas.items():
        for cargo, qtd_vaga in cargos_vagos.items():
            for _ in range(qtd_vaga):
                sub = _buscar_substituto_intermediario(funcionarios, cargo, turno_nome, data, alocados_ids)
                lista = turnos_resultado.get(turno_nome, {}).get('cargos', {}).get(cargo, {}).get('funcionarios', [])
                if sub:
                    lista.append(sub)
                    alocados_ids.add(sub['id'])
                else:
                    lista.append({'id': None, 'nome': 'VAGA (intermediário)', 'tipo': 'intermediario_vago'})

    return {
        'data': data.isoformat(),
        'dia_semana': DIAS_PT[data.weekday()],
        'turnos': turnos_resultado,
    }


def _buscar_substituto(funcionarios, cargo, turno, data, alocados_ids):
    candidatos = sorted(
        [f for f in funcionarios
         if f.get('turno') == turno and f.get('cargo_secundario') == cargo
         and is_disponivel(f, data) and f['id'] not in alocados_ids],
        key=tempo_de_casa
    )
    if candidatos:
        f = candidatos[0]
        return {'id': f['id'], 'nome': f['nome'], 'tipo': 'substituto_secundario',
                'velocidade': f.get('velocidade', 'normal'),
                'caixas_preferidos': f.get('caixas_preferidos', []),
                'obs': f'Cargo secundário — turno {turno}'}

    outro = 'tarde' if turno == 'manha' else 'manha'
    candidatos = sorted(
        [f for f in funcionarios
         if f.get('turno') == outro and f.get('cargo_primario') == cargo
         and is_disponivel(f, data) and f['id'] not in alocados_ids],
        key=tempo_de_casa
    )
    if candidatos:
        f = candidatos[0]
        tipo = 'intermediario' if outro == 'tarde' and turno == 'manha' else 'substituto_outro_turno'
        return {'id': f['id'], 'nome': f['nome'], 'tipo': tipo,
                'velocidade': f.get('velocidade', 'normal'),
                'caixas_preferidos': f.get('caixas_preferidos', []),
                'turno_original': outro, 'obs': f'Do turno {outro} — mais tempo de casa'}

    return None


def _buscar_substituto_intermediario(funcionarios, cargo, turno, data, alocados_ids):
    candidatos = sorted(
        [f for f in funcionarios
         if (f.get('cargo_primario') == cargo or f.get('cargo_secundario') == cargo)
         and is_disponivel(f, data) and f['id'] not in alocados_ids],
        key=tempo_de_casa
    )
    if candidatos:
        f = candidatos[0]
        return {'id': f['id'], 'nome': f['nome'], 'tipo': 'intermediario',
                'obs': 'Intermediário — cobertura de vacância'}
    return None


def gerar_dia_feriado(funcionarios, config, data, ids_confirmados):
    alocados = {f['id']: f for f in funcionarios if f['id'] in ids_confirmados}
    fila = sorted(alocados.values(), key=lambda f: (f['cargo_primario'], tempo_de_casa(f)))
    usados = set()
    turnos_resultado = {}

    for turno_nome, turno_config in config.get('turnos', {}).items():
        turno_resultado = {}
        for cargo, qtd in get_cargos_turno(turno_config).items():
            if qtd == 0:
                continue
            lista = []
            candidatos = [f for f in fila if f['cargo_primario'] == cargo and f['id'] not in usados]
            for _ in range(qtd):
                if candidatos:
                    f = candidatos.pop(0)
                    lista.append({'id': f['id'], 'nome': f['nome'], 'tipo': 'feriado'})
                    usados.add(f['id'])
                else:
                    lista.append({'id': None, 'nome': 'VAGA', 'tipo': 'vaga'})
            turno_resultado[cargo] = {'nome': CARGOS.get(cargo, cargo), 'necessario': qtd, 'funcionarios': lista}

        turnos_resultado[turno_nome] = {
            'horario': f"{turno_config.get('horario_inicio', '')} - {turno_config.get('horario_fim', '')}",
            'cargos': turno_resultado,
        }

    return {
        'data': data.isoformat(),
        'dia_semana': DIAS_PT[data.weekday()],
        'feriado': True,
        'turnos': turnos_resultado,
    }


def funcionarios_disponiveis_feriado(funcionarios, data):
    return [f for f in funcionarios if not f.get('folga_feriado', False) and is_disponivel(f, data)]


def gerar_escala_semana(funcionarios, config, data_inicio, feriados_confirmados=None, historico_caixas=None, dias_existentes=None):
    if feriados_confirmados is None:
        feriados_confirmados = {}
    if historico_caixas is None:
        historico_caixas = {}
    if dias_existentes is None:
        dias_existentes = {}
    dias = {}
    alertas = []

    periodo = config.get('periodo_geracao_dias', 7)
    datas_semana = [data_inicio + timedelta(days=i) for i in range(periodo)]

    # Planeja folgas do regime global antes de gerar os dias
    folgas_regime = _planejar_folgas_regime(funcionarios, config, datas_semana)

    for data in datas_semana:
        data_str = data.isoformat()

        # Funcionários com folga planejada hoje (regime)
        ausencias_hoje = {
            fid for fid, folgas in folgas_regime.items()
            if data_str in folgas
        }

        if data_str in dias_existentes:
            dias[data_str] = dias_existentes[data_str]
        elif data_str in feriados_confirmados:
            dias[data_str] = gerar_dia_feriado(funcionarios, config, data, feriados_confirmados[data_str])
        else:
            dias[data_str] = gerar_dia(funcionarios, config, data, historico_caixas, ausencias_hoje)
            for turno_dados in dias[data_str]['turnos'].values():
                for cargo_dados in turno_dados['cargos'].values():
                    vagas = [f for f in cargo_dados['funcionarios'] if 'vaga' in f.get('tipo', '')]
                    if vagas:
                        alertas.append(f"⚠ {data_str}: {len(vagas)} vaga(s) em {cargo_dados['nome']}")

    return {'dias': dias, 'alertas': alertas}
