import streamlit as st
import pandas as pd
import random
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# --- CONFIGURAÇÕES INICIAIS ---
AVALIADORAS_TODAS = ["Fatima", "Lindalva", "Rosana"]
AVALIADORAS_MAX = 10
SUPERVISOR_MAX_POR_PESSOA = 4

DADOS_PADRAO = {
    "Area": [
        "UTI E2", "UTI D2", "UTI E3", "Centro Cirúrgico", "Centro Cirúrgico Ambulatorial",
        "Ambulatório de Oftalmo", "Ambulatório de Pediatria", "Ambulatório de Psiquiatria",
        "Enfermaria de Pediatria", "Enfermaria de Psiquiatria", "Endoscopia", "Hemodialise",
        "Faturamento", "RH", "Diretoria Clinica"
    ],
    "Subtipo": [
        "UTI", "UTI", "UTI", "Procedimento", "Procedimento",
        "Ambulatorio", "Ambulatorio", "Ambulatorio",
        "Enfermaria", "Enfermaria", "Procedimento", "Procedimento",
        "Administrativa", "Administrativa", "Administrativa"
    ]
}

# --- CONEXÃO COM O FIREBASE ---
# No Streamlit Cloud, guardamos as credenciais em "Secrets" por segurança.
if not firebase_admin._apps:
    try:
        # Tenta ler das configurações secretas do Streamlit Cloud
        firebase_secrets = dict(st.secrets["firebase"])
        cred = credentials.Certificate(firebase_secrets)
        firebase_admin.initialize_app(cred)
    except Exception:
        # Se estiver rodando local na sua casa, lê o arquivo json que você baixou
        try:
            cred = credentials.Certificate("sua-chave-firebase.json")
            firebase_admin.initialize_app(cred)
        except Exception:
            st.error("Erro: Arquivo de credenciais do Firebase não encontrado!")

db = firestore.client()

# --- FUNÇÕES DO BANCO DE DADOS ---
def carregar_historico_firebase():
    docs = db.collection("historico").stream()
    lista_dados = []
    for doc in docs:
        lista_dados.append(doc.to_dict())
    if lista_dados:
        return pd.DataFrame(lista_dados)
    return pd.DataFrame(columns=["Data", "Area", "Subtipo", "Avaliador", "Supervisor_Presente"])

def salvar_no_firebase(dados_dicionario):
    # Salva uma nova avaliação no banco de dados com um ID único baseado no tempo
    id_unico = datetime.now().strftime("%Y%m%d_%H%M%S")
    db.collection("historico").document(id_unico).set(dados_dicionario)

st.set_page_config(page_title="Gestor de Avaliação", layout="centered")
st.title("🧼 Sistema de Sorteio de Avaliação + Google Firebase")
st.markdown("---")

# --- PAINEL LATERAL: CONTROLE DE PRESENÇA ---
st.sidebar.header("👥 Status da Equipe")
avaliadoras_ativas = []
for av in AVALIADORAS_TODAS:
    if st.sidebar.checkbox(f"👤 {av} está Disponível", value=True, key=f"presenca_{av}"):
        avaliadoras_ativas.append(av)

# --- CARREGAMENTO DE DADOS ---
st.sidebar.markdown("---")
st.sidebar.header("📁 Base de Dados")
arquivo_upload = st.sidebar.file_uploader("Suba sua planilha de áreas", type=["csv", "xlsx"])
df_areas = pd.read_csv(arquivo_upload) if arquivo_upload is not None and arquivo_upload.name.endswith('.csv') else (pd.read_excel(arquivo_upload) if arquivo_upload is not None else pd.DataFrame(DADOS_PADRAO))

# --- CÁLCULO DE METAS E COTAS (Puxando do Firebase) ---
df_hist = carregar_historico_firebase()
mes_atual = datetime.now().strftime("%Y-%m")
df_mes = df_hist[df_hist["Data"].str.startswith(mes_atual)] if not df_hist.empty else pd.DataFrame()

st.sidebar.markdown("### 📊 Estatísticas do Mês")
total_mes = len(df_mes)
st.sidebar.metric("Total de Avaliações (Meta: 30)", f"{total_mes} / 30")

