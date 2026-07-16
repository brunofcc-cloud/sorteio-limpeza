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

# Metas Globais do Contrato (Atualizado para 36 no total e 12 por pessoa)
TOTAL_AVALIACOES_MES = 36
AVALIADORAS_MAX = 12  # Divisão exata: 12 para cada uma das 3 avaliadoras

# Definição exata das Cotas por Criticidade (17 + 10 + 9 = 36)
METAS_COTAS = {
    "Crítica": 17,        # 12 áreas críticas aleatórias + 5 fixas obrigatórias
    "Semi-crítica": 10,   # Ambulatórios, Banheiros, etc.
    "Não-crítica": 9      # Áreas Administrativas
}

AREAS_FIXAS_OBRIGATORIAS = [
    "Divisão de Nutrição Dietética", 
    "Centro Cirúrgico Central", 
    "Centro Cirúrgico Ambulatorial", 
    "UER", 
    "UER Pediatrica"
]

# Dados de contingência caso o usuário não faça o upload da planilha
DADOS_PADRAO = {
    "Area": [
        "Divisão de Nutrição Dietética", "Centro Cirúrgico Central", "Centro Cirúrgico Ambulatorial", "UER", "UER Pediatrica",
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

# Dicionário auxiliar para converter Subtipos antigos em Criticidades se o campo estiver ausente
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
    Exemplo: 2026-06-21 vira '2026-07' (Mês subsequente)
             2026-07-20 continua '2026-07' (Mês atual)
    """
    dt = datetime.strptime(data_str, "%Y-%m-%d %H:%M")
    if dt.day >= 21:
        ano = dt.year + (1 if dt.month == 12 else 0)
        mes = 1 if dt.month == 12 else dt.month + 1
        return f"{ano}-{mes:02d}"
    else:
        return dt.strftime("%Y-%m")

# ==============================================================================
# 3. CONEXÃO E FUNÇÕES DO BANCO DE DADOS (FIREBASE)
# ==============================================================================
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
        
        # 1. Se a coluna 'Criticidade' não existir de jeito nenhum no df, cria ela vazia
        if "Criticidade" not in df.columns:
            df["Criticidade"] = None
            
        # 2. Se houver valores nulos (NaN) na Criticidade, tenta mapear usando o Subtipo
        if "Subtipo" in df.columns:
            df["Criticidade"] = df["Criticidade"].fillna(df["Subtipo"].map(MAPEAMENTO_SUBTIPO_CRITICIDADE))
            
        # 3. Qualquer nulo restante ou termos antigos de transição são tratados
        df["Criticidade"] = df["Criticidade"].fillna("Não-crítica")
        df["Criticidade"] = df["Criticidade"].replace({"Procedimento": "Semi-crítica", "Administrativa": "Não-crítica"})
            
        df["Competência"] = df["Data"].apply(obter_mes_competencia)
        return df
        
    return pd.DataFrame(columns=["Data", "Competência", "Area", "Subtipo", "Criticidade", "Avaliador", "Supervisor_Presente"])

def salvar_no_firebase(dados_sorteio):
    id_unico = datetime.now().strftime("%Y%m%d_%H%M%S")
    db.collection("historico").document(id_unico).set(dados_sorteio)

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

# Painel B: Upload da Base de Dados
st.sidebar.markdown("---")
st.sidebar.header("📁 Base de Dados")
arquivo_upload = st.sidebar.file_uploader("Suba a planilha de áreas (Colunas: Area, Subtipo, Criticidade)", type=["csv", "xlsx"])

if arquivo_upload is not None:
    df_areas = pd.read_csv(arquivo_upload) if arquivo_upload.name.endswith('.csv') else pd.read_excel(arquivo_upload)
else:
    df_areas = pd.DataFrame(DADOS_PADRAO)

if "Criticidade" not in df_areas.columns:
    df_areas["Criticidade"] = "Não-crítica"

# ==============================================================================
# 5. PROCESSAMENTO DE METAS (JANELA DO DIA 21 AO DIA 20)
# ==============================================================================
df_hist = carregar_historico_firebase()
data_hora_atual_str = datetime.now().strftime("%Y-%m-%d %H:%M")
competencia_atual = obter_mes_competencia(data_hora_atual_str)

# Filtra o histórico focando apenas no ciclo atual
df_mes = df_hist[df_hist["Competência"] == competencia_atual] if not df_hist.empty else pd.DataFrame()

total_mes = len(df_mes)
areas_sorteadas_no_mes = df_mes["Area"].values if not df_mes.empty else []
fixas_sorteadas = [area for area in AREAS_FIXAS_OBRIGATORIAS if area in areas_sorteadas_no_mes]

# Contadores de cota seguros
qtd_atual_cota = {
    "Crítica": len(df_mes[df_mes["Criticidade"] == "Crítica"]) if not df_mes.empty else 0,
    "Semi-crítica": len(df_mes[df_mes["Criticidade"] == "Semi-crítica"]) if not df_mes.empty else 0,
    "Não-crítica": len(df_mes[df_mes["Criticidade"] == "Não-crítica"]) if not df_mes.empty else 0
}

# Exibição das estatísticas
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
# 6. MOTOR DE LÓGICA DE SORTEIO
# ==============================================================================
st.subheader("🎲 Sorteio Inteligente do Dia")

if st.button("Realizar Sorteio", type="primary"):
    disponiveis_hoje = [av for av in avaliadoras_ativas if contagem_avaliadoras[av] < AVALIADORAS_MAX]
    if not disponiveis_hoje:
        st.error("Limite mensal de sorteios para o ciclo atual atingido pelas avaliadoras ativas!")
        st.stop()
    avaliadora_sorteada = random.choice(disponiveis_hoje)
    
    acomp_feitos = acompanhamentos_sup[avaliadora_sorteada]
    av_restantes = AVALIADORAS_MAX - contagem_avaliadoras[avaliadora_sorteada]
    acomp_restantes = SUPERVISOR_MAX_POR_PESSOA - acomp_feitos
    
    if acomp_restantes <= 0:
        supervisor_status = "Não"
    elif acomp_restantes >= av_restantes:
        supervisor_status = "Sim"
    else:
        supervisor_status = "Sim" if random.random() < 0.5 else "Não"

    vagas_restantes_no_mes = TOTAL_AVALIACOES_MES - total_mes
    fixas_pendentes = [area for area in AREAS_FIXAS_OBRIGATORIAS if area not in areas_sorteadas_no_mes]
    
    if len(fixas_pendentes) >= vagas_restantes_no_mes and len(fixas_pendentes) > 0:
        area_escolhida_nome = random.choice(fixas_pendentes)
        area_sorteada_row = df_areas[df_areas["Area"] == area_escolhida_nome].iloc[0]
    else:
        areas_disponiveis_pool = df_areas[~df_areas["Area"].isin(areas_sorteadas_no_mes)]
        if areas_disponiveis_pool.empty:
            areas_disponiveis_pool = df_areas
            
        lista_final_sorteio = []
        for _, row in areas_disponiveis_pool.iterrows():
            crit = row["Criticidade"]
            if row["Area"] in fixas_pendentes:
                lista_final_sorteio.append(row)
            elif crit in METAS_COTAS and qtd_atual_cota[crit] < METAS_COTAS[crit]:
                lista_final_sorteio.append(row)
                
        if not lista_final_sorteio:
            st.warning("Todas as cotas do ciclo CADTERC atual foram preenchidas!")
            st.stop()
            
        area_sorteada_row = random.choice(lista_final_sorteio)
        
    # ==============================================================================
    # 7. EXIBIÇÃO E PERSISTÊNCIA DOS DADOS
    # ==============================================================================
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

st.markdown("---")
st.subheader("📜 Histórico Geral")
if not df_hist.empty:
    colunas_ordenadas = ["Data", "Competência", "Area", "Subtipo", "Criticidade", "Avaliador", "Supervisor_Presente"]
    df_exibicao = df_hist[colunas_ordenadas].sort_values(by="Data", ascending=False)
    st.dataframe(df_exibicao, use_container_width=True)
else:
    st.info("Nenhum registro de sorteio encontrado no sistema cloud.")