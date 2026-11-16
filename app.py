import streamlit as st
import pandas as pd
import random
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# ==============================================================================
# 1. CONFIGURAÇÕES GERAIS E CONSTANTES
# ==============================================================================
AVALIADORAS_TODAS = ["Fatima", "Lindalva", "Rosana"]
SUPERVISOR_MAX_POR_PESSOA = 4

# Metas Globais do Contrato (36 no total)
TOTAL_AVALIACOES_MES = 36

# Definição exata das Cotas por Criticidade (17 + 10 + 9 = 36)
METAS_COTAS = {
    "Crítica": 17,        # 12 áreas críticas aleatórias + 5 fixas obrigatórias
    "Semi-crítica": 10,   # Ambulatórios, Banheiros, etc.
    "Não-crítica": 9      # Áreas Administrativas
}

AREAS_FIXAS_OBRIGATORIAS = [
    "Divisão de Nutrição e Dietética", 
    "Centro Cirúrgico Central", 
    "Centro Cirúrgico Ambulatorial", 
    "Unidade de Emergência Referenciada Adulto", 
    "Unidade de Emergência Referenciada Infantil"
]

# Dados de contingência
DADOS_PADRAO = {
    "Area": [
        "Divisão de Nutrição e Dietética", "Centro Cirúrgico Central", "Centro Cirúrgico Ambulatorial", "Unidade de Emergência Referenciada Adulto", "Unidade de Emergência Referenciada Infantil",
        "UTI E2", "UTI D2", "Enfermaria de Pediatria", "Enfermaria de Psiquiatria",
        "Ambulatório de Oftalmo", "Ambulatório de Pediatria", "Vestiário Masculino", "Banheiro Alta Circulação", "Endoscopia",
        "Faturamento", "RH", "Diretoria Clinica"
    ],
    "Subtipo": [
        "Fixo", "Fixo", "Fixo", "Fixo", "Fixo",
        "UTI", "UTI", "Enfermaria", "Enfermaria",
        "Ambulatorio", "Ambulatorio", "Banheiros", "Banheiros", "Procedimento",
        "Administrativa", "Administrativa", "Administrativa"
    ],
    "Criticidade": [
        "Crítica", "Crítica", "Crítica", "Crítica", "Crítica",
        "Crítica", "Crítica", "Crítica", "Crítica",
        "Semi-crítica", "Semi-crítica", "Semi-crítica", "Semi-crítica", "Semi-crítica",
        "Não-crítica", "Não-crítica", "Não-crítica"
    ]
}

# Dicionário auxiliar de mapeamento
MAPEAMENTO_SUBTIPO_CRITICIDADE = {
    "Fixo": "Crítica",
    "UTI": "Crítica",
    "Enfermaria": "Crítica",
    "Ambulatorio": "Semi-crítica",
    "Banheiros": "Semi-crítica",
    "Procedimento": "Semi-crítica",
    "Administrativa": "Não-crítica"
}

# ==============================================================================
# 2. INTELIGÊNCIA DE FECHAMENTO (REGRA DO DIA 20)
# ==============================================================================
def obter_mes_competencia(data_str):
    """
    Calcula a competência fiscal baseada no dia 20 de cada mês.
    Exemplo: 2026-06-21 vira '2026-07'
    """
    dt = datetime.strptime(data_str, "%Y-%m-%d %H:%M")
    if dt.day >= 21:
        ano = dt.year + (1 if dt.month == 12 else 0)
        mes = 1 if dt.month == 12 else dt.month + 1
        return f"{ano}-{mes:02d}"
    else:
        return dt.strftime("%Y-%m")

# ==============================================================================
# 3. CONEXÃO E FUNÇÕES DE TRATAMENTO / FIREBASE
# ==============================================================================
def padronizar_dados(df):
    if "Area" in df.columns:
        df["Area"] = df["Area"].astype(str).str.strip()
        mapeamento = {
            "UER": "Unidade de Emergência Referenciada Adulto",
            "UER Pediatrica": "Unidade de Emergência Referenciada Pediátrica",
            "UER Pediátrica": "Unidade de Emergência Referenciada Pediátrica"
        }
        df["Area"] = df["Area"].replace(mapeamento)
    return df

if not firebase_admin._apps:
    try:
        firebase_secrets = dict(st.secrets["firebase"])
        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred)
    except Exception:
        try:
            cred = credentials.Certificate("sua-chave-firebase.json")
            firebase_admin.initialize_app(cred)
        except Exception:
            st.error("Erro Crítico: Credenciais do Google Firebase não foram encontradas!")