contagem_avaliadoras = {av: 0 for av in AVALIADORAS_TODAS}
acompanhamentos_sup = {av: 0 for av in AVALIADORAS_TODAS}

if not df_mes.empty:
    for av in AVALIADORAS_TODAS:
        contagem_avaliadoras[av] = len(df_mes[df_mes["Avaliador"] == av])
        acompanhamentos_sup[av] = len(df_mes[(df_mes["Avaliador"] == av) & (df_mes["Supervisor_Presente"] == "Sim")])

st.sidebar.markdown("**Carga de Trabalho:**")
for av, qtd in contagem_avaliadoras.items():
    status_texto = " (Ausente)" if av not in avaliadoras_ativas else ""
    st.sidebar.write(f"👤 {av}{status_texto}: {qtd}/10")

# --- BOTÃO DE SORTEIO ---
st.subheader("🎲 Sorteio Inteligente do Dia")

if st.button("Realizar Sorteio", type="primary"):
    disponiveis_hoje = [av for av in avaliadoras_ativas if contagem_avaliadoras[av] < AVALIADORAS_MAX]
    
    if not disponiveis_hoje:
        st.error("Nenhuma avaliadora disponível para sorteio hoje!")
        st.stop()
        
    avaliadora_sorteada = random.choice(disponiveis_hoje)
    
    # Lógica do Supervisor
    acomp_feitos = acompanhamentos_sup[avaliadora_sorteada]
    av_avaliacoes_restantes = AVALIADORAS_MAX - contagem_avaliadoras[avaliadora_sorteada]
    acomp_restantes = SUPERVISOR_MAX_POR_PESSOA - acomp_feitos
    
    if acomp_restantes <= 0:
        supervisor_status = "Não"
    elif acomp_restantes >= av_avaliacoes_restantes:
        supervisor_status = "Sim"
    else:
        supervisor_status = "Sim" if random.random() < 0.5 else "Não"

    # Lógica das Áreas
    areas_sorteadas_no_mes = df_mes["Area"].values if not df_mes.empty else []
    areas_disponiveis = df_areas[~df_areas["Area"].isin(areas_sorteadas_no_mes)]
    if areas_disponiveis.empty:
        areas_disponiveis = df_areas
        
    subtipos_obrigatorios = ["UTI", "Ambulatorio", "Enfermaria", "Procedimento"]
    subtipos_nao_atendidos = [sub for sub in subtipos_obrigatorios if sub not in (df_mes["Subtipo"].values if not df_mes.empty else [])]
    areas_meta_pendente = areas_disponiveis[areas_disponiveis["Subtipo"].isin(subtipos_nao_atendidos)]
    
    if not areas_meta_pendente.empty:
        area_sorteada_row = areas_meta_pendente.sample(n=1).iloc[0]
    else:
        area_sorteada_row = areas_disponiveis.sample(n=1).iloc[0]
        
    # --- RESULTADOS ---
    st.success("🎉 Sorteio Concluído!")
    c1, c2 = st.columns(2)
    with c1:
        st.metric(label="📍 Área Sorteada", value=area_sorteada_row["Area"])
    with c2:
        st.metric(label="👤 Avaliador(a)", value=avaliadora_sorteada)
        st.markdown(f"**Acompanhamento do Supervisor:** {'👀 SIM' if supervisor_status == 'Sim' else '❌ Não'}")
        
    # Dicionário com os dados salvos
    dados_sorteio = {
        "Data": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Area": str(area_sorteada_row["Area"]),
        "Subtipo": str(area_sorteada_row["Subtipo"]),
        "Avaliador": str(avaliadora_sorteada),
        "Supervisor_Presente": str(supervisor_status)
    }
    
    salvar_no_firebase(dados_sorteio)
    st.rerun()

# --- HISTÓRICO ---
st.markdown("---")
st.subheader("📜 Prova Real (Histórico Directo do Firebase)")
if not df_hist.empty:
    st.dataframe(df_hist.sort_values(by="Data", ascending=False), use_container_width=True)
else:
    st.info("Nenhum registro encontrado no Firebase.")