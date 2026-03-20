import streamlit as st
import geopandas as gpd
import pandas as pd
import folium
from folium.features import GeoJsonTooltip
from streamlit_folium import st_folium
from shapely.geometry import Point
import numbers

#Shapefile
SHAPEFILE_PATH = "data/noma_app.shp"

#Fields
STATE_FIELD = "state"
LGA_FIELD = "ADM2_EN"
UNIQUE_FIELD = "ID"
POPULATION_FIELD = "population"
STATE_INC_FIELD = "state_inc"
LGA_INCIDENCE_FIELD = "lga_risk"
RISK_LEVEL_FIELD = "lga_level"
SIGNIFICANCE_FIELD = "lga_sig"
FEMALE_RISK_FIELD = "risk_fem"
MALE_RISK_FIELD = "risk_males"
U5_RISK_FIELD = "bel5_risk"
AGE_5_9_RISK_FIELD = "5_9_risk"

#12 states
TARGET_STATES = [
    "Adamawa",
    "Bauchi",
    "Borno",
    "Jigawa",
    "Kaduna",
    "Kano",
    "Katsina",
    "Kebbi",
    "Niger",
    "Sokoto",
    "Yobe",
    "Zamfara",
]

# Geometry simplification for speed
SIMPLIFY_TOLERANCE = 0.0005

# Risk colors
RISK_COLORS = {
    "Low": "blue",
    "High": "red",
    "Unknown": "grey"
}

#streamlit

st.set_page_config(
    page_title="Nigerian Noma Incidence Risk Maps by LGAs",
    layout="wide"
)

st.markdown("""
    <style>
    div[data-testid="stMetricValue"] {
        font-size: 18px;
        color: violet;
        font-family: Arial, sans-serif;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 15px;
        font-weight: 700;
        color: blue;
    }
    section[data-testid="stSidebar"] {
        width: 70px !important; # Set your desired width here
    }
    </style>
""", unsafe_allow_html=True)

st.title(":green[Nigerian Noma Incidence Risk Maps]")
st.caption("Select a state, click an LGA on the map, and view detailed noma incidence risk estimates")


def format_value(value):
    """Format values neatly for display."""
    if value is None:
        return "No data"

    try:
        if pd.isna(value):
            return "No data"
    except Exception:
        pass

    if isinstance(value, numbers.Number):
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"

    return str(value)


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce")


@st.cache_data
def load_data(path):
    gdf = gpd.read_file(path)

    # Check that required columns exist
    required_fields = [
        STATE_FIELD,
        LGA_FIELD,
        UNIQUE_FIELD,
        POPULATION_FIELD,
        STATE_INC_FIELD,
        LGA_INCIDENCE_FIELD,
        RISK_LEVEL_FIELD,
        SIGNIFICANCE_FIELD,
        FEMALE_RISK_FIELD,
        MALE_RISK_FIELD,
        U5_RISK_FIELD,
        AGE_5_9_RISK_FIELD,
    ]

    missing = [col for col in required_fields if col not in gdf.columns]
    if missing:
        raise ValueError(
            f"These required fields are missing in your shapefile: {missing}\n\n"
            f"Available fields are:\n{list(gdf.columns)}"
        )

    # Clean text fields
    gdf[STATE_FIELD] = gdf[STATE_FIELD].astype(str).str.strip()
    gdf[LGA_FIELD] = gdf[LGA_FIELD].astype(str).str.strip()
    gdf[RISK_LEVEL_FIELD] = gdf[RISK_LEVEL_FIELD].astype(str).str.strip()

    # Restrict to the 12 states
    if TARGET_STATES is not None:
        gdf = gdf[gdf[STATE_FIELD].isin(TARGET_STATES)].copy()

    # Ensure CRS is correct for web maps
    if gdf.crs is None:
        raise ValueError("Your shapefile has no CRS defined. Please define a CRS before using this app.")

    if gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs(epsg=4326)

    # Simplify geometry for performance
    if SIMPLIFY_TOLERANCE and SIMPLIFY_TOLERANCE > 0:
        gdf["geometry"] = gdf["geometry"].simplify(
            SIMPLIFY_TOLERANCE,
            preserve_topology=True
        )

    # Create internal feature id
    gdf["__feature_id__"] = gdf[UNIQUE_FIELD].astype(str)

    # Make sure there are no duplicates
    duplicated_mask = gdf["__feature_id__"].duplicated(keep=False)
    if duplicated_mask.any():
        gdf.loc[duplicated_mask, "__feature_id__"] = (
            gdf.loc[duplicated_mask, "__feature_id__"] + "__" + gdf.loc[duplicated_mask].index.astype(str)
        )

    return gdf


def get_color_from_risk(risk_value):
    if risk_value is None:
        return RISK_COLORS["Unknown"]

    risk_value = str(risk_value).strip().title()
    return RISK_COLORS.get(risk_value, RISK_COLORS["Unknown"])