db = firestore.client()

def carregar_historico_firebase():
    """Busca os dados e injeta dinamicamente as colunas necessárias para auditoria."""
    docs = db.collection("historico").stream()
    lista_dados = [doc.to_dict() for doc in docs]
    
    if lista_dados:
        df = pd.DataFrame(lista_dados)
        
        if "Criticidade" not in df.columns:
            df["Criticidade"] = None
            
        if "Subtipo" in df.columns:
            df["Criticidade"] = df["Criticidade"].fillna(df["Subtipo"].map(MAPEAMENTO_SUBTIPO_CRITICIDADE))
            
        df["Criticidade"] = df["Criticidade"].fillna("Não-crítica")
        df["Criticidade"] = df["Criticidade"].replace({"Procedimento": "Semi-crítica", "Administrativa": "Não-crítica"})
            
        df["Competência"] = df["Data"].apply(obter_mes_competencia)
        return df
        
    return pd.DataFrame(columns=["Data", "Competência", "Area", "Subtipo", "Criticidade", "Avaliador", "Supervisor_Presente"])

def salvar_no_firebase(dados_sorteio):
    id_unico = datetime.now().strftime("%Y%m%d_%H%M%S")
    db.collection("historico").document(id_unico).set(dados_sorteio)

def carregar_areas_do_firebase():
    """Tenta buscar a planilha salva no Firebase. Se não achar, usa os DADOS_PADRAO."""
    try:
        doc_ref = db.collection("configuracoes").document("areas")
        doc = doc_ref.get()
        if doc.exists:
            dados = doc.to_dict()
            if "lista" in dados:
                return pd.DataFrame(dados["lista"])
    except Exception:
        pass
    return pd.DataFrame(DADOS_PADRAO)

def salvar_areas_no_firebase(df):
    """Salva a planilha no Firebase."""
    colunas_obrigatorias = ["Area", "Subtipo", "Criticidade"]
    df_filtrado = df[colunas_obrigatorias].dropna(subset=["Area"]).copy()
    dados_dict = df_filtrado.to_dict(orient="records")
    db.collection("configuracoes").document("areas").set({"lista": dados_dict})

# ==============================================================================
# 4. INTERFACE E BARRA LATERAL (STREAMLIT)
# ==============================================================================
st.set_page_config(page_title="Gestor de Avaliação CADTERC", layout="centered")
st.title("🧼 Sorteio de Avaliação Hospitalar (Regras CADTERC)")
st.markdown("---")

# Painel A: Controle de Frequência da Equipe
st.sidebar.header("👥 Status da Equipe")
avaliadoras_ativas = []
for av in AVALIADORAS_TODAS:
    if st.sidebar.checkbox(f"👤 {av} está Disponível", value=True, key=f"presenca_{av}"):
        avaliadoras_ativas.append(av)

# Painel B: Upload e Persistência da Base de Dados
st.sidebar.markdown("---")
st.sidebar.header("📁 Base de Dados")

df_areas = carregar_areas_do_firebase()
df_areas = padronizar_dados(df_areas)

arquivo_upload = st.sidebar.file_uploader("Suba uma nova planilha para atualizar (Colunas: Area, Subtipo, Criticidade)", type=["csv", "xlsx"])

if arquivo_upload is not None:
    df_novo = pd.read_csv(arquivo_upload) if arquivo_upload.name.endswith('.csv') else pd.read_excel(arquivo_upload)
    df_novo = padronizar_dados(df_novo)
    
    if "Area" in df_novo.columns and "Subtipo" in df_novo.columns:
        if "Criticidade" not in df_novo.columns:
            df_novo["Criticidade"] = df_novo["Subtipo"].map(MAPEAMENTO_SUBTIPO_CRITICIDADE).fillna("Não-crítica")
            
        st.sidebar.warning("⚠️ Nova planilha detectada na memória temporária!")
        
        if st.sidebar.button("💾 Salvar Base no Banco de Dados", type="primary"):
            salvar_areas_no_firebase(df_novo)
            st.sidebar.success("✅ Salvo com sucesso no Firebase!")
            st.rerun()
            
        df_areas = df_novo
    else:
        st.sidebar.error("A planilha precisa ter pelo menos as colunas 'Area' e 'Subtipo'!")

