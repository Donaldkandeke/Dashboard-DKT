import streamlit as st
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import folium_static
import plotly.express as px
import io

# Configuration de la page
st.set_page_config(page_title="Quick Sales", page_icon="🌍", layout="wide")
st.header(":bar_chart: DKT Dashboard")
st.markdown('<style>div.block-container{padding-top:2rem;}</style>', unsafe_allow_html=True)

# Réglage des retries pour les requêtes HTTP
session = requests.Session()
retry = Retry(total=5, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry)
session.mount('https://', adapter)

# Mise en cache des données pour éviter des appels multiples à l'API
@st.cache_data
def download_kobo_data(api_url, headers):
    try:
        response = session.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Erreur lors de la récupération des données : {e}")
        return None

# URL de l'API et clé d'authentification
api_url = "https://kf.kobotoolbox.org/api/v2/assets/aHP3UroxqeCCCSQXUgxByV/data/?format=json"
headers = {"Authorization": "Token c700251b23afcdc188fcd30c68274996797149fd"}

# Télécharger les données de KoboCollect
data = download_kobo_data(api_url, headers)
if data:
    st.success("Données KoboCollect récupérées avec succès!")

    # Conversion des données JSON en DataFrame
    df_kobo = pd.json_normalize(data['results'])

    # Afficher les données brutes
    with st.expander("Données brutes"):
        st.dataframe(df_kobo)

    # Transformation des colonnes GPI et Sondage (si elles existent)
    for col in ['GPI', 'Sondage']:
        if col in df_kobo.columns:
            df_kobo[f'{col}_Transformed'] = df_kobo[col].apply(
                lambda x: ', '.join([str(obj) for obj in x]) if isinstance(x, list) else x
            )
            df_kobo.drop(columns=[col], inplace=True)

    # Traitement des données GPS (si la colonne existe et n'est pas vide)
    if 'GPS' in df_kobo.columns and df_kobo['GPS'].notna().any():
        gps_split = df_kobo['GPS'].str.split(' ', expand=True)
        if len(gps_split.columns) >= 4:
            df_kobo[['Latitude', 'Longitude', 'Altitude', 'Other']] = gps_split.apply(pd.to_numeric, errors='coerce')
        else:
            st.warning("Les données GPS ne sont pas au bon format.")

    # Conversion de la colonne de soumission en datetime
    if '_submission_time' in df_kobo.columns:
        df_kobo["_submission_time"] = pd.to_datetime(df_kobo["_submission_time"])
    else:
        st.error("La colonne '_submission_time' est manquante.")

    # Filtrage par date
    date1 = st.sidebar.date_input("Choisissez une date de début")
    date2 = st.sidebar.date_input("Choisissez une date de fin")

    date1 = pd.to_datetime(date1)
    date2 = pd.to_datetime(date2) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

    df_filtered = df_kobo[(df_kobo["_submission_time"] >= date1) & (df_kobo["_submission_time"] <= date2)]

    # Filtres supplémentaires
    st.sidebar.header("Filtres supplémentaires :")
    filters = {
        "Identification/Province": st.sidebar.multiselect("Province", sorted(df_filtered["Identification/Province"].dropna().unique())) if 'Identification/Province' in df_filtered.columns else [],
        "Identification/Commune": st.sidebar.multiselect("Commune", sorted(df_filtered["Identification/Commune"].dropna().unique())) if 'Identification/Commune' in df_filtered.columns else [],
        "Identification/Adresse_PDV": st.sidebar.multiselect("Avenue", sorted(df_filtered["Identification/Adresse_PDV"].dropna().unique())) if 'Identification/Adresse_PDV' in df_filtered.columns else [],
        "Name_Agent": st.sidebar.multiselect("Agent", sorted(df_filtered["Name_Agent"].dropna().unique())) if 'Name_Agent' in df_filtered.columns else []
    }

    for col, selection in filters.items():
        if selection:
            df_filtered = df_filtered[df_filtered[col].isin(selection)]

    # Bloc analytique
    with st.expander("Analyses"):
        a1, a2 = st.columns(2)

        if 'Sondage_Transformed' in df_filtered.columns:
            df_filtered['Sondage/PVT'] = pd.to_numeric(df_filtered['Sondage_Transformed'], errors='coerce')
            total_price = df_filtered['Sondage/PVT'].sum()
            num_rows = len(df_filtered)
            a1.metric(label="Nombre de PDVs", value=num_rows)
            a2.metric(label="Prix total", value=total_price)
        else:
            st.error("La colonne 'Sondage_Transformed' est manquante.")

    # Sélection de colonnes et téléchargement des données
    columns = st.multiselect("Colonnes à inclure dans le fichier téléchargé", options=df_kobo.columns.tolist(), default=df_kobo.columns.tolist())
    df_final = df_filtered[columns]

    st.subheader("Données filtrées")
    st.dataframe(df_final, use_container_width=True)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_final.to_excel(writer, index=False)
    processed_data = output.getvalue()

    st.download_button(
        label="Télécharger les données filtrées",
        data=processed_data,
        file_name="filtered_data.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Affichage de la carte
    if 'Latitude' in df_filtered.columns and 'Longitude' in df_filtered.columns:
        if not df_filtered[['Latitude', 'Longitude']].isna().all().any():
            df_filtered = df_filtered.dropna(subset=['Latitude', 'Longitude'])
            map_center = [df_filtered['Latitude'].mean(), df_filtered['Longitude'].mean()]
            map_folium = folium.Map(location=map_center, zoom_start=12)
            marker_cluster = MarkerCluster().add_to(map_folium)

            for _, row in df_filtered.iterrows():
                folium.Marker(
                    location=[row['Latitude'], row['Longitude']],
                    popup=f"Agent: {row['Identification/Name_PDV']}" if 'Identification/Name_PDV' in row else "Agent"
                ).add_to(marker_cluster)

            folium_static(map_folium)
        else:
            st.warning("Pas de données GPS valides pour afficher la carte.")
    else:
        st.warning("Les colonnes 'Latitude' et 'Longitude' sont manquantes.")

    # Graphiques
    col1, col2 = st.columns(2)

    with col1:
        if 'Identification/Type_PDV' in df_filtered.columns:
            st.subheader("Camembert Type_PDV")
            pie_chart_data = df_filtered['Identification/Type_PDV'].value_counts()
            fig = px.pie(pie_chart_data, values=pie_chart_data.values, names=pie_chart_data.index, title="Répartition Type_PDV", hole=0.3)
            fig.update_traces(textinfo='value', textposition='inside')
            st.plotly_chart(fig)

    with col2:
        if 'Name_Agent' in df_filtered.columns:
            st.subheader("Histogramme des agents")
            
            # Vérification que df_filtered n'est pas vide
            if not df_filtered.empty:
                # Utilisation correcte des colonnes pour l'histogramme
                bar_chart_data = df_filtered['Name_Agent'].value_counts()
                if not bar_chart_data.empty:
                    fig = px.bar(
                        bar_chart_data, 
                        x=bar_chart_data.index, 
                        y=bar_chart_data.values, 
                        labels={"x": "Nom Agent", "y": "Nombre d'occurrences"}, 
                        title="Nombre d'agents"
                    )
                    st.plotly_chart(fig)
                else:
                    st.warning("Aucune donnée pour l'histogramme des agents.")
            else:
                st.warning("Le DataFrame filtré est vide.")
