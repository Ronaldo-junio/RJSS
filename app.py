from flask import Flask, render_template, redirect, url_for, request, session, flash, jsonify, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta
from logica_escalas import gerar_escala_semana, funcionarios_disponiveis_feriado, CARGOS, DIAS_PT, feriados_brasil
import json
import os
import sys
import uuid
import functools

app = Flask(__name__)
app.secret_key = 'rjss_chave_secreta_2024'

USERS_FILE = os.path.join(os.path.dirname(__file__), 'data', 'users.json')
USER_FILES_DIR = os.path.join(os.path.dirname(__file__), 'user_files')


# ── Helpers de dados ─────────────────────────────────────────────────────────

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_users(users):
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def user_dir(username):
    return os.path.join(USER_FILES_DIR, username)

def user_file(username, *parts):
    return os.path.join(user_dir(username), *parts)

def load_json(path, default=None):
    if default is None:
        default = []
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_funcionarios(username):
    return load_json(user_file(username, 'funcionarios.json'), [])

def save_funcionarios(username, data):
    save_json(user_file(username, 'funcionarios.json'), data)

def get_config(username):
    default = {
        'turnos_fixos': True,
        'periodo_geracao_dias': 7,
        'turnos': {
            'manha': {'horario_inicio': '06:00', 'horario_fim': '14:00',
                      'supervisores': 1, 'operadores_caixa': 3, 'embaladores': 1, 'guarda_volumes': 1},
            'tarde': {'horario_inicio': '14:00', 'horario_fim': '22:00',
                      'supervisores': 1, 'operadores_caixa': 3, 'embaladores': 1, 'guarda_volumes': 1},
        },
        'caixas': [],
    }
    cfg = load_json(user_file(username, 'configuracoes.json'), default)
    if 'caixas' not in cfg:
        cfg['caixas'] = []
    if 'feriados_locais' not in cfg:
        cfg['feriados_locais'] = []
    return cfg

def save_config(username, data):
    save_json(user_file(username, 'configuracoes.json'), data)

def get_escalas(username):
    return load_json(user_file(username, 'escalas.json'), [])

def save_escalas(username, data):
    save_json(user_file(username, 'escalas.json'), data)


# ── Decoradores ───────────────────────────────────────────────────────────────

def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'usuario' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'usuario' not in session:
            return redirect(url_for('login'))
        if session.get('papel') != 'admin':
            return redirect(url_for('painel_usuario', username=session['usuario']))
        return f(*args, **kwargs)
    return decorated