# ==============================================================================
# 5. PROCESSAMENTO DE METAS E DADOS LOCAIS
# ==============================================================================
df_hist = carregar_historico_firebase()
data_hora_atual_str = datetime.now().strftime("%Y-%m-%d %H:%M")
competencia_atual = obter_mes_competencia(data_hora_atual_str)

df_mes = df_hist[df_hist["Competência"] == competencia_atual] if not df_hist.empty else pd.DataFrame()

total_mes = len(df_mes)
areas_sorteadas_no_mes = df_mes["Area"].values if not df_mes.empty else []
fixas_sorteadas = [area for area in AREAS_FIXAS_OBRIGATORIAS if area in areas_sorteadas_no_mes]

qtd_atual_cota = {
    "Crítica": len(df_mes[df_mes["Criticidade"] == "Crítica"]) if not df_mes.empty else 0,
    "Semi-crítica": len(df_mes[df_mes["Criticidade"] == "Semi-crítica"]) if not df_mes.empty else 0,
    "Não-crítica": len(df_mes[df_mes["Criticidade"] == "Não-crítica"]) if not df_mes.empty else 0
}

# Estatísticas na Barra Lateral
st.sidebar.markdown(f"### 📊 Ciclo de Fechamento: `{competencia_atual}`")
st.sidebar.info("Ciclo vigente: do dia 21 do mês anterior até o dia 20 do mês atual.")
st.sidebar.metric("Progresso do Ciclo", f"{total_mes} / {TOTAL_AVALIACOES_MES}")

st.sidebar.markdown("**Obrigatórias Fixas (No Ciclo):**")
st.sidebar.write(f"📌 Realizadas: {len(fixas_sorteadas)} / 5")

st.sidebar.markdown("**Cotas de Criticidade (CADTERC):**")
st.sidebar.write(f"🚨 Críticas (Comuns + Fixas): {qtd_atual_cota['Crítica']} / {METAS_COTAS['Crítica']}")
st.sidebar.write(f"🧪 Semi-críticas: {qtd_atual_cota['Semi-crítica']} / {METAS_COTAS['Semi-crítica']}")
st.sidebar.write(f"🏢 Não-críticas: {qtd_atual_cota['Não-crítica']} / {METAS_COTAS['Não-crítica']}")

contagem_avaliadoras = {av: 0 for av in AVALIADORAS_TODAS}
acompanhamentos_sup = {av: 0 for av in AVALIADORAS_TODAS}
if not df_mes.empty:
    for av in AVALIADORAS_TODAS:
        if "Avaliador" in df_mes.columns:
            contagem_avaliadoras[av] = len(df_mes[df_mes["Avaliador"] == av])
        if "Avaliador" in df_mes.columns and "Supervisor_Presente" in df_mes.columns:
            acompanhamentos_sup[av] = len(df_mes[(df_mes["Avaliador"] == av) & (df_mes["Supervisor_Presente"] == "Sim")])

# ==============================================================================
# 6. ABAS DA APLICAÇÃO (SORTEIO / PAINEL DA EQUIPE / HISTÓRICO)
# ==============================================================================
aba_sorteio, aba_painel, aba_historico = st.tabs([
    "🎲 Realizar Sorteio", 
    "📊 Painel de Vistorias da Equipe", 
    "📜 Histórico Geral"
])