def add_legend(folium_map):
    legend_html = """
    <div style="
        position: fixed;
        bottom: 50px;
        left: 50px;
        width: 120px;
        z-index: 9999;
        background-color: white;
        border: 2px solid grey;
        border-radius: 3px;
        padding: 10px;
        font-size: 14px;
    ">
        <b>Risk level</b><br>
        <i style="background:blue; width:12px; height:12px; display:inline-block; margin-right:8px;"></i>Low<br>
        <i style="background:red; width:12px; height:12px; display:inline-block; margin-right:8px;"></i>High<br>
    </div>
    """
    folium_map.get_root().html.add_child(folium.Element(legend_html))


def build_map(state_gdf, selected_feature_id):
    bounds = state_gdf.total_bounds
    center_lat = (bounds[1] + bounds[3]) / 2
    center_lon = (bounds[0] + bounds[2]) / 2

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=8,
        tiles="cartodbpositron"
    )

    tooltip_fields = []
    tooltip_aliases = []

    for field, alias in [
        (LGA_FIELD, "LGA"),
        (LGA_INCIDENCE_FIELD, "Noma relative risk"),
        (RISK_LEVEL_FIELD, "Risk level"),
        (SIGNIFICANCE_FIELD, "Risk Significance"),
    ]:
        if field in state_gdf.columns:
            tooltip_fields.append(field)
            tooltip_aliases.append(alias)

    def style_function(feature):
        props = feature["properties"]
        feature_id = str(props.get("__feature_id__", ""))
        risk_val = props.get(RISK_LEVEL_FIELD, "Unknown")
        is_selected = feature_id == str(selected_feature_id)

        return {
            "fillColor": get_color_from_risk(risk_val),
            "color": "#0057B8" if is_selected else "#222222",
            "weight": 4 if is_selected else 1,
            "fillOpacity": 0.75,
        }

    def highlight_function(feature):
        return {
            "color": "#00FFFF",
            "weight": 3,
            "fillOpacity": 0.9
        }

    geojson = folium.GeoJson(
        data=state_gdf.to_json(),
        name="LGAs",
        style_function=style_function,
        highlight_function=highlight_function,
        tooltip=GeoJsonTooltip(
            fields=tooltip_fields,
            aliases=tooltip_aliases,
            localize=True,
            sticky=False,
            labels=True
        )
    )

    geojson.add_to(m)

    # Fit map to state bounds
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

    add_legend(m)
    return m


def get_clicked_feature_id(map_output, state_gdf):
    """
    First try reading the polygon properties directly.
    If that fails, use the clicked point and locate the polygon.
    """

    # Strategy 1: read polygon properties directly
    clicked_feature = map_output.get("last_active_drawing")
    if clicked_feature and isinstance(clicked_feature, dict):
        props = clicked_feature.get("properties", {})
        feature_id = props.get("__feature_id__")
        if feature_id is not None:
            return str(feature_id)

    # Strategy 2: fallback to point-in-polygon
    last_clicked = map_output.get("last_clicked")
    if last_clicked and "lat" in last_clicked and "lng" in last_clicked:
        pt = Point(last_clicked["lng"], last_clicked["lat"])
        matches = state_gdf[state_gdf.geometry.intersects(pt)]
        if not matches.empty:
            return str(matches.iloc[0]["__feature_id__"])

    return None


def render_state_summary(state_gdf):
    c1, c2, c3, c4, c5 = st.columns([2,3,4,3,2])

    c1.metric("State LGAs", len(state_gdf))

    if POPULATION_FIELD in state_gdf.columns:
        total_pop = safe_numeric(state_gdf[POPULATION_FIELD]).fillna(0).sum()
        c2.metric("State population (2006)", f"{int(total_pop):,}")
    else:
        c2.metric("State population (2006)", "N/A")

    if STATE_INC_FIELD in state_gdf.columns:
        state_incidence = state_gdf[STATE_INC_FIELD].dropna()
        if not state_incidence.empty:
            c3.metric("Estimated state incidence (per 100,000)", format_value(state_incidence.iloc[0]))
        else:
            c3.metric("State incidence", "N/A")

    if LGA_INCIDENCE_FIELD in state_gdf.columns:
        avg_lga_inc = safe_numeric(state_gdf[LGA_INCIDENCE_FIELD]).mean()
        c4.metric("Average LGA risk", "N/A" if pd.isna(avg_lga_inc) else f"{avg_lga_inc:,.2f}")
    else:
        c4.metric("Average LGA risk", "N/A")

    if RISK_LEVEL_FIELD in state_gdf.columns:
        high_count = state_gdf[RISK_LEVEL_FIELD].astype(str).str.strip().eq("High").sum()
        c5.metric("High-risk LGAs", f"{int(high_count):,}")
    else:
        c5.metric("High-risk LGAs", "N/A")