def acesso_usuario(f):
    """Permite acesso ao próprio usuário ou ao admin."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if 'usuario' not in session:
            return redirect(url_for('login'))
        username = kwargs.get('username', '')
        if session['usuario'] != username and session.get('papel') != 'admin':
            return redirect(url_for('painel_usuario', username=session['usuario']))
        return f(*args, **kwargs)
    return decorated


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '')
        users = load_users()
        if usuario in users and check_password_hash(users[usuario]['senha'], senha):
            session['usuario'] = usuario
            session['papel'] = users[usuario]['papel']
            if users[usuario]['papel'] == 'admin':
                return redirect(url_for('painel_admin'))
            return redirect(url_for('painel_usuario', username=usuario))
        flash('Usuário ou senha incorretos.', 'erro')
    return render_template('login.html')

@app.route('/logout/')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route('/admin/')
@admin_required
def painel_admin():
    users = load_users()
    return render_template('admin/painel.html', users=users)

@app.route('/admin/adicionar/', methods=['GET', 'POST'])
@admin_required
def adicionar_usuario():
    if request.method == 'POST':
        novo = request.form.get('usuario', '').strip()
        senha = request.form.get('senha', '')
        papel = request.form.get('papel', 'usuario')
        if not novo or not senha:
            flash('Preencha todos os campos.', 'erro')
        else:
            users = load_users()
            if novo in users:
                flash('Este usuário já existe.', 'erro')
            else:
                users[novo] = {'senha': generate_password_hash(senha), 'papel': papel}
                save_users(users)
                os.makedirs(user_dir(novo), exist_ok=True)
                flash(f'Usuário "{novo}" criado com sucesso.', 'sucesso')
                return redirect(url_for('painel_admin'))
    return render_template('admin/adicionar_usuario.html')

@app.route('/admin/excluir/<username>', methods=['POST'])
@admin_required
def excluir_usuario(username):
    if username == 'admin':
        flash('Não é possível excluir o administrador.', 'erro')
        return redirect(url_for('painel_admin'))
    users = load_users()
    if username in users:
        del users[username]
        save_users(users)
        flash(f'Usuário "{username}" excluído.', 'sucesso')
    return redirect(url_for('painel_admin'))


@app.route('/admin/reiniciar/', methods=['POST'])
@admin_required
def reiniciar_servidor():
    session.clear()
    return redirect(url_for('login'))
    os.execv(sys.executable, [sys.executable] + sys.argv)


@app.route('/manual/')
def manual_usuario():
    base = os.path.dirname(__file__)
    return send_from_directory(base, 'manual.html')


# ── Painel do usuário ─────────────────────────────────────────────────────────

@app.route('/usuario/<username>/')
@acesso_usuario
def painel_usuario(username):
    return render_template('usuario/painel.html', username=username)


# ── Funcionários ──────────────────────────────────────────────────────────────

@app.route('/usuario/<username>/funcionarios/')
@acesso_usuario
def lista_funcionarios(username):
    funcs = get_funcionarios(username)
    return render_template('usuario/funcionarios/lista.html', username=username, funcionarios=funcs, cargos=CARGOS)

@app.route('/usuario/<username>/funcionarios/novo/', methods=['GET', 'POST'])
@acesso_usuario
def novo_funcionario(username):
    if request.method == 'POST':
        f = _form_to_funcionario(request.form)
        f['id'] = str(uuid.uuid4())
        f['atestados'] = []
        funcs = get_funcionarios(username)
        funcs.append(f)
        save_funcionarios(username, funcs)
        flash('Funcionário cadastrado com sucesso.', 'sucesso')
        return redirect(url_for('lista_funcionarios', username=username))
    return render_template('usuario/funcionarios/form.html', username=username, func=None, cargos=CARGOS,
                           dias_semana=DIAS_PT)

@app.route('/usuario/<username>/funcionarios/<func_id>/')
@acesso_usuario
def detalhes_funcionario(username, func_id):
    funcs = get_funcionarios(username)
    func = next((f for f in funcs if f['id'] == func_id), None)
    if not func:
        flash('Funcionário não encontrado.', 'erro')
        return redirect(url_for('lista_funcionarios', username=username))
    return render_template('usuario/funcionarios/detalhes.html', username=username, func=func, cargos=CARGOS)

@app.route('/usuario/<username>/funcionarios/<func_id>/editar/', methods=['GET', 'POST'])
@acesso_usuario
def editar_funcionario(username, func_id):
    funcs = get_funcionarios(username)
    idx = next((i for i, f in enumerate(funcs) if f['id'] == func_id), None)
    if idx is None:
        flash('Funcionário não encontrado.', 'erro')
        return redirect(url_for('lista_funcionarios', username=username))
    if request.method == 'POST':
        atestados = funcs[idx].get('atestados', [])
        funcs[idx] = _form_to_funcionario(request.form)
        funcs[idx]['id'] = func_id
        funcs[idx]['atestados'] = atestados
        save_funcionarios(username, funcs)
        flash('Funcionário atualizado.', 'sucesso')
        return redirect(url_for('detalhes_funcionario', username=username, func_id=func_id))
    return render_template('usuario/funcionarios/form.html', username=username, func=funcs[idx],
                           cargos=CARGOS, dias_semana=DIAS_PT)

@app.route('/usuario/<username>/funcionarios/<func_id>/excluir/', methods=['POST'])
@acesso_usuario
def excluir_funcionario(username, func_id):
    funcs = [f for f in get_funcionarios(username) if f['id'] != func_id]
    save_funcionarios(username, funcs)
    flash('Funcionário excluído.', 'sucesso')
    return redirect(url_for('lista_funcionarios', username=username))

@app.route('/usuario/<username>/funcionarios/<func_id>/atestado/', methods=['POST'])
@acesso_usuario
def add_atestado(username, func_id):
    funcs = get_funcionarios(username)
    func = next((f for f in funcs if f['id'] == func_id), None)
    if func:
        func.setdefault('atestados', []).append({
            'inicio': request.form.get('inicio', ''),
            'fim': request.form.get('fim', ''),
            'obs': request.form.get('obs', ''),
        })
        save_funcionarios(username, funcs)
        flash('Atestado registrado.', 'sucesso')
    return redirect(url_for('detalhes_funcionario', username=username, func_id=func_id))


# ── Escalas ───────────────────────────────────────────────────────────────────

@app.route('/usuario/<username>/escalas/')
@acesso_usuario
def lista_escalas(username):
    escalas = get_escalas(username)
    return render_template('usuario/escalas/lista.html', username=username, escalas=escalas)

@app.route('/usuario/<username>/escalas/<escala_id>/')
@acesso_usuario
def ver_escala(username, escala_id):
    escalas = get_escalas(username)
    escala = next((e for e in escalas if e['id'] == escala_id), None)
    if not escala:
        flash('Escala não encontrada.', 'erro')
        return redirect(url_for('lista_escalas', username=username))
    return render_template('usuario/escalas/semana.html', username=username, escala=escala, cargos=CARGOS)

@app.route('/usuario/<username>/escalas/<escala_id>/imprimir/')
@acesso_usuario
def imprimir_escala(username, escala_id):
    escalas = get_escalas(username)
    escala = next((e for e in escalas if e['id'] == escala_id), None)
    if not escala:
        return redirect(url_for('lista_escalas', username=username))
    dias_param = request.args.get('dias', '')
    if dias_param:
        datas_sel = set(d.strip() for d in dias_param.split(',') if d.strip())
        dias_filtrados = {k: v for k, v in escala['dias'].items() if k in datas_sel}
    else:
        dias_filtrados = escala['dias']
    escala_print = dict(escala, dias=dias_filtrados)
    return render_template('usuario/escalas/imprimir.html', username=username, escala=escala_print, cargos=CARGOS)

@app.route('/usuario/<username>/escalas/<escala_id>/excluir/', methods=['POST'])
@acesso_usuario
def excluir_escala(username, escala_id):
    escalas = [e for e in get_escalas(username) if e['id'] != escala_id]
    save_escalas(username, escalas)
    flash('Escala excluída.', 'sucesso')
    return redirect(url_for('lista_escalas', username=username))


@app.route('/usuario/<username>/escalas/dia-json/')
@acesso_usuario
def dia_json_endpoint(username):
    data_str = request.args.get('data', '')
    dias = _get_dias_existentes(get_escalas(username))
    if data_str in dias:
        return jsonify({'encontrado': True, 'dia': dias[data_str]})
    return jsonify({'encontrado': False})


def _local_para_cargo(local, caixas_config):
    """Mapeia string de local para (cargo, caixa_numero, caixa_id, caixa_tipo)."""
    ll = local.strip().lower()
    if ll.startswith('caixa'):
        parts = local.strip().split()
        num = parts[1] if len(parts) > 1 else '?'
        cx = next(
            (c for c in caixas_config
             if str(c.get('numero', '')).zfill(2) == num.zfill(2)
             or str(c.get('numero', '')) == num),
            None
        )
        return ('operador_caixa', num, cx['id'] if cx else None, cx.get('tipo', 'normal') if cx else 'normal')
    elif 'supervisor' in ll:
        return ('supervisor', None, None, None)
    elif 'embalador' in ll:
        return ('embalador', None, None, None)
    elif 'guarda' in ll or 'volume' in ll:
        return ('guarda_volumes', None, None, None)
    return (None, None, None, None)


@app.route('/usuario/<username>/escalas/adicionar/', methods=['GET', 'POST'])
@acesso_usuario
def adicionar_escala(username):
    config = get_config(username)
    funcionarios = get_funcionarios(username)
    locais = [f"Caixa {cx.get('numero', '').zfill(2)}" for cx in config.get('caixas', [])]
    locais += ['Supervisor', 'Embalador', 'Guarda-Volumes']
    turnos_config = config.get('turnos', {})

    if request.method == 'POST':
        data_str = request.form.get('data', '').strip()
        try:
            data_obj = date.fromisoformat(data_str)
        except ValueError:
            flash('Data inválida.', 'erro')
            return redirect(request.url)

        # Coleta linhas do formulário dinâmico
        func_ids  = request.form.getlist('func_id[]')
        turnos_l  = request.form.getlist('turno[]')
        locais_l  = request.form.getlist('local[]')
        destinos  = request.form.getlist('destino[]')

        # Agrupa em estrutura de dia
        turnos_resultado = {}
        for i, func_id in enumerate(func_ids):
            if not func_id:
                continue
            func = next((f for f in funcionarios if f['id'] == func_id), None)
            if not func:
                continue
            turno_nome = turnos_l[i] if i < len(turnos_l) else ''
            local      = locais_l[i] if i < len(locais_l) else ''
            destino    = destinos[i].strip() if i < len(destinos) else ''

            cargo, cx_num, cx_id, cx_tipo = _local_para_cargo(local, config.get('caixas', []))
            if not cargo:
                continue

            entry = {'id': func['id'], 'nome': func['nome'], 'tipo': 'manual'}
            if cx_num:
                entry.update({'caixa_numero': cx_num, 'caixa_id': cx_id, 'caixa_tipo': cx_tipo})
            if destino:
                entry['destino'] = destino

            if turno_nome not in turnos_resultado:
                tc = turnos_config.get(turno_nome, {})
                turnos_resultado[turno_nome] = {
                    'horario': f"{tc.get('horario_inicio','?')} - {tc.get('horario_fim','?')}",
                    'cargos': {}
                }
            cargos = turnos_resultado[turno_nome]['cargos']
            if cargo not in cargos:
                cargos[cargo] = {'nome': CARGOS.get(cargo, cargo), 'necessario': 0, 'funcionarios': []}
            cargos[cargo]['funcionarios'].append(entry)
            cargos[cargo]['necessario'] = len(cargos[cargo]['funcionarios'])

        dia_novo = {
            'data': data_str,
            'dia_semana': DIAS_PT[data_obj.weekday()],
            'manual': True,
            'turnos': turnos_resultado,
        }

        # Upsert: encontra escala existente que cobre este dia e atualiza, ou cria nova
        escalas = get_escalas(username)
        escala_alvo = next((e for e in escalas if data_str in e.get('dias', {})), None)
        if escala_alvo:
            escala_alvo['dias'][data_str] = dia_novo
            save_escalas(username, escalas)
            flash('Escala do dia atualizada com sucesso.', 'sucesso')
            return redirect(url_for('ver_escala', username=username, escala_id=escala_alvo['id']))
        else:
            nova = {
                'id': str(uuid.uuid4()),
                'data_inicio': data_str, 'data_fim': data_str,
                'manual': True,
                'dias': {data_str: dia_novo},
                'alertas': [],
            }
            escalas.insert(0, nova)
            save_escalas(username, escalas)
            flash('Escala do dia criada com sucesso.', 'sucesso')
            return redirect(url_for('ver_escala', username=username, escala_id=nova['id']))

    # Pré-carrega dia existente se ?data= passado na URL
    data_pre = request.args.get('data', '')
    dia_existente = None
    if data_pre:
        dias = _get_dias_existentes(get_escalas(username))
        dia_existente = dias.get(data_pre)

    return render_template(
        'usuario/escalas/adicionar.html',
        username=username,
        funcionarios=sorted(funcionarios, key=lambda f: f.get('nome', '')),
        locais=locais,
        turnos=list(turnos_config.keys()),
        data_pre=data_pre,
        dia_existente=dia_existente,
    )


# ── Gerar Escalas ─────────────────────────────────────────────────────────────

@app.route('/usuario/<username>/gerar-escalas/caixas-json/')
@acesso_usuario
def caixas_json(username):
    return jsonify(get_config(username).get('caixas', []))

@app.route('/usuario/<username>/gerar-escalas/')
@acesso_usuario
def gerar_escalas(username):
    config = get_config(username)
    return render_template('usuario/gerar_escalas/index.html', username=username, config=config)

@app.route('/usuario/<username>/gerar-escalas/configuracoes/', methods=['GET', 'POST'])
@acesso_usuario
def configuracoes_escala(username):
    config = get_config(username)
    if request.method == 'POST':
        config['turnos_fixos'] = 'turnos_fixos' in request.form
        config['periodo_geracao_dias'] = int(request.form.get('periodo_dias', 7))
        for turno in ['manha', 'tarde']:
            config['turnos'][turno] = {
                'horario_inicio': request.form.get(f'{turno}_inicio', ''),
                'horario_fim': request.form.get(f'{turno}_fim', ''),
                'supervisores': int(request.form.get(f'{turno}_supervisores', 0)),
                'operadores_caixa': int(request.form.get(f'{turno}_caixas', 0)),
                'embaladores': int(request.form.get(f'{turno}_embaladores', 0)),
                'guarda_volumes': int(request.form.get(f'{turno}_guarda_volumes', 0)),
            }
        # Salva caixas
        numeros = request.form.getlist('caixa_numero')
        tipos = request.form.getlist('caixa_tipo')
        ids = request.form.getlist('caixa_id')
        restricoes_erg = request.form.getlist('caixa_restricoes')
        caixas = []
        for i, num in enumerate(numeros):
            num = num.strip()
            if num:
                status_turno = {}
                for turno in config.get('turnos', {}).keys():
                    chave = f'caixa_status_{turno}_{i}'
                    # checkbox marcado → 'aberto'; desmarcado → nada enviado → 'fechado'
                    status_turno[turno] = 'aberto' if request.form.get(chave) else 'fechado'
                caixas.append({
                    'id': ids[i] if i < len(ids) and ids[i] else str(uuid.uuid4()),
                    'numero': num,
                    'tipo': tipos[i] if i < len(tipos) else 'normal',
                    'restricoes_ergonomicas': restricoes_erg[i].strip() if i < len(restricoes_erg) else '',
                    'status_turno': status_turno,
                })
        config['caixas'] = caixas
        # Feriados locais
        datas_fl = request.form.getlist('feriado_local_data')
        nomes_fl = request.form.getlist('feriado_local_nome')
        config['feriados_locais'] = [
            {'data': d.strip(), 'nome': n.strip()}
            for d, n in zip(datas_fl, nomes_fl)
            if d.strip()
        ]
        save_config(username, config)
        flash('Configurações salvas.', 'sucesso')
        return redirect(url_for('gerar_escalas', username=username))
    return render_template('usuario/gerar_escalas/configuracoes.html', username=username, config=config)

@app.route('/usuario/<username>/gerar-escalas/gerar/', methods=['POST'])
@acesso_usuario
def processar_geracao(username):
    data_inicio_str = request.form.get('data_inicio', '')
    try:
        data_inicio = date.fromisoformat(data_inicio_str)
    except ValueError:
        flash('Data inválida.', 'erro')
        return redirect(url_for('gerar_escalas', username=username))

    config = get_config(username)
    funcionarios = get_funcionarios(username)
    periodo = config.get('periodo_geracao_dias', 7)
    data_fim = data_inicio + timedelta(days=periodo - 1)

    # Feriados nacionais (fixos + móveis) + locais configurados
    feriados_br = [d.isoformat() for d in feriados_brasil(data_inicio.year)]
    if data_fim.year != data_inicio.year:
        feriados_br += [d.isoformat() for d in feriados_brasil(data_fim.year)]
    feriados_locais = [f['data'] for f in config.get('feriados_locais', [])]
    todos_feriados = list(dict.fromkeys(feriados_br + feriados_locais))  # deduplica mantendo ordem
    nomes_feriados = {f['data']: f['nome'] for f in config.get('feriados_locais', [])}
    feriados_no_periodo = [
        d for d in todos_feriados
        if data_inicio <= date.fromisoformat(d) <= data_fim
    ]

    if feriados_no_periodo:
        session['escala_pendente'] = {
            'data_inicio': data_inicio_str,
            'feriados': feriados_no_periodo,
            'nomes_feriados': nomes_feriados,
        }
        return redirect(url_for('confirmar_feriados', username=username))

    escalas_salvas = get_escalas(username)
    historico_caixas = _get_historico_caixas(escalas_salvas)
    dias_existentes = _get_dias_existentes(escalas_salvas)
    resultado = gerar_escala_semana(funcionarios, config, data_inicio, historico_caixas=historico_caixas, dias_existentes=dias_existentes)
    escala = {
        'id': str(uuid.uuid4()),
        'data_inicio': data_inicio_str,
        'data_fim': data_fim.isoformat(),
        'dias': resultado['dias'],
        'alertas': resultado['alertas'],
    }
    escalas = get_escalas(username)
    escalas.insert(0, escala)
    save_escalas(username, escalas)

    if resultado['alertas']:
        for alerta in resultado['alertas']:
            flash(alerta, 'aviso')

    flash('Escala gerada com sucesso.', 'sucesso')
    return redirect(url_for('ver_escala', username=username, escala_id=escala['id']))

@app.route('/usuario/<username>/gerar-escalas/feriados/', methods=['GET', 'POST'])
@acesso_usuario
def confirmar_feriados(username):
    pendente = session.get('escala_pendente')
    if not pendente:
        return redirect(url_for('gerar_escalas', username=username))

    funcionarios = get_funcionarios(username)
    feriados = pendente['feriados']
    data_inicio = date.fromisoformat(pendente['data_inicio'])
    config = get_config(username)

    if request.method == 'POST':
        feriados_confirmados = {}
        for f_data in feriados:
            selecionados = request.form.getlist(f'feriado_{f_data}')
            if selecionados:
                feriados_confirmados[f_data] = selecionados

        periodo = config.get('periodo_geracao_dias', 7)
        data_fim = data_inicio + timedelta(days=periodo - 1)
        escalas_salvas = get_escalas(username)
        historico_caixas = _get_historico_caixas(escalas_salvas)
        dias_existentes = _get_dias_existentes(escalas_salvas)
        resultado = gerar_escala_semana(funcionarios, config, data_inicio, feriados_confirmados, historico_caixas, dias_existentes)

        escala = {
            'id': str(uuid.uuid4()),
            'data_inicio': pendente['data_inicio'],
            'data_fim': data_fim.isoformat(),
            'dias': resultado['dias'],
            'alertas': resultado['alertas'],
        }
        escalas = get_escalas(username)
        escalas.insert(0, escala)
        save_escalas(username, escalas)
        session.pop('escala_pendente', None)

        flash('Escala gerada com feriados confirmados.', 'sucesso')
        return redirect(url_for('ver_escala', username=username, escala_id=escala['id']))

    nomes_feriados = pendente.get('nomes_feriados', {})
    # Para cada feriado, listar funcionários disponíveis
    info_feriados = []
    for f_data in feriados:
        d = date.fromisoformat(f_data)
        disponiveis = funcionarios_disponiveis_feriado(funcionarios, d)
        info_feriados.append({
            'data': f_data,
            'nome': nomes_feriados.get(f_data, ''),
            'funcionarios': disponiveis,
        })

    return render_template('usuario/gerar_escalas/feriado.html', username=username,
                           info_feriados=info_feriados, cargos=CARGOS)


# ── Utilitários ───────────────────────────────────────────────────────────────

def _form_to_funcionario(form):
    return {
        'nome': form.get('nome', '').strip(),
        'data_admissao': form.get('data_admissao', ''),
        'cargo_primario': form.get('cargo_primario', ''),
        'cargo_secundario': form.get('cargo_secundario', ''),
        'turno': form.get('turno', 'manha'),
        'regime_trabalho': form.get('regime_trabalho', '44h'),
        'folga_5x2_ref': form.get('folga_5x2_ref', '') or None,
        'rotacao_domingo': int(form.get('rotacao_domingo', 2)),
        'domingo_ref': form.get('domingo_ref', '') or None,
        'folga_semana': form.get('folga_semana', '') or None,
        'folga_feriado': 'folga_feriado' in form,
        'ferias_inicio': form.get('ferias_inicio', '') or None,
        'ferias_fim': form.get('ferias_fim', '') or None,
        'velocidade': form.get('velocidade', 'normal'),
        'caixas_preferidos': form.getlist('caixas_preferidos'),
        'caixa_fixo': form.get('caixa_fixo') or None,
        'domingos_folga': int(form.get('domingos_folga', 1)),
        'observacoes': form.get('observacoes', '').strip(),
        'avaliacoes': form.get('avaliacoes', '').strip(),
        'recomendacoes': form.get('recomendacoes', '').strip(),
        'restricoes': form.get('restricoes', '').strip(),
    }


def _get_historico_caixas(escalas):
    """Reconstrói o histórico de caixas de cada operador a partir das escalas salvas.
    Cada data é contada uma única vez (versão mais recente prevalece) e em ordem cronológica.
    """
    # Deduplica: mesma data em múltiplas escalas → usa a mais recente
    dias_por_data = {}
    for escala in reversed(escalas):  # mais antigas primeiro; mais recente sobrescreve
        for data_str, dia in escala.get('dias', {}).items():
            dias_por_data[data_str] = dia

    historico = {}
    for data_str in sorted(dias_por_data):
        dia = dias_por_data[data_str]
        for turno in dia.get('turnos', {}).values():
            ops = turno.get('cargos', {}).get('operador_caixa', {}).get('funcionarios', [])
            for op in ops:
                if op.get('id') and op.get('caixa_id'):
                    hist = historico.setdefault(op['id'], [])
                    hist.append(op['caixa_id'])
                    if len(hist) > 30:
                        hist.pop(0)
    return historico


def _get_dias_existentes(escalas):
    """Mapeia datas já geradas em escalas salvas para seus dados de dia.
    Quando a mesma data aparece em mais de uma escala, prevalece a da escala mais recente.
    """
    dias = {}
    for escala in reversed(escalas):  # mais antigas primeiro; mais recente sobrescreve
        for data_str, dia in escala.get('dias', {}).items():
            dias[data_str] = dia
    return dias


# ── Inicialização ─────────────────────────────────────────────────────────────

def init_admin():
    users = load_users()
    if 'admin' not in users:
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        users['admin'] = {'senha': generate_password_hash('admin123'), 'papel': 'admin'}
        save_users(users)
        print('Admin criado — senha padrão: admin123')

init_admin()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