# ------------------------------------------------------------------------------
# ABA 1: SORTEIO
# ------------------------------------------------------------------------------
with aba_sorteio:
    st.subheader("🎲 Sorteio Inteligente do Dia")

    if st.button("Realizar Sorteio", type="primary"):
        if total_mes >= TOTAL_AVALIACOES_MES:
            st.warning("Meta global de 36 avaliações do ciclo já foi atingida!")
            st.stop()

        if not avaliadoras_ativas:
            st.error("Nenhuma avaliadora marcada como disponível na barra lateral!")
            st.stop()

        # Redistribui dinamicamente o teto mensal entre as pessoas presentes
        vagas_restantes_no_mes = TOTAL_AVALIACOES_MES - total_mes
        cota_dinamica_por_ativa = TOTAL_AVALIACOES_MES / len(avaliadoras_ativas)

        # Prioriza quem tem menos vistorias no mês entre as presentes (evita travar por ausência)
        min_vistorias_ativas = min(contagem_avaliadoras[av] for av in avaliadoras_ativas)
        disponiveis_hoje = [
            av for av in avaliadoras_ativas 
            if contagem_avaliadoras[av] == min_vistorias_ativas
        ]
        
        avaliadora_sorteada = random.choice(disponiveis_hoje)
        
        acomp_feitos = acompanhamentos_sup[avaliadora_sorteada]
        av_restantes = max(1, int(round(cota_dinamica_por_ativa)) - contagem_avaliadoras[avaliadora_sorteada])
        acomp_restantes = SUPERVISOR_MAX_POR_PESSOA - acomp_feitos
        
        if acomp_restantes <= 0:
            supervisor_status = "Não"
        elif acomp_restantes >= av_restantes:
            supervisor_status = "Sim"
        else:
            supervisor_status = "Sim" if random.random() < 0.5 else "Não"

        # ----------------------------------------------------------------------
        # LÓGICA DE SELEÇÃO PROPORCIONAL DE CRITICIDADE E SEM REPETIÇÃO
        # ----------------------------------------------------------------------
        fixas_pendentes = [area for area in AREAS_FIXAS_OBRIGATORIAS if area not in areas_sorteadas_no_mes]

        # Calcula quantas vagas faltam em cada cota de criticidade
        vagas_por_crit = {
            crit: max(0, METAS_COTAS[crit] - qtd_atual_cota[crit])
            for crit in METAS_COTAS
        }

        if sum(vagas_por_crit.values()) <= 0:
            st.warning("Todas as cotas do ciclo CADTERC atual foram preenchidas!")
            st.stop()

        # Sorteia a criticidade ponderada pelas vagas restantes (evita acumular Críticas no fim do mês)
        criticidades_possiveis = [c for c, v in vagas_por_crit.items() if v > 0]
        pesos_criticidade = [vagas_por_crit[c] for c in criticidades_possiveis]
        criticidade_escolhida = random.choices(criticidades_possiveis, weights=pesos_criticidade, k=1)[0]

        # Contagem histórica de visitas por área (para nunca repetir antes de esgotar 100%)
        areas_hist_lista = df_hist["Area"].tolist() if not df_hist.empty else []
        contagem_historico = pd.Series(areas_hist_lista).value_counts()

        df_base = df_areas.copy()
        df_base["vezes_sorteada"] = df_base["Area"].map(contagem_historico).fillna(0).astype(int)

        # NUNCA repete uma área já sorteada dentro do mesmo ciclo mensal
        df_nao_sorteadas_mes = df_base[~df_base["Area"].isin(areas_sorteadas_no_mes)]
        if df_nao_sorteadas_mes.empty:
            df_nao_sorteadas_mes = df_base.copy()

        # Se a criticidade sorteada foi Crítica e ainda há áreas fixas obrigatórias pendentes,
        # distribui as fixas proporcionalmente ao longo de todo o mês (não só nos últimos 5 dias)
        vagas_criticas_restantes = vagas_por_crit["Crítica"]
        if (
            criticidade_escolhida == "Crítica"
            and len(fixas_pendentes) > 0
            and random.random() < (len(fixas_pendentes) / max(1, vagas_criticas_restantes))
        ):
            df_candidatas = df_nao_sorteadas_mes[df_nao_sorteadas_mes["Area"].isin(fixas_pendentes)]
        else:
            # Filtra pela criticidade escolhida, excluindo fixas já realizadas no mês
            df_candidatas = df_nao_sorteadas_mes[df_nao_sorteadas_mes["Criticidade"] == criticidade_escolhida]
            if criticidade_escolhida == "Crítica":
                # Evita sortear áreas fixas repetidas e reserva o slot proporcional das fixas
                df_comuns = df_candidatas[~df_candidatas["Area"].isin(AREAS_FIXAS_OBRIGATORIAS)]
                if not df_comuns.empty and (vagas_criticas_restantes > len(fixas_pendentes)):
                    df_candidatas = df_comuns

        # Fallback caso alguma categoria específica esteja vazia na base
        if df_candidatas.empty:
            df_candidatas = df_nao_sorteadas_mes.copy()

        # Prioriza estritamente as áreas com MENOR número de visitas no histórico global (0 visitas primeiro)
        min_visitas = df_candidatas["vezes_sorteada"].min()
        df_menor_frequencia = df_candidatas[df_candidatas["vezes_sorteada"] == min_visitas]

        area_sorteada_row = df_menor_frequencia.sample(n=1).iloc[0]
            
        st.success("🎉 Sorteio Concluído!")
        c1, c2 = st.columns(2)
        with c1:
            st.metric(label="📍 Área Sorteada", value=area_sorteada_row["Area"])
            st.caption(f"Tipo: {area_sorteada_row['Subtipo']} | Classificação: {area_sorteada_row['Criticidade']}")
        with c2:
            st.metric(label="👤 Avaliador(a)", value=avaliadora_sorteada)
            st.markdown(f"**Acompanhamento do Supervisor:** {'👀 SIM' if supervisor_status == 'Sim' else '❌ Não'}")
            
        dados_sorteio_atual = {
            "Data": data_hora_atual_str,
            "Area": str(area_sorteada_row["Area"]),
            "Subtipo": str(area_sorteada_row["Subtipo"]),
            "Criticidade": str(area_sorteada_row["Criticidade"]),
            "Avaliador": str(avaliadora_sorteada),
            "Supervisor_Presente": str(supervisor_status)
        }
        
        salvar_no_firebase(dados_sorteio_atual)
        st.rerun()