def render_detail_panel(selected_row):
    st.subheader(f":green[{selected_row[LGA_FIELD]}]")
    st.caption(f"#### :gray[State: {selected_row[STATE_FIELD]}]")

    # Main metrics
    c1, c2 = st.columns(2)
    c1.metric("Population", format_value(selected_row.get(POPULATION_FIELD, None)))
    c2.metric("Relative risk (RR)", format_value(selected_row.get(LGA_INCIDENCE_FIELD, None)))
    
    c3, c4 = st.columns(2)
    c3.metric("Risk level", format_value(selected_row.get(RISK_LEVEL_FIELD, None)))
    c4.metric("RR Significance", format_value(selected_row.get(SIGNIFICANCE_FIELD, None)))


    st.markdown("---")

    # Other detailed values
    st.markdown("## :blue[Stratified Estimates]")

    d1,d2 = st.columns(2)
    d1.metric("Risk (Females)", format_value(selected_row.get(FEMALE_RISK_FIELD, None)))
    d2.metric("Risk (Males)", format_value(selected_row.get(MALE_RISK_FIELD, None)))

    d3,d4 = st.columns(2)
    d3.metric("Under-5 risk", format_value(selected_row.get(U5_RISK_FIELD, None)))
    d4.metric("Ages 5-9 risk", format_value(selected_row.get(AGE_5_9_RISK_FIELD, None)))

    st.markdown("---")

    with st.expander("Show all LGA attributes"):
        raw = pd.DataFrame({
            "Field": [col for col in selected_row.index if col != "geometry"],
            "Value": [format_value(selected_row[col]) for col in selected_row.index if col != "geometry"]
        })
        st.dataframe(raw, use_container_width=True, hide_index=True)


# DATA

try:
    gdf = load_data(SHAPEFILE_PATH)
except Exception as e:
    st.error("Error loading shapefile.")
    st.exception(e)
    st.stop()

if gdf.empty:
    st.warning("No records found after loading/filtering the shapefile.")
    st.stop()


if "selected_feature_id" not in st.session_state:
    st.session_state["selected_feature_id"] = None

if "selected_state" not in st.session_state:
    st.session_state["selected_state"] = None

#Side bar

st.sidebar.header("Selection")


states = sorted(gdf[STATE_FIELD].dropna().unique().tolist())

default_index = 0
if st.session_state["selected_state"] in states:
    default_index = states.index(st.session_state["selected_state"])

selected_state = st.sidebar.selectbox(
    "Select a state below",
    states,
    index=default_index
)

if selected_state != st.session_state["selected_state"]:
    st.session_state["selected_state"] = selected_state
    st.session_state["selected_feature_id"] = None

if st.sidebar.button("Clear selected LGA"):
    st.session_state["selected_feature_id"] = None
    st.rerun()

state_gdf = gdf[gdf[STATE_FIELD] == selected_state].copy()

if state_gdf.empty:
    st.warning(f"No LGA features found for state: {selected_state}")
    st.stop()

st.sidebar.markdown('####')
st.sidebar.markdown('####')
st.sidebar.markdown('####')
st.sidebar.error("You can collapse the SIDEBAR to view the details more clearly.")


#Summary

st.markdown(f"## {selected_state}")
render_state_summary(state_gdf)

#Layout

map_col, detail_col = st.columns([2.2, 1])

#Map appearance

with map_col:
    selected_feature_id = st.session_state["selected_feature_id"]
    m = build_map(state_gdf, selected_feature_id)

    map_output = st_folium(
        m,
        width=800,
        height=600,
        returned_objects=["last_active_drawing", "last_clicked"]
    )

    clicked_feature_id = get_clicked_feature_id(map_output, state_gdf)

    if clicked_feature_id and clicked_feature_id != st.session_state["selected_feature_id"]:
        st.session_state["selected_feature_id"] = clicked_feature_id
        st.rerun()

#Noma incidence risk panel

with detail_col:
    st.markdown("## :blue[LGA Estimates]")

    selected_feature_id = st.session_state["selected_feature_id"]

    if selected_feature_id is None:
        st.info("Click an LGA on the map on the left to see its noma incidence risk here.")
    else:
        selected_rows = state_gdf[state_gdf["__feature_id__"] == selected_feature_id]

        if selected_rows.empty:
            st.warning("The selected LGA could not be found.")
        else:
            selected_row = selected_rows.iloc[0]
            render_detail_panel(selected_row)

st.markdown('####')
st.markdown('####')
st.write("#### :gray[References:]")
st.write("Braimah RO, Taiwo AO, Bello S, et al. Spatial Distribution of Noma Incidence in Northern Nigeria, 1999-2024: A model-based study. (In Press: The Lancet Global Health)")
st.write("[Braimah RO, Adeoye J, Taiwo AO, Bello S, Bala M, Butali A, Ile-Ogedengbe BO, Bello AA. Estimated incidence and clinical presentation of Noma in Northern Nigeria (1999-2024).PLoS Negl Trop Dis. 2025 May 29;19(5):e0012818.](https://doi.org/10.1371/journal.pntd.0012818)")
st.markdown('####')
st.markdown('####')
st.markdown('####')
st.write("###### This web tool is supported by the HKU Knowledge Exchange Impact Project Scheme (KE-SI-2025/26-12)  | 2026")