# ------------------------------------------------------------------------------
# ABA 2: PAINEL DE VISTORIAS DA EQUIPE
# ------------------------------------------------------------------------------
with aba_painel:
    st.subheader("📊 Painel de Desempenho da Equipe")
    
    if df_hist.empty:
        st.info("Ainda não existem vistorias registradas no banco de dados para exibir no painel.")
    else:
        opcao_filtro = st.radio(
            "Filtrar Período de Análise:",
            [f"Ciclo Atual ({competencia_atual})", "Todo o Histórico Acumulado"],
            horizontal=True
        )
        
        df_painel = df_mes.copy() if "Ciclo Atual" in opcao_filtro else df_hist.copy()
        
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric("Total de Vistorias", len(df_painel))
        with col_m2:
            sup_total = len(df_painel[df_painel["Supervisor_Presente"] == "Sim"]) if "Supervisor_Presente" in df_painel.columns else 0
            st.metric("Acompanhamentos de Supervisor", sup_total)
        with col_m3:
            criticas_total = len(df_painel[df_painel["Criticidade"] == "Crítica"]) if "Criticidade" in df_painel.columns else 0
            st.metric("Vistorias em Áreas Críticas", criticas_total)
            
        st.markdown("---")
        st.markdown("### 👤 Vistorias Realizadas por Avaliadora")
        
        meta_ref = max(1, int(round(TOTAL_AVALIACOES_MES / max(1, len(avaliadoras_ativas)))))
        cols_p = st.columns(len(AVALIADORAS_TODAS))
        for idx, av in enumerate(AVALIADORAS_TODAS):
            with cols_p[idx]:
                qtd_feita = len(df_painel[df_painel["Avaliador"] == av]) if "Avaliador" in df_painel.columns else 0
                st.metric(
                    label=f"👤 {av}", 
                    value=f"{qtd_feita} / {meta_ref}", 
                    delta=f"{(qtd_feita / meta_ref) * 100:.0f}% da cota" if "Ciclo Atual" in opcao_filtro else None
                )
                
                if "Supervisor_Presente" in df_painel.columns and "Avaliador" in df_painel.columns:
                    sup_ind = len(df_painel[(df_painel["Avaliador"] == av) & (df_painel["Supervisor_Presente"] == "Sim")])
                    st.caption(f"👀 Acompanhadas pelo Supervisor: {sup_ind}")
                    
        st.markdown("---")
        st.markdown("### 📋 Distribuição de Vistorias por Criticidade de Área")
        
        if "Avaliador" in df_painel.columns and "Criticidade" in df_painel.columns and not df_painel.empty:
            tabela_cruzada = pd.crosstab(
                df_painel["Avaliador"], 
                df_painel["Criticidade"], 
                margins=True, 
                margins_name="Total Realizado"
            )
            st.dataframe(tabela_cruzada, use_container_width=True)
            
            st.markdown("#### 📈 Comparativo Gráfico de Trabalho")
            df_chart = df_painel.groupby(["Avaliador", "Criticidade"]).size().unstack(fill_value=0)
            st.bar_chart(df_chart)

# ------------------------------------------------------------------------------
# ABA 3: HISTÓRICO GERAL
# ------------------------------------------------------------------------------
with aba_historico:
    st.subheader("📜 Histórico Completo de Sorteios")
    if not df_hist.empty:
        colunas_ordenadas = ["Data", "Competência", "Area", "Subtipo", "Criticidade", "Avaliador", "Supervisor_Presente"]
        df_exibicao = df_hist[colunas_ordenadas].sort_values(by="Data", ascending=False)
        st.dataframe(df_exibicao, use_container_width=True)
    else:
        st.info("Nenhum registro de sorteio encontrado no sistema cloud.")
